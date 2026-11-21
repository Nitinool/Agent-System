use crate::{
    migrate,
    model::{AppError, Result, *},
};
use chrono::{Local, NaiveDate};
use rusqlite::{params, Connection, OptionalExtension, Row, TransactionBehavior};
use std::collections::HashMap;
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

fn color(value: &str) -> Result<()> {
    ensure(
        value.len() == 7
            && value.starts_with('#')
            && value[1..].bytes().all(|c| c.is_ascii_hexdigit()),
        "请选择有效的颜色。",
    )
}

/// 事项是否落在某一天：显式排除优先，其次显式加入，最后看日期范围。
pub fn on_day(task: &Task, day: &str) -> bool {
    !task.excluded_days.iter().any(|d| d == day)
        && (task.included_days.iter().any(|d| d == day)
            || task
                .start
                .as_deref()
                .is_some_and(|s| s <= day && day <= task.end.as_deref().unwrap_or(s)))
}

/// 事项在某一天是否出现：重复事项只看规则与截止日，其余沿用日期范围 + 显式加减。
pub fn occurs_on(task: &Task, day: &str) -> bool {
    match &task.recurrence {
        None => on_day(task, day),
        Some(rule) => {
            let Some(start) = task.start.as_deref() else {
                return false;
            };
            if day < start {
                return false;
            }
            if let Some(until) = task.repeat_until.as_deref() {
                if day > until {
                    return false;
                }
            }
            if task.excluded_days.iter().any(|d| d == day) {
                return false;
            }
            recurrence_matches(start, rule, day)
        }
    }
}

/// 规则是否命中某天。`daily` 每天一次；`every:N` 从开始日期起每 N 天一次。
pub fn recurrence_matches(start: &str, rule: &str, day: &str) -> bool {
    let Some(step) = recurrence_step(rule) else {
        return false;
    };
    match (NaiveDate::parse_from_str(start, "%Y-%m-%d"), NaiveDate::parse_from_str(day, "%Y-%m-%d")) {
        (Ok(start), Ok(day)) => {
            let gap = (day - start).num_days();
            gap >= 0 && gap % step as i64 == 0
        }
        _ => false,
    }
}

pub fn recurrence_step(rule: &str) -> Option<u32> {
    if rule == "daily" {
        return Some(1);
    }
    rule.strip_prefix("every:")
        .and_then(|value| value.parse::<u32>().ok())
        .filter(|value| (1..=365).contains(value))
}

/// 从 `start` 出发、严格晚于 `after` 的下一次日期；用来在完成后把到期日往前滚。
pub fn next_occurrence(start: &str, rule: &str, after: &str) -> Option<String> {
    let step = recurrence_step(rule)? as i64;
    let start = NaiveDate::parse_from_str(start, "%Y-%m-%d").ok()?;
    let after = NaiveDate::parse_from_str(after, "%Y-%m-%d").ok()?;
    if start > after {
        return Some(start.format("%Y-%m-%d").to_string());
    }
    let gap = (after - start).num_days();
    let mut index = gap / step;
    if start + chrono::Duration::days(index * step) <= after {
        index += 1;
    }
    let next = start + chrono::Duration::days(index * step);
    Some(next.format("%Y-%m-%d").to_string())
}

fn row_to_task(r: &Row<'_>) -> rusqlite::Result<Task> {
    Ok(Task {
        id: r.get(0)?,
        project_id: r.get(1)?,
        section_id: r.get(2)?,
        parent_id: r.get(3)?,
        title: r.get(4)?,
        notes: r.get(5)?,
        color: r.get(6)?,
        priority: r.get(7)?,
        start: r.get(8)?,
        end: r.get(9)?,
        recurrence: r.get(10)?,
        repeat_until: r.get(11)?,
        position: r.get(12)?,
        completed: r.get(13)?,
        completions: Vec::new(),
        included_days: Vec::new(),
        excluded_days: Vec::new(),
        label_ids: Vec::new(),
        deleted_at: r.get(16)?,
        created_at: r.get(14)?,
        updated_at: r.get(15)?,
    })
}

const TASK_COLUMNS: &str = "id,project_id,section_id,parent_id,title,notes,color,priority,start_date,end_date,recurrence,repeat_until,position,completed,created_at,updated_at,deleted_at";

