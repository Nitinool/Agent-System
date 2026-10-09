"""Manual note storage; table creation belongs to the schema migration."""

from datetime import datetime

from .models import stamp
from .notes import Note

NOTE_SCHEMA = (
    """CREATE TABLE notes (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 500),
        created_at TEXT NOT NULL)""",
    'CREATE INDEX note_times ON notes(julianday(created_at) DESC, id DESC)',
)


class NoteRepository:
    def __init__(self, db):
        self.db = db

    def add(self, title, at):
        with self.db:
            return self.db.execute('INSERT INTO notes(title, created_at) VALUES (?, ?)',
                                   (title, stamp(at))).lastrowid

    def latest(self):
        # Same-time entries remain deterministic; timezone offsets sort by instant.
        rows = self.db.execute('SELECT * FROM notes ORDER BY julianday(created_at) DESC, id DESC LIMIT 200')
        return tuple(Note(row['id'], row['title'], datetime.fromisoformat(row['created_at'])) for row in rows)
