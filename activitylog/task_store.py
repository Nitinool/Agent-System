"""Tasks and dated today-list membership on the Store's shared connection."""

from datetime import date, datetime
import sqlite3

from .tasks import Task, TaskDraft
from .projects import project_code

TASK_SCHEMA_V3 = (
    """CREATE TABLE tasks (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, planned_on TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT '其他', notes TEXT NOT NULL DEFAULT '',
        completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0, 1)))""",
    "CREATE INDEX task_dates ON tasks(planned_on)",
    """CREATE TABLE task_day_entries (
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        day TEXT NOT NULL, PRIMARY KEY (task_id, day))""",
    "CREATE INDEX task_entry_dates ON task_day_entries(day)",
)

TASK_SCHEMA = (
    """CREATE TABLE tasks (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, planned_on TEXT,
        category TEXT NOT NULL DEFAULT '其他', notes TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT '待开始' CHECK(status IN ('待开始', '进行中', '受阻', '已完成')),
        priority TEXT NOT NULL DEFAULT '普通' CHECK(priority IN ('紧急', '高', '普通', '低')),
        kind TEXT NOT NULL DEFAULT '任务' CHECK(kind IN ('任务', '功能', '问题')),
        project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
        resume_status TEXT NOT NULL DEFAULT '待开始' CHECK(resume_status IN ('待开始', '进行中', '受阻')))""",
    "CREATE INDEX task_dates ON tasks(planned_on)",
    TASK_SCHEMA_V3[2],
    TASK_SCHEMA_V3[3],
    "CREATE INDEX task_projects ON tasks(project_id)",
)

# Rebuild the two related tables within Store's transaction. Copy memberships
# before dropping their old parent; SQLite updates the new FK on table rename.
TASK_V4_MIGRATION = (
    TASK_SCHEMA[0].replace("CREATE TABLE tasks", "CREATE TABLE tasks_next"),
    """INSERT INTO tasks_next(id, title, planned_on, category, notes, status)
        SELECT id, title, planned_on, category, notes,
        CASE WHEN completed=1 THEN '已完成' ELSE '待开始' END FROM tasks""",
    TASK_SCHEMA[2].replace("task_day_entries", "task_entries_next").replace("REFERENCES tasks(", "REFERENCES tasks_next("),
    "INSERT INTO task_entries_next SELECT task_id, day FROM task_day_entries",
    "DROP TABLE task_day_entries",
    "DROP TABLE tasks",
    "ALTER TABLE tasks_next RENAME TO tasks",
    "ALTER TABLE task_entries_next RENAME TO task_day_entries",
    TASK_SCHEMA[1], TASK_SCHEMA[3], TASK_SCHEMA[4],
)

# Existing completed tasks retain unknown completion time; never invent history.
TASK_V5_SCHEMA = (
    "ALTER TABLE tasks ADD COLUMN milestone_id INTEGER REFERENCES milestones(id) ON DELETE SET NULL",
    "ALTER TABLE tasks ADD COLUMN acceptance TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE tasks ADD COLUMN outcome TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE tasks ADD COLUMN completed_at TEXT",
    "CREATE INDEX task_milestones ON tasks(milestone_id)",
    """CREATE TABLE task_completions (
        id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
        title TEXT NOT NULL, completed_at TEXT NOT NULL, reopened_at TEXT)""",
    "CREATE INDEX completion_projects ON task_completions(project_id, id)",
)

TASK_ORDER = """status='已完成', CASE priority WHEN '紧急' THEN 0 WHEN '高' THEN 1
    WHEN '普通' THEN 2 ELSE 3 END, id"""

TASK_V7_SCHEMA = (
    "ALTER TABLE tasks ADD COLUMN range_start TEXT",
    "ALTER TABLE tasks ADD COLUMN range_end TEXT",
    """CREATE TABLE task_day_exclusions(task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        day TEXT NOT NULL, PRIMARY KEY(task_id,day))""",
)


