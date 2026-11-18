use crate::model::{AppError, Completion, Result};
use chrono::{Local, NaiveDate};
use rusqlite::{params, Connection, DatabaseName, OptionalExtension, TransactionBehavior};
use serde::Deserialize;
use std::path::{Path, PathBuf};

/// schema 2 的完整结构。可重复执行，用于新建资料与迁移后建表。
pub const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS projects(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  color TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  favorite INTEGER NOT NULL DEFAULT 0,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sections(
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sections_project ON sections(project_id, position);
CREATE TABLE IF NOT EXISTS labels(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  color TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(id),
  section_id TEXT REFERENCES sections(id) ON DELETE SET NULL,
  parent_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  notes TEXT NOT NULL DEFAULT '',
  color TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 4 CHECK(priority BETWEEN 1 AND 4),
  start_date TEXT,
  end_date TEXT,
  position INTEGER NOT NULL DEFAULT 0,
  completed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_project ON tasks(project_id, position);
CREATE INDEX IF NOT EXISTS tasks_parent ON tasks(parent_id, position);
CREATE INDEX IF NOT EXISTS tasks_dates ON tasks(start_date, end_date);
CREATE TABLE IF NOT EXISTS task_labels(
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  label_id TEXT NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
  PRIMARY KEY(task_id, label_id)
);
CREATE TABLE IF NOT EXISTS task_completions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  completed_at TEXT NOT NULL,
  reopened_at TEXT
);
CREATE INDEX IF NOT EXISTS completions_task ON task_completions(task_id, id);
CREATE TABLE IF NOT EXISTS task_days(
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  day TEXT NOT NULL,
  included INTEGER NOT NULL,
  PRIMARY KEY(task_id, day)
);
CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
INSERT OR IGNORE INTO state VALUES(1,0);
";

/// 标签颜色沿用界面的八色调色板，保证迁移后视觉不突变。
const PALETTE: [&str; 8] = [
    "#3b82f6", "#8b5cf6", "#0891b2", "#ca8a04", "#db2777", "#16a34a", "#ea580c", "#475569",
];

#[derive(Deserialize)]
struct LegacyTask {
    id: String,
    title: String,
    #[serde(default)]
    start: Option<String>,
    #[serde(default)]
    end: Option<String>,
    #[serde(default)]
    category: String,
    #[serde(default)]
    color: String,
    #[serde(default)]
    notes: String,
    #[serde(default)]
    completed: bool,
    #[serde(default)]
    completions: Vec<Completion>,
    #[serde(default)]
    included_days: Vec<String>,
    #[serde(default)]
    excluded_days: Vec<String>,
    created_at: String,
    updated_at: String,
}

fn stamp() -> String {
    Local::now().format("%Y%m%d-%H%M%S").to_string()
}

fn backup(conn: &Connection, database: &Path) -> Result<PathBuf> {
    let directory = database
        .parent()
        .ok_or_else(|| AppError::new("io", "无法确定事项便签数据目录。"))?
        .join("backups");
    std::fs::create_dir_all(&directory)?;
    let mut path = directory.join(format!("tasks-{}.sqlite3", stamp()));
    let mut suffix = 1;
    while path.exists() {
        path = directory.join(format!("tasks-{}-{suffix}.sqlite3", stamp()));
        suffix += 1;
    }
    // 用 SQLite 备份接口，连同 WAL 内容一起落盘，避免只拷贝主文件导致数据缺失。
    conn.backup(DatabaseName::Main, &path, None)?;
    Ok(path)
}

/// 新建资料：直接建 schema 2。
pub fn create(conn: &Connection) -> Result<()> {
    let tx = conn.unchecked_transaction()?;
    tx.execute_batch(SCHEMA)?;
    tx.execute_batch("PRAGMA user_version=2;")?;
    tx.commit()?;
    Ok(())
}

/// schema 1 → 2。先备份，再在一个事务里改名旧表、建新表、逐条搬运；任何一步失败都回滚。
pub fn upgrade_from_1(conn: &mut Connection, database: &Path) -> Result<PathBuf> {
    let saved = backup(conn, database)?;
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let moved = move_legacy(&tx)?;
    verify(&tx, moved)?;
    tx.execute_batch("DROP TABLE legacy_tasks;")?;
    tx.execute_batch("PRAGMA user_version=2;")?;
    tx.commit()?;
    Ok(saved)
}

struct Moved {
    tasks: i64,
    completions: i64,
    days: i64,
    revision: i64,
}

fn move_legacy(tx: &rusqlite::Transaction<'_>) -> Result<Moved> {
    let revision: i64 = tx
        .query_row("SELECT revision FROM state WHERE id=1", [], |r| r.get(0))
        .optional()?
        .unwrap_or(0);
    tx.execute_batch("ALTER TABLE tasks RENAME TO legacy_tasks;")?;
    tx.execute_batch(SCHEMA)?;
    tx.execute("UPDATE state SET revision=?1 WHERE id=1", [revision])?;

    let mut statement = tx.prepare("SELECT rowid, payload FROM legacy_tasks ORDER BY rowid")?;
    let rows = statement
        .query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    drop(statement);

    let now = Local::now().to_rfc3339();
    let mut labels: Vec<(String, String)> = Vec::new();
    let mut tasks = 0;
    let mut completions = 0;
    let mut days = 0;
    for (rowid, payload) in rows {
        let legacy: LegacyTask = serde_json::from_str(&payload).map_err(|_| {
            AppError::new(
                "migration",
                "旧事项数据无法解析，已停止升级并保留原数据与备份；请不要继续操作数据文件。",
            )
        })?;
        if legacy.id.trim().is_empty() {
            return Err(AppError::new("migration", "旧事项中存在空编号，已停止升级。"));
        }
        // 日期字段沿用旧语义：结束为空即单日；不合法的旧值按缺失处理，不猜。
        let valid = |v: &Option<String>| {
            v.as_deref().is_some_and(|d| {
                d.len() == 10
                    && NaiveDate::parse_from_str(d, "%Y-%m-%d")
                        .is_ok_and(|x| x.format("%Y-%m-%d").to_string() == d)
            })
        };
        let start = if valid(&legacy.start) {
            legacy.start.clone()
        } else {
            None
        };
        let end = if valid(&legacy.end) {
            legacy.end.clone()
        } else {
            None
        };
        let color = if legacy.color.len() == 7 && legacy.color.starts_with('#') {
            legacy.color.clone()
        } else {
            PALETTE[0].to_string()
        };
        tx.execute(
            "INSERT INTO tasks(id,project_id,section_id,parent_id,title,notes,color,priority,start_date,end_date,position,completed,created_at,updated_at)
             VALUES(?1,NULL,NULL,NULL,?2,?3,?4,4,?5,?6,?7,?8,?9,?10)",
            params![
                legacy.id,
                legacy.title,
                legacy.notes,
                color,
                start,
                end,
                rowid,
                legacy.completed,
                legacy.created_at,
                legacy.updated_at
            ],
        )?;
        tasks += 1;
        // 旧的单值分类迁成标签：单值本来就是多值标签的子集，语义不丢。
        let category = legacy.category.trim().to_string();
        if !category.is_empty() && category != "其他" {
            let index = match labels.iter().position(|(name, _)| name == &category) {
                Some(index) => index,
                None => {
                    labels.push((
                        category.clone(),
                        PALETTE[labels.len() % PALETTE.len()].to_string(),
                    ));
                    labels.len() - 1
                }
            };
            let name = &labels[index].0;
            let id: Option<String> = tx
                .query_row("SELECT id FROM labels WHERE name=?1", [name], |r| r.get(0))
                .optional()?;
            let label_id = match id {
                Some(id) => id,
                None => {
                    let id = uuid::Uuid::new_v4().to_string();
                    tx.execute(
                        "INSERT INTO labels(id,name,color,position,created_at,updated_at) VALUES(?1,?2,?3,?4,?5,?5)",
                        params![id, labels[index].0, labels[index].1, index as i64, now],
                    )?;
                    id
                }
            };
            tx.execute(
                "INSERT OR IGNORE INTO task_labels(task_id,label_id) VALUES(?1,?2)",
                params![legacy.id, label_id],
            )?;
        }
        for day in legacy.included_days.iter().filter(|d| d.len() == 10) {
            tx.execute(
                "INSERT OR REPLACE INTO task_days(task_id,day,included) VALUES(?1,?2,1)",
                params![legacy.id, day],
            )?;
            days += 1;
        }
        for day in legacy.excluded_days.iter().filter(|d| d.len() == 10) {
            tx.execute(
                "INSERT OR REPLACE INTO task_days(task_id,day,included) VALUES(?1,?2,0)",
                params![legacy.id, day],
            )?;
            days += 1;
        }
        for completion in &legacy.completions {
            tx.execute(
                "INSERT INTO task_completions(task_id,completed_at,reopened_at) VALUES(?1,?2,?3)",
                params![legacy.id, completion.completed_at, completion.reopened_at],
            )?;
            completions += 1;
        }
    }
    Ok(Moved {
        tasks,
        completions,
        days,
        revision,
    })
}

/// 迁移后核对条数与版本号，对不上就回滚，绝不带着半份数据继续用。
fn verify(tx: &rusqlite::Transaction<'_>, moved: Moved) -> Result<()> {
    let tasks: i64 = tx.query_row("SELECT COUNT(*) FROM tasks", [], |r| r.get(0))?;
    let completions: i64 =
        tx.query_row("SELECT COUNT(*) FROM task_completions", [], |r| r.get(0))?;
    let days: i64 = tx.query_row("SELECT COUNT(*) FROM task_days", [], |r| r.get(0))?;
    let revision: i64 = tx.query_row("SELECT revision FROM state WHERE id=1", [], |r| r.get(0))?;
    if tasks != moved.tasks || completions != moved.completions || revision != moved.revision {
        return Err(AppError::new(
            "migration",
            "升级后的条数与旧数据不一致，已回滚并保留备份；请先别继续写入。",
        ));
    }
    // 同一事项同一天可能既被加入又被移出，键冲突会被合并，所以只要求不超过搬运数。
    if days > moved.days {
        return Err(AppError::new(
            "migration",
            "升级后的日期归属记录异常，已回滚并保留备份。",
        ));
    }
    Ok(())
}
