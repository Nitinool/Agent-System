//! SQLite is owned by one worker. Business operations validate before committing.
use crate::{model::*, rules};
use chrono::Local;
use rusqlite::{params, Connection};
use std::{
    cell::Cell,
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::mpsc,
};

const SCHEMA: &str = "
CREATE TABLE records(local_id INTEGER PRIMARY KEY, uid TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO state VALUES('revision','0');
INSERT INTO state VALUES('baseline','{}');
CREATE TABLE segments(id INTEGER PRIMARY KEY,start TEXT NOT NULL,last_seen TEXT NOT NULL,end TEXT,seconds REAL NOT NULL CHECK(seconds>=0),app TEXT NOT NULL,process TEXT NOT NULL,title TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,reason TEXT NOT NULL,resume_reason TEXT NOT NULL,category TEXT NOT NULL);
CREATE INDEX segment_dates ON segments(start,last_seen);
PRAGMA user_version=1;";

pub struct Store {
    pub db: Connection,
    pub path: PathBuf,
    external_version: Cell<u32>,
    external_revision: Cell<u32>,
}
impl Store {
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let db = Connection::open(path)?;
        db.busy_timeout(std::time::Duration::from_secs(3))?;
        db.execute_batch("PRAGMA foreign_keys=ON;")?;
        let version: u32 = db.query_row("PRAGMA user_version", [], |r| r.get(0))?;
        let tables: u32 = db.query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='table'",
            [],
            |r| r.get(0),
        )?;
        if version == 0 && tables == 0 {
            let tx = db.unchecked_transaction()?;
            tx.execute_batch(SCHEMA)?;
            tx.commit()?;
        } else if version != 1 {
            return Err(AppError::new(
                "schema",
                "此数据库不是新版支持的数据文件，未修改文件。",
            ));
        }
        db.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;")?;
        db.execute("UPDATE segments SET end=last_seen,status='interrupted',reason='上次异常退出，仅保留已采样时长' WHERE status='running'", [])?;
        let external_version = db.query_row("PRAGMA data_version", [], |r| r.get(0))?;
        Ok(Self {
            db,
            path: path.into(),
            external_version: Cell::new(external_version),
            external_revision: Cell::new(0),
        })
    }
    pub fn revision(&self) -> Result<u32> {
        let external: u32 = self.db.query_row("PRAGMA data_version", [], |r| r.get(0))?;
        if self.external_version.replace(external) != external {
            self.external_revision
                .set(self.external_revision.get().wrapping_add(1));
        }
        Ok(self
            .db
            .query_row("SELECT value FROM state WHERE key='revision'", [], |r| {
                let s: String = r.get(0)?;
                s.parse::<u32>().map_err(|_| rusqlite::Error::InvalidQuery)
            })?
            .wrapping_add(self.external_revision.get()))
    }
    pub fn snapshot(&self) -> Result<Snapshot> {
        let _read = self.db.unchecked_transaction()?;
        let mut rows = self
            .db
            .prepare("SELECT uid,local_id,payload FROM records ORDER BY local_id")?;
        let mut records = BTreeMap::new();
        let mut local_ids = BTreeMap::new();
        for row in rows.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, u32>(1)?,
                r.get::<_, String>(2)?,
            ))
        })? {
            let (uid, id, payload) = row?;
            local_ids.insert(uid.clone(), id);
            records.insert(uid, serde_json::from_str(&payload)?);
        }
        Ok(Snapshot {
            revision: self.revision()?,
            records,
            local_ids,
        })
    }
    pub fn baseline(&self) -> Result<Records> {
        let s: String =
            self.db
                .query_row("SELECT value FROM state WHERE key='baseline'", [], |r| {
                    r.get(0)
                })?;
        Ok(serde_json::from_str(&s)?)
    }
    pub fn synced_at(&self) -> Option<String> {
        self.db
            .query_row("SELECT value FROM state WHERE key='synced_at'", [], |r| {
                r.get(0)
            })
            .ok()
    }
    pub fn mutate(&mut self, mutation: Mutation, expected: u32) -> Result<Snapshot> {
        let old = self.snapshot()?;
        if old.revision != expected {
            return Err(AppError::new(
                "local_changed",
                "数据已更新，请刷新后重试；草稿仍保留。",
            ));
        }
        let mut records = old.records.clone();
        rules::mutate(&mut records, mutation, &Local::now().to_rfc3339())?;
        self.replace(&old.records, &records, None)?;
        self.snapshot()
    }
    pub fn import(&mut self, expected: &Records, records: &Records) -> Result<Snapshot> {
        rules::validate(records)?;
        if self.snapshot()?.records != *expected {
            return Err(AppError::new(
                "local_changed",
                "同步期间本地有修改，未覆盖；请再次同步。",
            ));
        }
        if records != expected {
            let backups = self.path.parent().unwrap().join("backups");
            std::fs::create_dir_all(&backups)?;
            let mut target = Connection::open(backups.join(format!(
                "before-sync-{}.sqlite3",
                Local::now().format("%Y%m%d-%H%M%S-%f")
            )))?;
            rusqlite::backup::Backup::new(&self.db, &mut target)?.run_to_completion(
                64,
                std::time::Duration::from_millis(1),
                None,
            )?;
        }
        self.replace(expected, records, Some(&Local::now().to_rfc3339()))?;
        self.snapshot()
    }
    fn replace(&mut self, expected: &Records, records: &Records, at: Option<&str>) -> Result<()> {
        let tx = self
            .db
            .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let mut actual = Records::new();
        {
            let mut statement = tx.prepare("SELECT uid,payload FROM records")?;
            for row in
                statement.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?
            {
                let (id, payload) = row?;
                actual.insert(id, serde_json::from_str(&payload)?);
            }
        }
        if actual != *expected {
            return Err(AppError::new("local_changed", "本地记录已变化，请重试。"));
        }
        for (uid, r) in records {
            if expected.get(uid) != Some(r) {
                tx.execute("INSERT INTO records(uid,kind,payload) VALUES(?,?,?) ON CONFLICT(uid) DO UPDATE SET kind=excluded.kind,payload=excluded.payload", params![uid, r.kind(), serde_json::to_string(r)?])?;
            }
        }
        if records != expected {
            tx.execute(
                "UPDATE state SET value=CAST(value AS INTEGER)+1 WHERE key='revision'",
                [],
            )?;
        }
        if let Some(time) = at {
            tx.execute(
                "UPDATE state SET value=? WHERE key='baseline'",
                [serde_json::to_string(records)?],
            )?;
            tx.execute("INSERT INTO state(key,value) VALUES('synced_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", [time])?;
        }
        tx.commit()?;
        Ok(())
    }
    pub fn save_segments(&self, rows: &[Segment]) -> Result<()> {
        let tx = self.db.unchecked_transaction()?;
        for s in rows {
            tx.execute("INSERT INTO segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen,end=excluded.end,seconds=excluded.seconds,status=excluded.status,reason=excluded.reason", params![s.id,s.start,s.last_seen,s.end,s.seconds,s.app,s.process,s.title,s.kind,s.status,s.reason,s.resume_reason,s.category])?;
        }
        tx.commit()?;
        Ok(())
    }
    pub fn segments(&self, day: Option<&str>) -> Result<Vec<Segment>> {
        if let Some(d) = day {
            rules::day(d)?;
        }
        let mut statement = self.db.prepare("SELECT * FROM segments WHERE ? IS NULL OR (substr(start,1,10)<=? AND substr(last_seen,1,10)>=?) ORDER BY start DESC,id DESC")?;
        let rows = statement.query_map(params![day, day, day], |r| {
            Ok(Segment {
                id: r.get(0)?,
                start: r.get(1)?,
                last_seen: r.get(2)?,
                end: r.get(3)?,
                seconds: r.get(4)?,
                app: r.get(5)?,
                process: r.get(6)?,
                title: r.get(7)?,
                kind: r.get(8)?,
                status: r.get(9)?,
                reason: r.get(10)?,
                resume_reason: r.get(11)?,
                category: r.get(12)?,
            })
        })?;
        let mut result = Vec::new();
        for row in rows {
            let mut segment = row?;
            if let Some(d) = day {
                let end = chrono::DateTime::parse_from_rfc3339(&segment.last_seen)
                    .map_err(|_| AppError::validation("记录时间无效。"))?;
                if segment.start.get(..10).is_some_and(|start| start < d)
                    && end.date_naive() == rules::day(d)?
                    && end.time() == chrono::NaiveTime::MIN
                {
                    continue;
                }
                crate::capture::clip(&mut segment, d)?;
            }
            result.push(segment);
        }
        Ok(result)
    }
    pub fn classify(&self, ids: &[i64], category: &str) -> Result<()> {
        if !["开发", "学习", "求职", "娱乐", "沟通", "其他", "未分类"].contains(&category)
        {
            return Err(AppError::validation("分类无效。"));
        }
        let tx = self.db.unchecked_transaction()?;
        for id in ids {
            tx.execute(
                "UPDATE segments SET category=? WHERE id=? AND kind='activity'",
                params![category, id],
            )?;
        }
        tx.commit()?;
        Ok(())
    }
}