fn load_task(conn: &Connection, id: &str) -> Result<Option<Task>> {
    let sql = format!("SELECT {TASK_COLUMNS} FROM tasks WHERE id=?1");
    let Some(mut task) = conn.query_row(&sql, [id], row_to_task).optional()? else {
        return Ok(None);
    };
    let mut statement = conn.prepare("SELECT label_id FROM task_labels WHERE task_id=?1 ORDER BY label_id")?;
    task.label_ids = statement
        .query_map([id], |r| r.get(0))?
        .collect::<std::result::Result<Vec<String>, _>>()?;
    let mut statement = conn.prepare(
        "SELECT completed_at,reopened_at,due_date FROM task_completions WHERE task_id=?1 ORDER BY id",
    )?;
    task.completions = statement
        .query_map([id], |r| {
            Ok(Completion {
                completed_at: r.get(0)?,
                reopened_at: r.get(1)?,
                due_date: r.get(2)?,
            })
        })?
        .collect::<std::result::Result<Vec<Completion>, _>>()?;
    let mut statement =
        conn.prepare("SELECT day,included FROM task_days WHERE task_id=?1 ORDER BY day")?;
    for row in statement.query_map([id], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)))? {
        let (day, included) = row?;
        if included == 1 {
            task.included_days.push(day);
        } else {
            task.excluded_days.push(day);
        }
    }
    Ok(Some(task))
}

fn next_position(conn: &Connection, table: &str) -> Result<i32> {
    let sql = format!("SELECT COALESCE(MAX(position),-1)+1 FROM {table}");
    Ok(conn.query_row(&sql, [], |r| r.get(0))?)
}

fn exists(conn: &Connection, table: &str, id: &str) -> Result<bool> {
    let sql = format!("SELECT 1 FROM {table} WHERE id=?1");
    Ok(conn
        .query_row(&sql, [id], |_| Ok(()))
        .optional()?
        .is_some())
}

fn project_of(conn: &Connection, id: &str) -> Result<Option<String>> {
    Ok(conn
        .query_row("SELECT project_id FROM tasks WHERE id=?1", [id], |r| r.get(0))
        .optional()?
        .flatten())
}

/// 父事项链上溯，用于阻止事项成为自己的祖先。
fn would_cycle(conn: &Connection, id: &str, parent: &str) -> Result<bool> {
    let mut current = Some(parent.to_string());
    let mut guard = 0;
    while let Some(candidate) = current {
        if candidate == id {
            return Ok(true);
        }
        guard += 1;
        if guard > 200 {
            return Ok(true);
        }
        current = conn
            .query_row("SELECT parent_id FROM tasks WHERE id=?1", [&candidate], |r| {
                r.get(0)
            })
            .optional()?
            .flatten();
    }
    Ok(false)
}

fn validate_task(conn: &Connection, id: Option<&str>, draft: &mut TaskDraft) -> Result<()> {
    draft.title = draft.title.trim().into();
    ensure(
        !draft.title.is_empty() && draft.title.chars().count() <= 200,
        "事项名称不能为空，最多 200 字。",
    )?;
    ensure(draft.notes.chars().count() <= 50_000, "备注最多 50000 字。")?;
    color(&draft.color)?;
    ensure((1..=4).contains(&draft.priority), "优先级必须是 1 到 4。")?;
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
    if let (Some(start), Some(end)) = (&draft.start, &draft.end) {
        ensure(end >= start, "结束日期不能早于开始日期。")?;
    }
    match &draft.recurrence {
        Some(rule) => {
            ensure(
                recurrence_step(rule).is_some(),
                "重复规则无效，请选择每天或每隔几天。",
            )?;
            ensure(draft.start.is_some(), "重复事项必须先有开始日期。")?;
            ensure(
                draft.end.is_none(),
                "重复事项不用结束日期，请改用“重复截止”。",
            )?;
            if let Some(until) = &draft.repeat_until {
                date(until)?;
                let start = draft.start.as_deref().unwrap_or_default();
                ensure(until.as_str() >= start, "重复截止不能早于开始日期。")?;
            }
        }
        None => ensure(
            draft.repeat_until.is_none(),
            "只有重复事项才能设置重复截止。",
        )?,
    }
    draft.label_ids.sort();
    draft.label_ids.dedup();
    for label in &draft.label_ids {
        ensure(exists(conn, "labels", label)?, "标签不存在，请刷新后重试。")?;
    }
    if let Some(project) = &draft.project_id {
        ensure(exists(conn, "projects", project)?, "项目不存在，请刷新后重试。")?;
    }
    if let Some(section) = &draft.section_id {
        let owner: Option<String> = conn
            .query_row("SELECT project_id FROM sections WHERE id=?1", [section], |r| r.get(0))
            .optional()?;
        let owner = owner.ok_or_else(|| AppError::new("validation", "分区不存在，请刷新后重试。"))?;
        ensure(
            draft.project_id.as_deref() == Some(owner.as_str()),
            "分区不属于所选项目。",
        )?;
    }
    if let Some(parent) = &draft.parent_id {
        ensure(exists(conn, "tasks", parent)?, "父事项不存在，请刷新后重试。")?;
        ensure(
            id != Some(parent.as_str()),
            "事项不能作为自己的父事项。",
        )?;
        if let Some(self_id) = id {
            ensure(!would_cycle(conn, self_id, parent)?, "父子关系不能形成循环。")?;
        }
        let owner = project_of(conn, parent)?;
        ensure(
            owner == draft.project_id,
            "子事项必须与父事项在同一个项目。",
        )?;
    }
    Ok(())
}

