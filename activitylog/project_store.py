"""Projects and progress computed from shared tasks."""

import sqlite3

from .projects import CompletionRecord, Milestone, MilestoneDraft, Project, ProjectDraft, ProjectSummary

PROJECT_SCHEMA = (
    """CREATE TABLE projects (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
        goal TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '进行中'
        CHECK(status IN ('进行中', '暂停', '已完成')))""",
)

PROJECT_V5_SCHEMA = (
    """CREATE TABLE milestones (
        id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        name TEXT NOT NULL, acceptance TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL,
        completed_at TEXT)""",
    "CREATE INDEX milestone_projects ON milestones(project_id, position)",
)

PROJECT_V7_SCHEMA = (
    "ALTER TABLE projects ADD COLUMN priority TEXT NOT NULL DEFAULT '普通'",
    "ALTER TABLE projects ADD COLUMN mode TEXT NOT NULL DEFAULT '目标型'",
    "ALTER TABLE projects ADD COLUMN project_key TEXT",
    "CREATE UNIQUE INDEX project_keys ON projects(project_key)",
    """CREATE TRIGGER project_identity AFTER INSERT ON projects WHEN NEW.project_key IS NULL
        BEGIN UPDATE projects SET project_key=COALESCE(project_key, lower(hex(randomblob(16)))) WHERE id=NEW.id; END""",
)


class ProjectRepository:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    @staticmethod
    def _project(row) -> Project:
        return Project(row["id"], row["name"], row["goal"], row["status"], row["priority"], row["mode"], row["project_key"] or "")

    def summaries(self) -> tuple[ProjectSummary, ...]:
        rows = self.db.execute("""SELECT p.*, COUNT(t.id) AS total,
            COALESCE(SUM(t.status='已完成'), 0) AS completed
            FROM projects p LEFT JOIN tasks t ON t.project_id=p.id
            GROUP BY p.id ORDER BY p.id DESC""")
        return tuple(ProjectSummary(self._project(row), row["total"], row["completed"]) for row in rows)

    def get(self, identifier: int) -> Project:
        row = self.db.execute("SELECT * FROM projects WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("项目已不存在，请刷新后重试。")
        return self._project(row)

    def all_projects(self) -> tuple[Project, ...]:
        return tuple(self._project(row) for row in self.db.execute("SELECT * FROM projects ORDER BY id DESC"))

    def save(self, draft: ProjectDraft, identifier: int | None = None) -> int:
        with self.db:
            if identifier is None:
                cursor = self.db.execute("INSERT INTO projects(name, name_key, goal, status, priority, mode) VALUES (?, ?, ?, ?, ?, ?)",
                                         (draft.name, draft.name.casefold(), draft.goal, draft.status, draft.priority, draft.mode))
                return cursor.lastrowid
            cursor = self.db.execute("UPDATE projects SET name=?, name_key=?, goal=?, status=?, priority=?, mode=? WHERE id=?",
                                     (draft.name, draft.name.casefold(), draft.goal, draft.status, draft.priority, draft.mode, identifier))
            if not cursor.rowcount:
                raise ValueError("项目已不存在，请刷新后重试。")
        return identifier

    def delete(self, identifier: int) -> None:
        # ON DELETE SET NULL retains tasks and their calendar/today membership.
        with self.db:
            self.db.execute("DELETE FROM projects WHERE id=?", (identifier,))

    def milestones(self, project_id: int) -> tuple[Milestone, ...]:
        rows = self.db.execute("""SELECT m.*, COUNT(t.id) AS total,
            COALESCE(SUM(t.status='已完成'), 0) AS completed FROM milestones m
            LEFT JOIN tasks t ON t.milestone_id=m.id WHERE m.project_id=?
            GROUP BY m.id ORDER BY m.position, m.id""", (project_id,))
        return tuple(Milestone(row['id'], row['project_id'], row['name'], row['acceptance'],
                               row['position'], row['completed_at'], row['total'], row['completed']) for row in rows)

    def milestone(self, identifier: int) -> Milestone:
        row = self.db.execute("SELECT project_id FROM milestones WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("里程碑已不存在，请刷新后重试。")
        return next(item for item in self.milestones(row['project_id']) if item.id == identifier)

    def save_milestone(self, project_id: int, draft: MilestoneDraft, identifier: int | None = None) -> int:
        with self.db:
            self.get(project_id)
            if identifier is None:
                position = self.db.execute("SELECT COALESCE(MAX(position), 0)+1 FROM milestones WHERE project_id=?",
                                           (project_id,)).fetchone()[0]
                return self.db.execute("INSERT INTO milestones(project_id,name,acceptance,position) VALUES (?,?,?,?)",
                                       (project_id, draft.name, draft.acceptance, position)).lastrowid
            if self.milestone(identifier).project_id != project_id:
                raise ValueError("里程碑不属于当前项目。")
            self.db.execute("UPDATE milestones SET name=?, acceptance=?, completed_at=NULL WHERE id=?",
                            (draft.name, draft.acceptance, identifier))
        return identifier

    def finish_milestone(self, identifier: int, at: str) -> None:
        with self.db:
            item = self.milestone(identifier)
            if not item.total or item.completed != item.total:
                raise ValueError("请先完成这个阶段的所有事项，再确认验收。")
            self.db.execute("UPDATE milestones SET completed_at=COALESCE(completed_at, ?) WHERE id=?", (at, identifier))

    def delete_milestone(self, identifier: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM milestones WHERE id=?", (identifier,))

    def completion_records(self, project_id: int) -> tuple[CompletionRecord, ...]:
        rows = self.db.execute("""SELECT e.*, t.outcome FROM task_completions e JOIN tasks t ON t.id=e.task_id
            WHERE e.project_id=? ORDER BY e.id DESC""", (project_id,))
        return tuple(CompletionRecord(row['id'], row['task_id'], row['title'], row['completed_at'],
                                      row['reopened_at'], row['outcome']) for row in rows)