type Work = Box<dyn FnOnce(&mut Store) + Send>;
#[derive(Clone)]
pub struct Database {
    tx: mpsc::SyncSender<Work>,
}
impl Database {
    pub fn start(path: PathBuf) -> Result<Self> {
        let (tx, rx) = mpsc::sync_channel::<Work>(64);
        let (ready, initialized) = mpsc::channel();
        std::thread::Builder::new()
            .name("sqlite-owner".into())
            .spawn(move || {
                let mut store = match Store::open(&path) {
                    Ok(s) => {
                        let _ = ready.send(Ok(()));
                        s
                    }
                    Err(e) => {
                        let _ = ready.send(Err(e));
                        return;
                    }
                };
                for work in rx {
                    work(&mut store);
                }
            })?;
        initialized
            .recv()
            .map_err(|_| AppError::new("storage", "数据库线程未能启动。"))??;
        Ok(Self { tx })
    }
    pub fn call<T: Send + 'static>(
        &self,
        operation: impl FnOnce(&mut Store) -> Result<T> + Send + 'static,
    ) -> Result<T> {
        let (tx, rx) = mpsc::channel();
        self.tx
            .send(Box::new(move |store| {
                let _ = tx.send(operation(store));
            }))
            .map_err(|_| AppError::new("closed", "数据库已关闭。"))?;
        rx.recv()
            .map_err(|_| AppError::new("closed", "数据库操作已中断。"))?
    }
}
