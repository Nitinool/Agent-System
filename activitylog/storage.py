"""SQLite persistence and additive feature tables; no legacy point-data migration."""

from datetime import date, datetime
from pathlib import Path
import sqlite3
from collections.abc import Iterable

from .analysis import merge_for_display
from .export import export_csv
from .models import Activity, CATEGORIES, Segment, stamp
from .job_store import JOB_SCHEMA
from .task_store import TASK_SCHEMA, TASK_V4_MIGRATION, TASK_V5_SCHEMA, TASK_V7_SCHEMA
from .project_store import PROJECT_SCHEMA, PROJECT_V5_SCHEMA, PROJECT_V7_SCHEMA
from .finance_store import FINANCE_SCHEMA
from .note_store import NOTE_SCHEMA

SCHEMA_VERSION = 8
RECORDING_SCHEMA = (
    """CREATE TABLE segments (
        id INTEGER PRIMARY KEY, start_time TEXT NOT NULL, last_seen TEXT NOT NULL,
        end_time TEXT, seconds REAL NOT NULL DEFAULT 0 CHECK(seconds >= 0),
        app TEXT NOT NULL, process TEXT NOT NULL, title TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('activity', 'locked', 'gap')),
        status TEXT NOT NULL CHECK(status IN ('running', 'closed', 'interrupted')),
        reason TEXT NOT NULL DEFAULT '', resume_reason TEXT NOT NULL DEFAULT '')""",
    "CREATE INDEX segment_dates ON segments(start_time, last_seen)",
    """CREATE TABLE classifications (
        segment_id INTEGER PRIMARY KEY REFERENCES segments(id) ON DELETE CASCADE,
        category TEXT NOT NULL)""",
)
SCHEMA = RECORDING_SCHEMA + JOB_SCHEMA + PROJECT_SCHEMA + TASK_SCHEMA + PROJECT_V5_SCHEMA + TASK_V5_SCHEMA + FINANCE_SCHEMA + PROJECT_V7_SCHEMA + TASK_V7_SCHEMA + NOTE_SCHEMA


class UnsupportedSchemaError(sqlite3.DatabaseError):
    """Opening an incompatible database must not alter it."""


