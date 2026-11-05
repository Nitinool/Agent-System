use crate::model::*;
use chrono::{Local, NaiveDate};
use rusqlite::{params, Connection, TransactionBehavior};
use std::path::Path;

pub struct Store {
    conn: Connection,
}
fn ensure(ok: bool, message: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(AppError::new("validation", message))
    }
}
fn date(value: &str) -> Result<()> {
    ensure(
        value.len() == 10
            && NaiveDate::parse_from_str(value, "%Y-%m-%d")
                .is_ok_and(|d| d.format("%Y-%m-%d").to_string() == value),
        "日期必须是有效的 YYYY-MM-DD。",
    )
}
fn validate(draft: &mut Draft) -> Result<()> {
    draft.title = draft.title.trim().into();
    ensure(
        !draft.title.is_empty() && draft.title.chars().count() <= 200,
        "事项名称不能为空，最多 200 字。",
    )?;
    ensure(draft.notes.chars().count() <= 50_000, "备注最多 50000 字。")?;
    ensure(draft.category.chars().count() <= 40, "分类最多 40 字。")?;
    ensure(
        draft.color.len() == 7
            && draft.color.starts_with('#')
            && draft.color[1..].bytes().all(|c| c.is_ascii_hexdigit()),
        "请选择有效的事项颜色。",
    )?;
    if let Some(start) = &draft.start {
        date(start)?;
    }
    if let Some(end) = &draft.end {
        date(end)?;
    }
    ensure(
        draft.end.is_none() || draft.start.is_some(),
        "设置结束日期前，请先选择开始日期。",
    )?;
    ensure(
        draft.end.is_none() || draft.end >= draft.start,
        "结束日期不能早于开始日期。",
    )
}
pub fn on_day(task: &Task, day: &str) -> bool {
    !task.excluded_days.iter().any(|d| d == day)
        && (task.included_days.iter().any(|d| d == day)
            || task
                .start
                .as_deref()
                .is_some_and(|s| s <= day && day <= task.end.as_deref().unwrap_or(s)))
}
impl Store {
    pub fn open(path: &Path) -> Result<Self> {
        let conn = Connection::open(path)?;
        conn.busy_timeout(std::time::Duration::from_secs(5))?;
        let version: i32 = conn.query_row("PRAGMA user_version", [], |r| r.get(0))?;
        ensure(version <= 1, "资料来自更高版本，请更新应用；未修改数据。")?;
        conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
            INSERT OR IGNORE INTO state VALUES(1,0);
            PRAGMA user_version=1; COMMIT;")?;
        Ok(Self { conn })
    }
    pub fn snapshot(&self) -> Result<Snapshot> {
        let revision = self
            .conn
            .query_row("SELECT revision FROM state WHERE id=1", [], |r| r.get(0))?;
        let mut statement = self
            .conn
            .prepare("SELECT payload FROM tasks ORDER BY rowid")?;
        let mut tasks = vec![];
        for row in statement.query_map([], |r| r.get::<_, String>(0))? {
            tasks.push(serde_json::from_str(&row?)?);
        }
        Ok(Snapshot { revision, tasks })
    }
    pub fn mutate(&mut self, mutation: Mutation, revision: u32) -> Result<Snapshot> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: u32 =
            tx.query_row("SELECT revision FROM state WHERE id=1", [], |r| r.get(0))?;
        if current != revision {
            return Err(AppError::new(
                "stale",
                "另一个窗口已修改事项，已刷新列表，请重试；编辑内容仍保留。",
            ));
        }
        let id = match &mutation {
            Mutation::Save { id, .. } => id
                .clone()
                .unwrap_or_else(|| uuid::Uuid::new_v4().to_string()),
            Mutation::Complete { id, .. }
            | Mutation::Delete { id }
            | Mutation::Today { id, .. } => id.clone(),
        };
        let payload: Option<String> = tx
            .query_row("SELECT payload FROM tasks WHERE id=?", [&id], |r| r.get(0))
            .optional()?;
        let mut task: Option<Task> = payload.as_deref().map(serde_json::from_str).transpose()?;
        let now = Local::now().to_rfc3339();
        match mutation {
            Mutation::Save {
                id: existing,
                mut draft,
            } => {
                validate(&mut draft)?;
                ensure(
                    existing.is_none() || task.is_some(),
                    "事项已被删除，请重新新增。",
                )?;
                let mut t = task.unwrap_or_else(|| Task {
                    id: id.clone(),
                    title: String::new(),
                    start: None,
                    end: None,
                    category: String::new(),
                    color: String::new(),
                    notes: String::new(),
                    completed: false,
                    completions: vec![],
                    included_days: vec![],
                    excluded_days: vec![],
                    created_at: now.clone(),
                    updated_at: now.clone(),
                });
                let end = draft.end.or_else(|| draft.start.clone());
                if t.start != draft.start || t.end != end {
                    t.excluded_days.clear();
                }
                t.title = draft.title;
                t.start = draft.start;
                t.end = end;
                t.category = draft.category;
                t.color = draft.color;
                t.notes = draft.notes;
                task = Some(t);
            }
            Mutation::Complete { completed, .. } => {
                let t = task
                    .as_mut()
                    .ok_or_else(|| AppError::new("missing", "事项已被删除。"))?;
                if completed && !t.completed {
                    t.completions.push(Completion {
                        completed_at: now.clone(),
                        reopened_at: None,
                    });
                }
                if !completed && t.completed {
                    if let Some(event) = t.completions.last_mut() {
                        event.reopened_at = Some(now.clone());
                    }
                }
                t.completed = completed;
            }
            Mutation::Today { day, included, .. } => {
                date(&day)?;
                let t = task
                    .as_mut()
                    .ok_or_else(|| AppError::new("missing", "事项已被删除。"))?;
                t.included_days.retain(|d| d != &day);
                t.excluded_days.retain(|d| d != &day);
                if included {
                    t.included_days.push(day);
                } else {
                    t.excluded_days.push(day);
                }
            }
            Mutation::Delete { .. } => {
                ensure(task.is_some(), "事项已被删除。")?;
                tx.execute("DELETE FROM tasks WHERE id=?", [&id])?;
                task = None;
            }
        }
        if let Some(mut t) = task {
            t.updated_at = now;
            tx.execute("INSERT INTO tasks(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", params![id, serde_json::to_string(&t)?])?;
        }
        tx.execute("UPDATE state SET revision=revision+1 WHERE id=1", [])?;
        tx.commit()?;
        self.snapshot()
    }
}
use rusqlite::OptionalExtension;