class TaskRepository:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def _task(self, row: sqlite3.Row) -> Task:
        project = self.db.execute("SELECT project_key FROM projects WHERE id=?", (row['project_id'],)).fetchone()
        return Task(row["id"], row["title"], date.fromisoformat(row["planned_on"]) if row["planned_on"] else None,
                    row["category"], row["notes"], row["status"], row["priority"], row["kind"],
                    row["project_id"], row["resume_status"], row["milestone_id"], row["acceptance"],
                    row["outcome"], row["completed_at"],
                    date.fromisoformat(row['range_start']) if row['range_start'] else None,
                    date.fromisoformat(row['range_end']) if row['range_end'] else None,
                    project_code(project[0]) if project else "")

    def get(self, identifier: int) -> Task:
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("事项已不存在，请刷新后重试。")
        return self._task(row)

    def between(self, first: date, last: date) -> tuple[Task, ...]:
        rows = self.db.execute(f"""SELECT * FROM tasks WHERE planned_on BETWEEN ? AND ?
            OR (range_start<=? AND range_end>=?) ORDER BY planned_on, {TASK_ORDER}""",
            (first.isoformat(), last.isoformat(), last.isoformat(), first.isoformat()))
        return tuple(self._task(row) for row in rows)

    def day_tasks(self, day: date) -> tuple[Task, ...]:
        rows = self.db.execute(f"""SELECT t.* FROM tasks t WHERE t.id IN
            (SELECT task_id FROM task_day_entries WHERE day=?) OR
            (t.range_start<=? AND t.range_end>=? AND t.status!='已完成' AND NOT EXISTS
             (SELECT 1 FROM task_day_exclusions e WHERE e.task_id=t.id AND e.day=?))
            ORDER BY {TASK_ORDER}""", (day.isoformat(),) * 4)
        return tuple(self._task(row) for row in rows)

    def unscheduled(self) -> tuple[Task, ...]:
        rows = self.db.execute(f"SELECT * FROM tasks WHERE planned_on IS NULL AND range_start IS NULL ORDER BY {TASK_ORDER}")
        return tuple(self._task(row) for row in rows)

    def project_tasks(self, identifier: int, keyword: str, status: str) -> tuple[Task, ...]:
        where = "project_id=? AND (instr(lower(title),lower(?))>0 OR instr(lower(notes),lower(?))>0)"
        args = [identifier, keyword, keyword]
        if status != "全部状态":
            where += " AND status=?"
            args.append(status)
        rows = self.db.execute(f"SELECT * FROM tasks WHERE {where} ORDER BY {TASK_ORDER}", args)
        return tuple(self._task(row) for row in rows)

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    def is_on_day(self, identifier: int, day: date) -> bool:
        return any(task.id == identifier for task in self.day_tasks(day))

    def save(self, draft: TaskDraft, identifier: int | None, today: date,
             in_today: bool) -> int:
        # Editing fields and today's membership succeed or roll back together.
        with self.db:
            if draft.project_id is not None and self.db.execute(
                    "SELECT 1 FROM projects WHERE id=?", (draft.project_id,)).fetchone() is None:
                raise ValueError("项目已不存在，请重新选择所属项目。")
            previous = self.get(identifier) if identifier is not None else None
            if draft.milestone_id is not None:
                milestone = self.db.execute("SELECT project_id FROM milestones WHERE id=?", (draft.milestone_id,)).fetchone()
                if milestone is None or milestone['project_id'] != draft.project_id:
                    raise ValueError("里程碑不属于所选项目，请重新选择。")
            status = draft.status or (previous.status if previous else "待开始")
            resume = previous.resume_status if previous and previous.completed else (
                previous.status if previous else "待开始")
            if status != "已完成":
                resume = status
            values = (draft.title, draft.planned_on or None, draft.category, draft.notes,
                      status, draft.priority, draft.kind, draft.project_id, resume,
                      draft.milestone_id, draft.acceptance, draft.outcome, draft.range_start or None, draft.range_end or None)
            if identifier is None:
                cursor = self.db.execute("""INSERT INTO tasks
                    (title, planned_on, category, notes, status, priority, kind, project_id, resume_status,
                    milestone_id, acceptance, outcome, range_start, range_end) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", values)
                identifier = cursor.lastrowid
            else:
                cursor = self.db.execute("""UPDATE tasks SET title=?, planned_on=?, category=?, notes=?,
                    status=?, priority=?, kind=?, project_id=?, resume_status=?,
                    milestone_id=?, acceptance=?, outcome=?, range_start=?, range_end=? WHERE id=?""", values + (identifier,))
                if not cursor.rowcount:
                    raise ValueError("事项已不存在，请刷新后重试。")
            if previous and (draft.range_start, draft.range_end) != (
                    previous.range_start.isoformat() if previous.range_start else '',
                    previous.range_end.isoformat() if previous.range_end else ''):
                self.db.execute('DELETE FROM task_day_exclusions WHERE task_id=?', (identifier,))
            self._set_membership(identifier, today, in_today)
            self._record_transition(self.get(identifier), previous.status if previous else None)
            self._invalidate_milestone(draft.milestone_id)
            if previous:
                self._invalidate_milestone(previous.milestone_id)
        return identifier

    def _set_membership(self, identifier: int, day: date, included: bool) -> None:
        task = self.get(identifier)
        if task.range_start and task.range_start <= day <= task.range_end:
            self.db.execute("DELETE FROM task_day_entries WHERE task_id=? AND day=?", (identifier, day.isoformat()))
            if task.completed:
                return
            if included:
                self.db.execute("DELETE FROM task_day_exclusions WHERE task_id=? AND day=?", (identifier, day.isoformat()))
            else:
                self.db.execute("INSERT OR IGNORE INTO task_day_exclusions(task_id,day) VALUES(?,?)", (identifier, day.isoformat()))
            return
        if included:
            self.db.execute("INSERT OR IGNORE INTO task_day_entries(task_id, day) VALUES (?, ?)",
                            (identifier, day.isoformat()))
        else:
            self.db.execute("DELETE FROM task_day_entries WHERE task_id=? AND day=?",
                            (identifier, day.isoformat()))

    def set_membership(self, identifier: int, day: date, included: bool) -> None:
        with self.db:
            task = self.get(identifier)
            if included and task.planned_on is None:
                self.db.execute("UPDATE tasks SET planned_on=? WHERE id=?", (day.isoformat(), identifier))
            self._set_membership(identifier, day, included)

    def schedule(self, identifier, start, end):
        with self.db:
            self.get(identifier)
            self.db.execute("UPDATE tasks SET planned_on=?, range_start=?, range_end=? WHERE id=?",
                            (start, start, end, identifier))
            self.db.execute("DELETE FROM task_day_exclusions WHERE task_id=?", (identifier,))
            self.db.execute("DELETE FROM task_day_entries WHERE task_id=? AND day BETWEEN ? AND ?", (identifier, start, end))

    def complete(self, identifier: int, completed: bool) -> None:
        with self.db:
            task = self.get(identifier)
            self._set_status(task, "已完成" if completed else task.resume_status)

    def _set_status(self, task: Task, status: str) -> None:
        resume = (task.resume_status if task.completed else task.status) if status == "已完成" else status
        self.db.execute("UPDATE tasks SET status=?, resume_status=? WHERE id=?", (status, resume, task.id))
        self._record_transition(self.get(task.id), task.status)
        self._invalidate_milestone(task.milestone_id)

    def _record_transition(self, task: Task, previous_status: str | None) -> None:
        if task.status == previous_status:
            return
        at = datetime.now().astimezone().isoformat(timespec='seconds')
        if task.completed:
            self.db.execute("UPDATE tasks SET completed_at=? WHERE id=?", (at, task.id))
            self.db.execute("INSERT INTO task_completions(task_id,project_id,title,completed_at) VALUES (?,?,?,?)",
                            (task.id, task.project_id, task.title, at))
        elif previous_status == '已完成':
            self.db.execute("UPDATE tasks SET completed_at=NULL WHERE id=?", (task.id,))
            self.db.execute("UPDATE task_completions SET reopened_at=? WHERE task_id=? AND reopened_at IS NULL",
                            (at, task.id))

    def _invalidate_milestone(self, identifier: int | None) -> None:
        if identifier is not None:
            self.db.execute("""UPDATE milestones SET completed_at=NULL WHERE id=? AND
                (NOT EXISTS (SELECT 1 FROM tasks WHERE milestone_id=?) OR
                 EXISTS (SELECT 1 FROM tasks WHERE milestone_id=? AND status!='已完成'))""",
                (identifier, identifier, identifier))

    def set_status(self, identifier: int, status: str) -> None:
        with self.db:
            self._set_status(self.get(identifier), status)

    def delete(self, identifier: int) -> None:
        with self.db:
            task = self.get(identifier)
            self.db.execute("DELETE FROM tasks WHERE id=?", (identifier,))
            self._invalidate_milestone(task.milestone_id)