class Store:
    def __init__(self, path: str | Path, recover: bool = False):
        self.path = None if str(path) == ":memory:" else Path(path).resolve()
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA busy_timeout=3000")
            self.db.execute("PRAGMA foreign_keys=ON")
            self._initialize_schema()
            if recover:
                with self.db:
                    self.db.execute("""UPDATE segments SET end_time=last_seen, status='interrupted',
                        reason='上次程序异常退出，仅保留最后一次保存的时长' WHERE status='running'""")
        except BaseException:
            self.db.close()
            raise

    def _initialize_schema(self) -> None:
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if version == SCHEMA_VERSION:
            return
        if version in (1, 2, 3, 4, 5, 6, 7):
            # Add the new feature tables without rewriting recorded activities.
            with self.db:
                self.db.execute("BEGIN")
                statements = (() if version in (4, 5, 6, 7) else
                              (JOB_SCHEMA if version == 1 else ()) + PROJECT_SCHEMA
                              + (TASK_V4_MIGRATION if version == 3 else TASK_SCHEMA))
                if version < 5:
                    statements += PROJECT_V5_SCHEMA + TASK_V5_SCHEMA
                if version < 6:
                    statements += FINANCE_SCHEMA
                if version < 7:
                    statements += PROJECT_V7_SCHEMA + TASK_V7_SCHEMA
                statements += NOTE_SCHEMA
                for statement in statements:
                    self.db.execute(statement)
                if version < 7 and any(row[0] == 'sync_entities' for row in tables):
                    self.db.execute("""UPDATE projects SET project_key=(SELECT uid FROM sync_entities
                        WHERE kind='projects' AND local_id=projects.id)""")
                if version < 7:
                    self.db.execute("UPDATE projects SET project_key=lower(hex(randomblob(16))) WHERE project_key IS NULL")
                self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            return
        if version != 0 or tables:
            raise UnsupportedSchemaError("数据库结构不受支持。请使用当前版本的数据文件。")
        # Explicit BEGIN makes table creation and the version marker atomic.
        with self.db:
            self.db.execute("BEGIN")
            for statement in SCHEMA:
                self.db.execute(statement)
            self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def set_category(self, references: Iterable[int], category: str) -> None:
        if category not in CATEGORIES:
            raise ValueError("请选择列表中的分类。")
        identifiers = set(references)
        if any(not isinstance(identifier, int) for identifier in identifiers):
            raise ValueError("无效的记录编号。")
        with self.db:
            for identifier in identifiers:
                self.db.execute("""INSERT INTO classifications(segment_id, category)
                    SELECT id, ? FROM segments WHERE id=? AND kind='activity'
                    ON CONFLICT(segment_id) DO UPDATE SET category=excluded.category""",
                    (category, identifier))

    def begin(self, activity: Activity, at: datetime, kind: str = "activity",
              resume_reason: str = "") -> int:
        with self.db:
            cursor = self.db.execute("""INSERT INTO segments
                (start_time, last_seen, app, process, title, kind, status, resume_reason)
                VALUES (?, ?, ?, ?, ?, ?, 'running', ?)""",
                (stamp(at), stamp(at), activity.app, activity.process, activity.title, kind, resume_reason))
        return cursor.lastrowid

    def checkpoint(self, identifier: int, at: datetime, seconds: float) -> None:
        with self.db:
            self.db.execute("UPDATE segments SET last_seen=?, seconds=? WHERE id=?",
                            (stamp(at), max(0, seconds), identifier))

    def finish(self, identifier: int, at: datetime, seconds: float, reason: str = "",
               interrupted: bool = False) -> None:
        with self.db:
            self.db.execute("""UPDATE segments SET last_seen=?, end_time=?, seconds=?,
                status=?, reason=? WHERE id=?""",
                (stamp(at), stamp(at), max(0, seconds),
                 "interrupted" if interrupted else "closed", reason, identifier))

    def gap(self, start: datetime, end: datetime) -> None:
        with self.db:
            self.db.execute("""INSERT INTO segments
                (start_time, last_seen, end_time, seconds, app, process, title, kind, status, reason)
                VALUES (?, ?, ?, 0, '采集间隔', '', '', 'gap', 'closed', ?)""",
                (stamp(start), stamp(end), stamp(end), "睡眠或程序未能按时采样，未计入应用停留时长"))

    def rows(self, selected: date | None = None) -> list[Segment]:
        where, args = "", ()
        if selected is not None:
            where = "WHERE substr(start_time,1,10)<=? AND substr(last_seen,1,10)>=?"
            args = (selected.isoformat(), selected.isoformat())
        records = []
        query = f"""SELECT s.*, COALESCE(c.category, '未分类') AS category FROM segments s
            LEFT JOIN classifications c ON c.segment_id=s.id {where} ORDER BY s.id DESC"""
        for record in self.db.execute(query, args):
            row = self._segment(record)
            row = row.on_day(selected) if selected is not None else row
            if row is not None:
                records.append(row)
        return sorted(records, key=lambda row: row.start, reverse=True)

    @staticmethod
    def _segment(record: sqlite3.Row) -> Segment:
        return Segment(
            start=datetime.fromisoformat(record["start_time"]),
            end=datetime.fromisoformat(record["last_seen"]),
            app=record["app"], process=record["process"], title=record["title"],
            seconds=None if record["kind"] == "gap" else record["seconds"],
            kind=record["kind"], status=record["status"], reason=record["reason"],
            resume_reason=record["resume_reason"], category=record["category"],
            references=(record["id"],),
        )

    def export(self, path: str | Path, selected: date | None = None, merged: bool = False) -> int:
        rows = self.rows(selected)
        return export_csv(path, merge_for_display(rows) if merged else rows, database_path=self.path)

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