fn save_task(
    conn: &Connection,
    id: Option<String>,
    draft: &mut TaskDraft,
    now: &str,
) -> Result<()> {
    // 子事项没填项目时跟随父事项，避免落在收件箱里跟父事项分家。
    if draft.project_id.is_none() {
        if let Some(parent) = &draft.parent_id {
            draft.project_id = project_of(conn, parent)?;
        }
    }
    let existing = match &id {
        Some(id) => {
            let task = load_task(conn, id)?
                .ok_or_else(|| AppError::new("missing", "事项已被删除，请重新新增。"))?;
            ensure(
                task.deleted_at.is_none(),
                "事项在回收站里，请先恢复再编辑。",
            )?;
            Some(task)
        }
        None => None,
    };
    validate_task(conn, id.as_deref(), draft)?;
    let task_id = id.unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
    let position = match &existing {
        Some(task) => task.position,
        None => next_position(conn, "tasks")?,
    };
    let created_at = match &existing {
        Some(task) => task.created_at.clone(),
        None => now.to_string(),
    };
    // 日期变了就清掉旧的单日排除，和旧版行为一致：改期后重新按新范围显示。
    if let Some(task) = &existing {
        if task.start != draft.start || task.end != draft.end {
            conn.execute(
                "DELETE FROM task_days WHERE task_id=?1 AND included=0",
                [&task_id],
            )?;
        }
    }
    conn.execute(
        "INSERT INTO tasks(id,project_id,section_id,parent_id,title,notes,color,priority,start_date,end_date,recurrence,repeat_until,position,completed,created_at,updated_at)
         VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16)
         ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id,section_id=excluded.section_id,parent_id=excluded.parent_id,title=excluded.title,notes=excluded.notes,color=excluded.color,priority=excluded.priority,start_date=excluded.start_date,end_date=excluded.end_date,recurrence=excluded.recurrence,repeat_until=excluded.repeat_until,updated_at=excluded.updated_at",
        params![
            task_id,
            draft.project_id,
            draft.section_id,
            draft.parent_id,
            draft.title,
            draft.notes,
            draft.color,
            draft.priority,
            draft.start,
            draft.end,
            draft.recurrence,
            draft.repeat_until,
            position,
            existing.as_ref().is_some_and(|task| task.completed),
            created_at,
            now
        ],
    )?;
    conn.execute("DELETE FROM task_labels WHERE task_id=?1", [&task_id])?;
    for label in &draft.label_ids {
        conn.execute(
            "INSERT OR IGNORE INTO task_labels(task_id,label_id) VALUES(?1,?2)",
            params![task_id, label],
        )?;
    }
    Ok(())
}

impl Store {
    pub fn open(path: &Path) -> Result<Self> {
        let mut conn = Connection::open(path)?;
        conn.busy_timeout(std::time::Duration::from_secs(5))?;
        conn.execute_batch("PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;")?;
        let version: i32 = conn.query_row("PRAGMA user_version", [], |r| r.get(0))?;
        ensure(version <= 4, "资料来自更高版本，请更新应用；未修改数据。")?;
        // v1 的升级流程自己会备份，这里只补 2 / 3 两种情况。
        if (2..4).contains(&version) {
            migrate::backup_now(&conn, path)?;
        }
        match version {
            0 => migrate::create(&conn)?,
            1 => {
                migrate::upgrade_from_1(&mut conn, path)?;
                migrate::upgrade_2_to_3(&mut conn)?;
                migrate::upgrade_3_to_4(&mut conn)?;
            }
            2 => {
                migrate::upgrade_2_to_3(&mut conn)?;
                migrate::upgrade_3_to_4(&mut conn)?;
            }
            3 => migrate::upgrade_3_to_4(&mut conn)?,
            _ => {}
        }
        // 每天首次打开留一份自动备份。
        let _ = migrate::daily_backup(&conn, path);
        // 回收站保留 30 天，超期清理。
        let cutoff = (Local::now() - chrono::Duration::days(30)).to_rfc3339();
        conn.execute(
            "DELETE FROM tasks WHERE deleted_at IS NOT NULL AND deleted_at < ?1",
            [&cutoff],
        )?;
        Ok(Self { conn })
    }

