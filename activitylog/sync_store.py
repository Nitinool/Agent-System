"""Stable identities, deletion tracking and atomic imports on the UI-owned DB."""

from datetime import datetime
from contextlib import closing
import json
import sqlite3

from .sync import FIELDS, LocalChanged, REPOSITORY, SyncError, encode, validate

TABLES = tuple(FIELDS)


class SyncRepository:
    def __init__(self, store):
        self.store, self.db = store, store.db
        # These auxiliary tables have an independent format and do not rewrite
        # the application's version-5 tables. Triggers track every edit path.
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS sync_entities (
                uid TEXT PRIMARY KEY, kind TEXT NOT NULL, local_id INTEGER,
                UNIQUE(kind, local_id))""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS sync_state (
                repository TEXT PRIMARY KEY, baseline TEXT NOT NULL, synced_at TEXT NOT NULL)""")
            for table in TABLES:
                self.db.execute(f"""INSERT INTO sync_entities(uid, kind, local_id)
                    SELECT lower(hex(randomblob(16))), ?, t.id FROM {table} t
                    WHERE NOT EXISTS (SELECT 1 FROM sync_entities e WHERE e.kind=? AND e.local_id=t.id)""", (table, table))
                self.db.execute(f"""CREATE TRIGGER IF NOT EXISTS sync_insert_{table}
                    AFTER INSERT ON {table} BEGIN
                    INSERT INTO sync_entities(uid, kind, local_id)
                    VALUES (lower(hex(randomblob(16))), '{table}', NEW.id); END""")
                self.db.execute(f"""CREATE TRIGGER IF NOT EXISTS sync_delete_{table}
                    AFTER DELETE ON {table} BEGIN
                    UPDATE sync_entities SET local_id=NULL WHERE kind='{table}' AND local_id=OLD.id; END""")

    def snapshot(self):
        # A read transaction also keeps CLI bootstrap snapshots consistent if an
        # older app window is still writing through another SQLite connection.
        self.db.execute("SAVEPOINT sync_snapshot")
        try:
            return self._read_snapshot()
        finally:
            self.db.execute("RELEASE sync_snapshot")

    def _read_snapshot(self):
        identities = self.db.execute("SELECT * FROM sync_entities").fetchall()
        by_id = {(e["kind"], e["local_id"]): e["uid"] for e in identities if e["local_id"] is not None}

        def reference(kind, identifier):
            return None if identifier is None else by_id[(kind, identifier)]

        result = {}
        for entity in identities:
            uid, table, identifier = entity["uid"], entity["kind"], entity["local_id"]
            if identifier is None:
                result[uid] = {"kind": table, "fields": None}
                continue
            row = self.db.execute(f"SELECT * FROM {table} WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise SyncError("本地同步编号不一致，请关闭软件后重试。")
            fields = {key: row[key] for key in FIELDS[table] if key not in ("days", "completions", "company")}
            for key, kind in (("project_id", "projects"), ("milestone_id", "milestones")):
                if key in fields:
                    fields[key] = reference(kind, fields[key])
            if table == "tasks":
                fields["days"] = [r[0] for r in self.db.execute("SELECT day FROM task_day_entries WHERE task_id=? ORDER BY day", (identifier,))]
                fields["completions"] = []
                for event in self.db.execute("SELECT title, project_id, completed_at, reopened_at FROM task_completions WHERE task_id=? ORDER BY id", (identifier,)):
                    entry = dict(event)
                    entry["project_id"] = reference("projects", entry["project_id"])
                    fields["completions"].append(entry)
            if table == "job_applications":
                fields["company"] = self.db.execute("SELECT name FROM job_companies WHERE id=?", (row["company_id"],)).fetchone()[0]
            result[uid] = {"kind": table, "fields": fields}
        return result

    def baseline(self):
        row = self.db.execute("SELECT baseline FROM sync_state WHERE repository=?", (REPOSITORY,)).fetchone()
        return json.loads(row[0]) if row else {}

    def status(self):
        base, local = self.baseline(), self.snapshot()
        pending = sum(base.get(uid) != local.get(uid) for uid in set(base) | set(local))
        row = self.db.execute("SELECT synced_at FROM sync_state WHERE repository=?", (REPOSITORY,)).fetchone()
        return pending, row[0] if row else None

    def apply(self, expected, merged):
        """Called only after the remote CAS succeeds; failed imports retain old base."""
        validate(merged)
        encode(merged)
        if self.snapshot() != expected:
            raise LocalChanged("同步期间本地有修改。远端已保存本次版本，本地未覆盖，请再次同步。")
        if merged != expected and self.store.path:
            backups = self.store.path.parent / "backups"
            backups.mkdir(exist_ok=True)
            path = backups / f"before-sync-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3"
            # SQLite's context manager ends transactions but leaves files open.
            with closing(sqlite3.connect(path)) as target:
                self.db.backup(target)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.snapshot() != expected:
                raise LocalChanged("同步期间本地有修改，请再次同步。")
            self._import(expected, merged)
            if self.snapshot() != merged:
                raise SyncError("同步导入校验未通过，本地修改已回滚，请再次同步。")
            at = datetime.now().astimezone().isoformat(timespec="seconds")
            self.db.execute("""INSERT INTO sync_state(repository, baseline, synced_at) VALUES (?, ?, ?)
                ON CONFLICT(repository) DO UPDATE SET baseline=excluded.baseline, synced_at=excluded.synced_at""",
                (REPOSITORY, json.dumps(merged, ensure_ascii=False, sort_keys=True), at))

    def _import(self, expected, merged):
        changed = {uid for uid, value in merged.items() if expected.get(uid) != value}
        # Drop children before parents. Unchanged surviving children are restored
        # below if FK effects touched them; unrelated row IDs stay stable.
        for table in reversed(TABLES):
            for uid in changed:
                record = merged[uid]
                if record["kind"] == table and record["fields"] is None:
                    row = self.db.execute("SELECT local_id FROM sync_entities WHERE uid=?", (uid,)).fetchone()
                    if row and row[0] is not None:
                        self.db.execute(f"DELETE FROM {table} WHERE id=?", (row[0],))
                    self.db.execute("INSERT OR IGNORE INTO sync_entities(uid, kind, local_id) VALUES (?, ?, NULL)", (uid, table))
        ids = {r["uid"]: r["local_id"] for r in self.db.execute("SELECT * FROM sync_entities") if r["local_id"] is not None}
        # Release unique names first so two devices can exchange project names.
        for uid in changed:
            if merged[uid]["kind"] == "projects" and merged[uid]["fields"] is not None and uid in ids:
                self.db.execute("UPDATE projects SET name_key=? WHERE id=?", ("__sync__" + uid, ids[uid]))
        for table in TABLES:
            for uid, record in merged.items():
                fields = record["fields"]
                if record["kind"] != table or fields is None or uid not in changed:
                    continue
                # Parents already exist at this point; global IDs never enter
                # business tables, preserving their existing repository APIs.
                values = {key: value for key, value in fields.items() if key not in ("days", "completions", "company")}
                for key in ("project_id", "milestone_id"):
                    if key in values:
                        values[key] = ids[values[key]] if values[key] else None
                if table == "projects":
                    values["name_key"] = fields["name"].casefold()
                if table == "job_applications":
                    key = fields["company"].casefold()
                    company = self.db.execute("SELECT id FROM job_companies WHERE name_key=?", (key,)).fetchone()
                    if company:
                        values["company_id"] = company[0]
                        self.db.execute("UPDATE job_companies SET name=? WHERE id=?", (fields["company"], company[0]))
                    else:
                        values["company_id"] = self.db.execute("INSERT INTO job_companies(name, name_key) VALUES (?, ?)", (fields["company"], key)).lastrowid
                if uid not in ids:
                    columns = ", ".join(values)
                    placeholders = ", ".join("?" for _ in values)
                    identifier = self.db.execute(f"INSERT INTO {table}({columns}) VALUES ({placeholders})", tuple(values.values())).lastrowid
                    self.db.execute("DELETE FROM sync_entities WHERE uid=? AND local_id IS NULL", (uid,))
                    self.db.execute("UPDATE sync_entities SET uid=? WHERE kind=? AND local_id=?", (uid, table, identifier))
                    ids[uid] = identifier
                else:
                    identifier = ids[uid]
                    assignments = ", ".join(f"{key}=?" for key in values)
                    self.db.execute(f"UPDATE {table} SET {assignments} WHERE id=?", (*values.values(), identifier))
                if table == "tasks" and uid in changed:
                    self.db.execute("DELETE FROM task_day_entries WHERE task_id=?", (identifier,))
                    self.db.executemany("INSERT INTO task_day_entries(task_id, day) VALUES (?, ?)", ((identifier, day) for day in fields["days"]))
                    self.db.execute("DELETE FROM task_completions WHERE task_id=?", (identifier,))
                    for event in fields["completions"]:
                        self.db.execute("INSERT INTO task_completions(task_id, project_id, title, completed_at, reopened_at) VALUES (?, ?, ?, ?, ?)",
                                        (identifier, ids[event["project_id"]] if event["project_id"] else None, event["title"], event["completed_at"], event["reopened_at"]))
