"""Notes survive restarts, merge across devices and preserve old business data."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from activitylog.models import Activity
from activitylog.note_store import NOTE_SCHEMA
from activitylog.service import ActivityService
from activitylog.storage import Store, SCHEMA_VERSION
from activitylog.sync import decode, encode, merge, SyncError
from activitylog.tasks import TaskDraft
from tests.ui_smoke import FixtureReader


class NoteTests(unittest.TestCase):
    def device(self, path=':memory:'):
        service = ActivityService(Store(path), FixtureReader())
        self.addCleanup(service.close)
        service.notes.clock = lambda: datetime(2026, 10, 9, 11, 30, 45, tzinfo=timezone(timedelta(hours=8)))
        return service

    def test_validation_and_write_failure_leave_no_phantom_note(self):
        app = self.device()
        for title in ('', ' \t ', 'a' * 501):
            with self.assertRaises(ValueError):
                app.notes.add(title)
        with patch.object(app.notes.repository, 'add', side_effect=sqlite3.OperationalError('失败')):
            with self.assertRaises(sqlite3.Error):
                app.notes.add('失败的记录')
        self.assertEqual(app.notes.latest(), ())
        identifier = app.notes.add('  开发 XXX  ')
        self.assertEqual(app.notes.latest()[0].id, identifier)
        self.assertEqual(app.notes.latest()[0].title, '开发 XXX')
        self.assertEqual(app.notes.latest()[0].created_at, app.notes.clock())
        app.notes.clock = lambda: datetime(2026, 10, 9)
        with self.assertRaises(ValueError):
            app.notes.add('没有时区')

    def test_persist_on_restart_without_task_or_recording_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'notes.sqlite3'
            app = ActivityService(Store(path), FixtureReader())
            try:
                app.notes.add('开发数据看板')
            finally:
                app.close()
            with Store(path) as store:
                reopened = ActivityService(store, FixtureReader())
                self.assertEqual(reopened.notes.latest()[0].title, '开发数据看板')
                self.assertEqual(reopened.tasks.all_tasks(), ())
                self.assertEqual(reopened.store.rows(), [])

    def test_sort_by_instant_then_id_and_limit_display_only(self):
        app = self.device()
        first = app.notes.add('第一条')
        second = app.notes.add('同秒新增')
        self.assertEqual([n.id for n in app.notes.latest()], [second, first])
        app.notes.clock = lambda: datetime(2026, 10, 9, 4, tzinfo=timezone.utc)
        newest = app.notes.add('UTC 新记录')
        self.assertEqual(app.notes.latest()[0].id, newest)
        for index in range(205):
            app.notes.add(f'更多记录 {index}')
        self.assertEqual(len(app.notes.latest()), 200)
        self.assertEqual(sum(r['kind'] == 'notes' for r in app.sync.snapshot().values()), 208)

    def test_two_device_merge_preserves_timestamps_and_avoids_duplicates(self):
        a, b = self.device(), self.device()
        a.notes.add('开发主页')
        b.notes.add('写项目文档')
        local_a, local_b = a.sync.snapshot(), b.sync.snapshot()
        merged, conflicts = merge({}, local_a, local_b)
        self.assertFalse(conflicts)
        payload = encode(merged)
        self.assertEqual(json.loads(payload)['version'], 4)
        remote = decode(payload)
        a.sync.apply(local_a, remote)
        b.sync.apply(local_b, remote)
        self.assertEqual(a.sync.snapshot(), b.sync.snapshot())
        self.assertEqual({n.title for n in a.notes.latest()}, {'开发主页', '写项目文档'})
        self.assertEqual({n.created_at for n in a.notes.latest()}, {a.notes.clock()})
        a.sync.apply(a.sync.snapshot(), remote)
        self.assertEqual(len(a.notes.latest()), 2)

    def test_wire_format_rejects_old_version_and_invalid_timestamp(self):
        app = self.device()
        app.notes.add('开发')
        payload = json.loads(encode(app.sync.snapshot()))
        for version in (1, 2, 3):
            payload['version'] = version
            with self.assertRaises(SyncError):
                decode(json.dumps(payload))
        payload['version'] = 4
        next(iter(payload['records'].values()))['fields']['created_at'] = '2026-10-09T12:00:00'
        with self.assertRaises(SyncError):
            decode(json.dumps(payload))

    def legacy_fixture(self, path):
        app = ActivityService(Store(path), FixtureReader())
        try:
            app.tasks.save(TaskDraft('保留事项', '2026-10-09'))
            identifier = app.store.begin(Activity('code.exe', '保留行为'), datetime.now().astimezone())
            before = app.sync.snapshot()
            app.sync.apply(before, before)
            with app.store.db:
                app.store.db.execute('DROP TABLE notes')
                app.store.db.execute('PRAGMA user_version=7')
            return before, identifier
        finally:
            app.close()

    def test_v7_upgrade_preserves_business_rows_and_sync_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'v7.sqlite3'
            before, identifier = self.legacy_fixture(path)
            with Store(path) as store:
                app = ActivityService(store, FixtureReader())
                self.assertEqual(app.sync.snapshot(), before)
                self.assertEqual(app.sync.baseline(), before)
                self.assertEqual(app.notes.latest(), ())
                self.assertEqual(app.store.db.execute('SELECT id FROM segments').fetchone()[0], identifier)
                self.assertEqual(app.store.db.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)
                self.assertEqual(app.store.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_failed_migration_rolls_back_new_table_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'v7.sqlite3'
            self.legacy_fixture(path)
            with patch('activitylog.storage.NOTE_SCHEMA', NOTE_SCHEMA + ('INVALID SQL',)):
                with self.assertRaises(sqlite3.Error):
                    Store(path)
            db = sqlite3.connect(path)
            try:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 7)
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='notes'").fetchone())
                self.assertEqual(db.execute('SELECT title FROM tasks').fetchone()[0], '保留事项')
            finally:
                db.close()


if __name__ == '__main__':
    unittest.main()