    pub fn snapshot(&self) -> Result<Snapshot> {
        let revision = self
            .conn
            .query_row("SELECT revision FROM state WHERE id=1", [], |r| r.get(0))?;

        let mut projects = Vec::new();
        let mut statement = self.conn.prepare(
            "SELECT id,name,color,position,favorite,archived,created_at,updated_at FROM projects ORDER BY position,created_at,id",
        )?;
        for row in statement.query_map([], |r| {
            Ok(Project {
                id: r.get(0)?,
                name: r.get(1)?,
                color: r.get(2)?,
                position: r.get(3)?,
                favorite: r.get(4)?,
                archived: r.get(5)?,
                created_at: r.get(6)?,
                updated_at: r.get(7)?,
            })
        })? {
            projects.push(row?);
        }

        let mut sections = Vec::new();
        let mut statement = self.conn.prepare(
            "SELECT id,project_id,name,position,created_at,updated_at FROM sections ORDER BY position,created_at,id",
        )?;
        for row in statement.query_map([], |r| {
            Ok(Section {
                id: r.get(0)?,
                project_id: r.get(1)?,
                name: r.get(2)?,
                position: r.get(3)?,
                created_at: r.get(4)?,
                updated_at: r.get(5)?,
            })
        })? {
            sections.push(row?);
        }

        let mut labels = Vec::new();
        let mut statement = self.conn.prepare(
            "SELECT id,name,color,position,created_at,updated_at FROM labels ORDER BY position,created_at,id",
        )?;
        for row in statement.query_map([], |r| {
            Ok(Label {
                id: r.get(0)?,
                name: r.get(1)?,
                color: r.get(2)?,
                position: r.get(3)?,
                created_at: r.get(4)?,
                updated_at: r.get(5)?,
            })
        })? {
            labels.push(row?);
        }

        let sql = format!(
            "SELECT {TASK_COLUMNS} FROM tasks WHERE deleted_at IS NULL ORDER BY position,created_at,id"
        );
        let tasks = self.collect_tasks(&sql)?;

        Ok(Snapshot {
            revision,
            projects,
            sections,
            labels,
            tasks,
        })
    }

    /// 回收站：只列已软删除的事项，最近删的在前。
    pub fn trash(&self) -> Result<Vec<Task>> {
        let sql = format!(
            "SELECT {TASK_COLUMNS} FROM tasks WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC,id"
        );
        self.collect_tasks(&sql)
    }

    /// 今天要做的事与已过期的数量，给提醒用。
    pub fn summary(&self, day: &str) -> Result<(usize, usize)> {
        let sql = format!("SELECT {TASK_COLUMNS} FROM tasks WHERE deleted_at IS NULL");
        let tasks = self.collect_tasks(&sql)?;
        let mut due = 0;
        let mut overdue = 0;
        for task in &tasks {
            if shows_on(task, day) && !done_on(task, day) && !task.completed {
                due += 1;
            }
            if let Some(end) = task.end.as_deref().or(task.start.as_deref()) {
                if end < day && !task.completed {
                    overdue += 1;
                }
            }
        }
        Ok((due, overdue))
    }

    /// 同步前留一份快照。
    pub fn backup_to(&self, database: &Path) -> Result<std::path::PathBuf> {
        migrate::backup_now(&self.conn, database)
    }

    /// 同步用：包含回收站里的全部事项。
    pub fn all_tasks(&self) -> Result<Vec<Task>> {
        let sql = format!("SELECT {TASK_COLUMNS} FROM tasks ORDER BY position,created_at,id");
        self.collect_tasks(&sql)
    }

    pub fn all_labels(&self) -> Result<Vec<Label>> {
        let mut statement = self.conn.prepare(
            "SELECT id,name,color,position,created_at,updated_at FROM labels ORDER BY position,created_at,id",
        )?;
        let labels = statement
            .query_map([], |r| {
                Ok(Label {
                    id: r.get(0)?,
                    name: r.get(1)?,
                    color: r.get(2)?,
                    position: r.get(3)?,
                    created_at: r.get(4)?,
                    updated_at: r.get(5)?,
                })
            })?
            .collect::<std::result::Result<Vec<Label>, _>>()?;
        Ok(labels)
    }

    /// 把合并后的结果写回本地：整条覆盖事项并重写子表，最后推进版本号让窗口刷新。
    pub fn apply_sync(&mut self, tasks: &[Task], labels: &[Label]) -> Result<()> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        for label in labels {
            tx.execute(
                "INSERT INTO labels(id,name,color,position,created_at,updated_at) VALUES(?1,?2,?3,?4,?5,?6)
                 ON CONFLICT(id) DO UPDATE SET name=excluded.name,color=excluded.color,position=excluded.position,updated_at=excluded.updated_at",
                params![
                    label.id,
                    label.name,
                    label.color,
                    label.position,
                    label.created_at,
                    label.updated_at
                ],
            )?;
        }
        // 先写事项本体（父事项可能排在后面，先留空），再补父子关系。
        for task in tasks {
            let project = match &task.project_id {
                Some(id) if exists(&tx, "projects", id)? => Some(id.clone()),
                _ => None,
            };
            let section = match (&project, &task.section_id) {
                (Some(_), Some(id)) if exists(&tx, "sections", id)? => Some(id.clone()),
                _ => None,
            };
            tx.execute("DELETE FROM task_labels WHERE task_id=?1", [&task.id])?;
            tx.execute("DELETE FROM task_completions WHERE task_id=?1", [&task.id])?;
            tx.execute("DELETE FROM task_days WHERE task_id=?1", [&task.id])?;
            tx.execute(
                "INSERT INTO tasks(id,project_id,section_id,parent_id,title,notes,color,priority,start_date,end_date,recurrence,repeat_until,position,completed,created_at,updated_at,deleted_at)
                 VALUES(?1,?2,?3,NULL,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16)
                 ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id,section_id=excluded.section_id,title=excluded.title,notes=excluded.notes,color=excluded.color,priority=excluded.priority,start_date=excluded.start_date,end_date=excluded.end_date,recurrence=excluded.recurrence,repeat_until=excluded.repeat_until,position=excluded.position,completed=excluded.completed,updated_at=excluded.updated_at,deleted_at=excluded.deleted_at",
                params![
                    task.id,
                    project,
                    section,
                    task.title,
                    task.notes,
                    task.color,
                    task.priority,
                    task.start,
                    task.end,
                    task.recurrence,
                    task.repeat_until,
                    task.position,
                    task.completed,
                    task.created_at,
                    task.updated_at,
                    task.deleted_at
                ],
            )?;
            for label in &task.label_ids {
                tx.execute(
                    "INSERT OR IGNORE INTO task_labels(task_id,label_id) VALUES(?1,?2)",
                    params![task.id, label],
                )?;
            }
            for completion in &task.completions {
                tx.execute(
                    "INSERT INTO task_completions(task_id,completed_at,reopened_at,due_date) VALUES(?1,?2,?3,?4)",
                    params![
                        task.id,
                        completion.completed_at,
                        completion.reopened_at,
                        completion.due_date
                    ],
                )?;
            }
            for day in &task.included_days {
                tx.execute(
                    "INSERT OR IGNORE INTO task_days(task_id,day,included) VALUES(?1,?2,1)",
                    params![task.id, day],
                )?;
            }
            for day in &task.excluded_days {
                tx.execute(
                    "INSERT OR IGNORE INTO task_days(task_id,day,included) VALUES(?1,?2,0)",
                    params![task.id, day],
                )?;
            }
        }
        for task in tasks {
            if let Some(parent) = &task.parent_id {
                if exists(&tx, "tasks", parent)? {
                    tx.execute(
                        "UPDATE tasks SET parent_id=?2 WHERE id=?1",
                        params![task.id, parent],
                    )?;
                }
            }
        }
        tx.execute("UPDATE state SET revision=revision+1 WHERE id=1", [])?;
        tx.commit()?;
        Ok(())
    }

    fn collect_tasks(&self, sql: &str) -> Result<Vec<Task>> {
        let mut statement = self.conn.prepare(sql)?;
        let mut tasks = statement
            .query_map([], row_to_task)?
            .collect::<std::result::Result<Vec<Task>, _>>()?;
        drop(statement);

        let mut index: HashMap<String, usize> = HashMap::with_capacity(tasks.len());
        for (position, task) in tasks.iter().enumerate() {
            index.insert(task.id.clone(), position);
        }
        let mut statement = self
            .conn
            .prepare("SELECT task_id,label_id FROM task_labels ORDER BY label_id")?;
        for row in statement.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))? {
            let (task, label) = row?;
            if let Some(position) = index.get(&task) {
                tasks[*position].label_ids.push(label);
            }
        }
        let mut statement = self.conn.prepare(
            "SELECT task_id,completed_at,reopened_at,due_date FROM task_completions ORDER BY task_id,id",
        )?;
        for row in statement.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                Completion {
                    completed_at: r.get(1)?,
                    reopened_at: r.get(2)?,
                    due_date: r.get(3)?,
                },
            ))
        })? {
            let (task, completion) = row?;
            if let Some(position) = index.get(&task) {
                tasks[*position].completions.push(completion);
            }
        }
        let mut statement =
            self.conn.prepare("SELECT task_id,day,included FROM task_days ORDER BY day")?;
        for row in statement.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i64>(2)?,
            ))
        })? {
            let (task, day, included) = row?;
            if let Some(position) = index.get(&task) {
                if included == 1 {
                    tasks[*position].included_days.push(day);
                } else {
                    tasks[*position].excluded_days.push(day);
                }
            }
        }

        Ok(tasks)
    }

    pub fn mutate(&mut self, mutation: Mutation, revision: u32) -> Result<Snapshot> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: u32 = tx.query_row("SELECT revision FROM state WHERE id=1", [], |r| r.get(0))?;
        if current != revision {
            return Err(AppError::new(
                "stale",
                "另一个窗口已修改事项，已刷新列表，请重试；编辑内容仍保留。",
            ));
        }
        let now = Local::now().to_rfc3339();
        match mutation {
            Mutation::TaskSave { id, mut draft } => save_task(&tx, id, &mut draft, &now)?,
            Mutation::TaskComplete { id, completed } => complete_task(&tx, &id, completed, &now)?,
            Mutation::TaskDelete { id } => {
                ensure(exists(&tx, "tasks", &id)?, "事项已被删除。")?;
                soft_delete(&tx, &id, &now)?;
            }
            Mutation::TaskRestore { id } => {
                ensure(exists(&tx, "tasks", &id)?, "事项已被彻底删除。")?;
                restore_tree(&tx, &id)?;
            }
            Mutation::TaskPurge { id } => {
                ensure(exists(&tx, "tasks", &id)?, "事项已被彻底删除。")?;
                tx.execute("DELETE FROM tasks WHERE id=?1", [&id])?;
            }
            Mutation::UndoDelete => {
                let latest: Option<String> = tx
                    .query_row(
                        "SELECT deleted_at FROM tasks WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC LIMIT 1",
                        [],
                        |r| r.get(0),
                    )
                    .optional()?;
                if let Some(at) = latest {
                    tx.execute(
                        "UPDATE tasks SET deleted_at=NULL WHERE deleted_at=?1",
                        [&at],
                    )?;
                }
            }
            Mutation::TaskToday {
                id,
                day,
                included,
            } => {
                date(&day)?;
                ensure(exists(&tx, "tasks", &id)?, "事项已被删除。")?;
                tx.execute(
                    "INSERT INTO task_days(task_id,day,included) VALUES(?1,?2,?3)
                     ON CONFLICT(task_id,day) DO UPDATE SET included=excluded.included",
                    params![id, day, i64::from(included)],
                )?;
            }
            Mutation::TaskMove {
                id,
                project_id,
                section_id,
                parent_id,
            } => move_task(&tx, &id, project_id, section_id, parent_id, &now)?,
            Mutation::TaskReorder { ids } => {
                for (position, id) in ids.iter().enumerate() {
                    tx.execute(
                        "UPDATE tasks SET position=?2 WHERE id=?1",
                        params![id, position as i32],
                    )?;
                }
            }
            Mutation::ProjectSave { id, mut draft } => {
                draft.name = draft.name.trim().into();
                ensure(
                    !draft.name.is_empty() && draft.name.chars().count() <= 100,
                    "项目名称不能为空，最多 100 字。",
                )?;
                color(&draft.color)?;
                match id {
                    Some(id) => {
                        ensure(exists(&tx, "projects", &id)?, "项目已被删除。")?;
                        tx.execute(
                            "UPDATE projects SET name=?2,color=?3,favorite=?4,updated_at=?5 WHERE id=?1",
                            params![id, draft.name, draft.color, draft.favorite, now],
                        )?;
                    }
                    None => {
                        let position = next_position(&tx, "projects")?;
                        tx.execute(
                            "INSERT INTO projects(id,name,color,position,favorite,archived,created_at,updated_at) VALUES(?1,?2,?3,?4,?5,0,?6,?6)",
                            params![
                                uuid::Uuid::new_v4().to_string(),
                                draft.name,
                                draft.color,
                                position,
                                draft.favorite,
                                now
                            ],
                        )?;
                    }
                }
            }
            Mutation::ProjectDelete { id } => {
                ensure(exists(&tx, "projects", &id)?, "项目已被删除。")?;
                let tasks: i64 =
                    tx.query_row("SELECT COUNT(*) FROM tasks WHERE project_id=?1", [&id], |r| {
                        r.get(0)
                    })?;
                ensure(
                    tasks == 0,
                    "项目内还有事项，请先把它们移到别的项目或收件箱，再删除项目。",
                )?;
                tx.execute("DELETE FROM projects WHERE id=?1", [&id])?;
            }
            Mutation::SectionSave {
                id,
                project_id,
                name,
            } => {
                let name = name.trim().to_string();
                ensure(
                    !name.is_empty() && name.chars().count() <= 40,
                    "分区名称不能为空，最多 40 字。",
                )?;
                ensure(exists(&tx, "projects", &project_id)?, "项目已被删除。")?;
                match id {
                    Some(id) => {
                        let owner: Option<String> = tx
                            .query_row("SELECT project_id FROM sections WHERE id=?1", [&id], |r| {
                                r.get(0)
                            })
                            .optional()?;
                        ensure(owner.is_some(), "分区已被删除。")?;
                        ensure(
                            owner.as_deref() == Some(project_id.as_str()),
                            "分区不能跨项目移动，请先把它的事项移到目标项目。",
                        )?;
                        tx.execute(
                            "UPDATE sections SET name=?2,updated_at=?3 WHERE id=?1",
                            params![id, name, now],
                        )?;
                    }
                    None => {
                        let position: i32 = tx.query_row(
                            "SELECT COALESCE(MAX(position),-1)+1 FROM sections WHERE project_id=?1",
                            [&project_id],
                            |r| r.get(0),
                        )?;
                        tx.execute(
                            "INSERT INTO sections(id,project_id,name,position,created_at,updated_at) VALUES(?1,?2,?3,?4,?5,?5)",
                            params![uuid::Uuid::new_v4().to_string(), project_id, name, position, now],
                        )?;
                    }
                }
            }
            Mutation::SectionDelete { id } => {
                ensure(exists(&tx, "sections", &id)?, "分区已被删除。")?;
                let tasks: i64 =
                    tx.query_row("SELECT COUNT(*) FROM tasks WHERE section_id=?1", [&id], |r| {
                        r.get(0)
                    })?;
                ensure(
                    tasks == 0,
                    "分区内还有事项，请先把它们移出分区，再删除分区。",
                )?;
                tx.execute("DELETE FROM sections WHERE id=?1", [&id])?;
            }
            Mutation::LabelSave { id, mut draft } => {
                draft.name = draft.name.trim().into();
                ensure(
                    !draft.name.is_empty() && draft.name.chars().count() <= 40,
                    "标签名称不能为空，最多 40 字。",
                )?;
                color(&draft.color)?;
                match id {
                    Some(id) => {
                        ensure(exists(&tx, "labels", &id)?, "标签已被删除。")?;
                        tx.execute(
                            "UPDATE labels SET name=?2,color=?3,updated_at=?4 WHERE id=?1",
                            params![id, draft.name, draft.color, now],
                        )?;
                    }
                    None => {
                        let position = next_position(&tx, "labels")?;
                        tx.execute(
                            "INSERT INTO labels(id,name,color,position,created_at,updated_at) VALUES(?1,?2,?3,?4,?5,?5)",
                            params![
                                uuid::Uuid::new_v4().to_string(),
                                draft.name,
                                draft.color,
                                position,
                                now
                            ],
                        )?;
                    }
                }
            }
            Mutation::LabelDelete { id } => {
                ensure(exists(&tx, "labels", &id)?, "标签已被删除。")?;
                tx.execute("DELETE FROM labels WHERE id=?1", [&id])?;
            }
        }
        tx.execute("UPDATE state SET revision=revision+1 WHERE id=1", [])?;
        tx.commit()?;
        self.snapshot()
    }
}

/// 某一天是否已勾掉：非重复看「完成且落在自己的安排日」，重复看当天完成记录。
pub fn done_on(task: &Task, day: &str) -> bool {
    match &task.recurrence {
        Some(_) => task
            .completions
            .iter()
            .any(|c| c.due_date.as_deref() == Some(day) && c.reopened_at.is_none()),
        None => task.completed && on_day(task, day),
    }
}

/// 视图里要不要出现：当天该做，或当天已经勾掉（重复事项勾完后日期滚走，但当天仍要看得见）。
pub fn shows_on(task: &Task, day: &str) -> bool {
    occurs_on(task, day) || done_on(task, day)
}

/// 删除进回收站：整棵子事项树共用同一个删除时间，恢复时按时间一起捞回来。
fn soft_delete(conn: &Connection, id: &str, now: &str) -> Result<()> {
    conn.execute(
        "WITH RECURSIVE tree(id) AS (
            SELECT id FROM tasks WHERE id=?1
            UNION ALL
            SELECT t.id FROM tasks t JOIN tree ON t.parent_id = tree.id
         )
         UPDATE tasks SET deleted_at=?2 WHERE id IN (SELECT id FROM tree)",
        params![id, now],
    )?;
    Ok(())
}

/// 从回收站恢复整棵树（只恢复同一批删除的那部分）。
fn restore_tree(conn: &Connection, id: &str) -> Result<()> {
    let at: Option<String> = conn
        .query_row("SELECT deleted_at FROM tasks WHERE id=?1", [id], |r| r.get(0))
        .optional()?
        .flatten();
    let Some(at) = at else {
        return Ok(());
    };
    conn.execute(
        "WITH RECURSIVE tree(id) AS (
            SELECT id FROM tasks WHERE id=?1
            UNION ALL
            SELECT t.id FROM tasks t JOIN tree ON t.parent_id = tree.id
         )
         UPDATE tasks SET deleted_at=NULL WHERE id IN (SELECT id FROM tree) AND deleted_at=?2",
        params![id, at],
    )?;
    Ok(())
}

fn complete_task(conn: &Connection, id: &str, completed: bool, now: &str) -> Result<()> {
    let task = load_task(conn, id)?.ok_or_else(|| AppError::new("missing", "事项已被删除。"))?;
    if task.recurrence.is_some() {
        return complete_occurrence(conn, &task, completed, now);
    }
    if completed && !task.completed {
        conn.execute(
            "INSERT INTO task_completions(task_id,completed_at,reopened_at) VALUES(?1,?2,NULL)",
            params![id, now],
        )?;
    }
    if !completed && task.completed {
        conn.execute(
            "UPDATE task_completions SET reopened_at=?2 WHERE id=(SELECT MAX(id) FROM task_completions WHERE task_id=?1 AND reopened_at IS NULL)",
            params![id, now],
        )?;
    }
    conn.execute(
        "UPDATE tasks SET completed=?2,updated_at=?3 WHERE id=?1",
        params![id, completed, now],
    )?;
    Ok(())
}

/// 重复事项的勾选：写一条带 due_date 的完成记录，然后把开始日期滚到下一次。
/// 撤销则把最近一条未撤销的记录标回 reopened，并把日期搬回那一天。
fn complete_occurrence(conn: &Connection, task: &Task, completed: bool, now: &str) -> Result<()> {
    let rule = task.recurrence.as_deref().unwrap_or("daily");
    if completed {
        let due = task
            .start
            .clone()
            .ok_or_else(|| AppError::new("validation", "重复事项缺少开始日期。"))?;
        let already: Option<i64> = conn
            .query_row(
                "SELECT id FROM task_completions WHERE task_id=?1 AND due_date=?2 AND reopened_at IS NULL",
                params![task.id, due],
                |r| r.get(0),
            )
            .optional()?;
        if already.is_none() {
            conn.execute(
                "INSERT INTO task_completions(task_id,completed_at,reopened_at,due_date) VALUES(?1,?2,NULL,?3)",
                params![task.id, now, due],
            )?;
        }
        let today = Local::now().format("%Y-%m-%d").to_string();
        if let Some(next) = next_occurrence(&due, rule, &today) {
            if task
                .repeat_until
                .as_deref()
                .is_some_and(|until| next.as_str() > until)
            {
                // 已经越过重复截止，整条事项收尾。
                conn.execute(
                    "UPDATE tasks SET completed=1,updated_at=?2 WHERE id=?1",
                    params![task.id, now],
                )?;
            } else {
                conn.execute(
                    "UPDATE tasks SET start_date=?2,completed=0,updated_at=?3 WHERE id=?1",
                    params![task.id, next, now],
                )?;
                conn.execute(
                    "DELETE FROM task_days WHERE task_id=?1 AND included=0",
                    [&task.id],
                )?;
            }
        }
        return Ok(());
    }
    let last: Option<(i64, Option<String>)> = conn
        .query_row(
            "SELECT id,due_date FROM task_completions WHERE task_id=?1 AND reopened_at IS NULL AND due_date IS NOT NULL ORDER BY id DESC LIMIT 1",
            [&task.id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    match last {
        Some((completion_id, due)) => {
            conn.execute(
                "UPDATE task_completions SET reopened_at=?2 WHERE id=?1",
                params![completion_id, now],
            )?;
            if let Some(due) = due {
                conn.execute(
                    "UPDATE tasks SET start_date=?2,completed=0,updated_at=?3 WHERE id=?1",
                    params![task.id, due, now],
                )?;
            }
        }
        None => {
            conn.execute(
                "UPDATE tasks SET completed=0,updated_at=?2 WHERE id=?1",
                params![task.id, now],
            )?;
        }
    }
    Ok(())
}

fn move_task(
    conn: &Connection,
    id: &str,
    project_id: Option<String>,
    section_id: Option<String>,
    parent_id: Option<String>,
    now: &str,
) -> Result<()> {
    let task = load_task(conn, id)?.ok_or_else(|| AppError::new("missing", "事项已被删除。"))?;
    if let Some(project) = &project_id {
        ensure(exists(conn, "projects", project)?, "项目不存在，请刷新后重试。")?;
    }
    if let Some(section) = &section_id {
        let owner: Option<String> = conn
            .query_row("SELECT project_id FROM sections WHERE id=?1", [section], |r| r.get(0))
            .optional()?;
        let owner = owner.ok_or_else(|| AppError::new("validation", "分区不存在，请刷新后重试。"))?;
        ensure(
            project_id.as_deref() == Some(owner.as_str()),
            "分区不属于所选项目。",
        )?;
    }
    if let Some(parent) = &parent_id {
        ensure(exists(conn, "tasks", parent)?, "父事项不存在，请刷新后重试。")?;
        ensure(parent != id, "事项不能作为自己的父事项。")?;
        ensure(!would_cycle(conn, id, parent)?, "父子关系不能形成循环。")?;
        ensure(
            project_of(conn, parent)? == project_id,
            "子事项必须与父事项在同一个项目。",
        )?;
    }
    // 换项目时分区由调用方一并给出；这里不做「保留旧分区」的补救，避免把事项留在别的项目的分区里。
    let _ = &task;
    conn.execute(
        "UPDATE tasks SET project_id=?2,section_id=?3,parent_id=?4,updated_at=?5 WHERE id=?1",
        params![id, project_id, section_id, parent_id, now],
    )?;
    Ok(())
}
