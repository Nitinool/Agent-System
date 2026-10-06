"""Range scheduling, project identities and compatible synchronization."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from activitylog.projects import ProjectDraft
from activitylog.project_store import ProjectRepository
from activitylog.project_service import ProjectService
from activitylog.storage import Store
from activitylog.storage import RECORDING_SCHEMA, JOB_SCHEMA, PROJECT_SCHEMA, TASK_SCHEMA, PROJECT_V5_SCHEMA, TASK_V5_SCHEMA, FINANCE_SCHEMA
from activitylog.project_store import PROJECT_V7_SCHEMA
from activitylog.task_store import TaskRepository
from activitylog.task_service import TaskService
from activitylog.tasks import TaskDraft
from activitylog.sync_store import SyncRepository
from activitylog.sync import LEGACY_FIELDS, SyncError, encode, decode, merge


class ProjectBoardTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.addCleanup(self.store.close)
        self.today = date(2026, 10, 6)
        self.tasks = TaskService(TaskRepository(self.store.db), today=lambda: self.today)
        self.projects = ProjectService(ProjectRepository(self.store.db), self.tasks)
        self.sync = SyncRepository(self.store)
        self.project = self.projects.save(ProjectDraft('测试', priority='高', mode='探索型'))
        self.task = self.tasks.save(TaskDraft('事项', '', project_id=self.project))

    def test_range_is_inclusive_and_completion_exits_then_reopen_returns(self):
        self.tasks.schedule(self.task, '2026-10-06', '2026-10-08')
        self.assertTrue(self.tasks.is_in_today(self.task))
        self.today = date(2026, 10, 8)
        self.assertTrue(self.tasks.is_in_today(self.task))
        self.tasks.complete(self.task, True)
        self.assertFalse(self.tasks.is_in_today(self.task))
        self.tasks.update(self.task, notes='完成后的笔记')
        self.tasks.complete(self.task, False)
        self.assertTrue(self.tasks.is_in_today(self.task))
        self.today = date(2026, 10, 9)
        self.assertFalse(self.tasks.is_in_today(self.task))
        self.assertEqual(len(self.projects.items(self.project)), 1)

    def test_remove_skips_today_only_and_arrange_restores(self):
        self.tasks.schedule(self.task, '2026-10-06', '2026-10-08')
        self.tasks.remove_today(self.task)
        self.assertFalse(self.tasks.is_in_today(self.task))
        self.today = date(2026, 10, 7)
        self.assertTrue(self.tasks.is_in_today(self.task))
        self.today = date(2026, 10, 6)
        self.tasks.arrange_today(self.task)
        self.assertTrue(self.tasks.is_in_today(self.task))

    def test_schedule_changes_clear_old_skips_and_keep_manual_other_day(self):
        self.tasks.arrange_today(self.task)
        self.tasks.schedule(self.task, '2026-10-07', '2026-10-08')
        self.assertTrue(self.tasks.is_in_today(self.task))
        self.today = date(2026, 10, 7)
        self.tasks.remove_today(self.task)
        self.tasks.schedule(self.task, '2026-10-07', '2026-10-09')
        self.assertTrue(self.tasks.is_in_today(self.task))
        self.tasks.schedule(self.task)
        self.assertFalse(self.tasks.is_in_today(self.task))

    def test_date_validation_and_calendar_overlap(self):
        for start, end in [('bad', ''), ('2026-10-08', '2026-10-07'), ('', '2026-10-08')]:
            with self.assertRaises(ValueError):
                self.tasks.schedule(self.task, start, end)
        self.tasks.schedule(self.task, '2026-09-29', '2026-10-08')
        self.assertEqual([t.id for t in self.tasks.repository.between(date(2026,10,6), date(2026,10,6))], [self.task])
        self.assertFalse(self.tasks.repository.unscheduled())

    def test_project_identity_survives_other_device_local_id_collision(self):
        with Store(':memory:') as other:
            tasks = TaskService(TaskRepository(other.db), today=lambda: self.today)
            projects = ProjectService(ProjectRepository(other.db), tasks)
            remote = SyncRepository(other)
            projects.save(ProjectDraft('占用本地编号'))
            records, conflicts = merge({}, remote.snapshot(), self.sync.snapshot())
            self.assertFalse(conflicts)
            remote.apply(remote.snapshot(), records)
            imported = next(s.project for s in projects.summaries() if s.project.name == '测试')
            self.assertNotEqual(imported.id, self.project)
            self.assertEqual(imported.code, self.projects.get(self.project).code)
            self.assertEqual(imported.priority, '高')
            self.assertEqual(imported.mode, '探索型')

    def test_range_and_skip_sync_without_copying_tasks(self):
        self.tasks.schedule(self.task, '2026-10-06', '2026-10-08')
        self.tasks.remove_today(self.task)
        with Store(':memory:') as other:
            sync = SyncRepository(other)
            sync.apply({}, self.sync.snapshot())
            tasks = TaskService(TaskRepository(other.db), today=lambda: self.today)
            self.assertFalse(tasks.today_tasks())
            self.today = date(2026, 10, 7)
            self.assertEqual(len(tasks.today_tasks()), 1)
            self.assertEqual(tasks.today_tasks()[0].project_code, self.projects.get(self.project).code)

    def test_old_wire_normalizes_defaults_and_new_wire_rejects_bad_ranges(self):
        current = self.sync.snapshot()
        old = deepcopy(current)
        for record in old.values():
            record['fields'] = {key: value for key, value in record['fields'].items() if key in LEGACY_FIELDS[record['kind']]}
        payload = json.dumps({'format':'agent-system-data','version':1,'records':old})
        upgraded = decode(payload)
        self.assertEqual(next(r['fields']['mode'] for r in upgraded.values() if r['kind']=='projects'), '目标型')
        self.assertEqual(json.loads(encode(current))['version'], 3)
        bad = deepcopy(current)
        task = next(r['fields'] for r in bad.values() if r['kind']=='tasks')
        task['range_start'], task['range_end'] = '2026-10-08', '2026-10-06'
        with self.assertRaises(SyncError):
            encode(bad)

    def test_project_lane_edit_keeps_identity_and_rejects_bad_metadata(self):
        before = self.projects.get(self.project).code
        self.projects.set_lane(self.project, 'Archive')
        self.assertEqual(self.projects.get(self.project).lane, 'Archive')
        self.assertEqual(self.projects.get(self.project).code, before)
        for changes in ({'mode':'bad'}, {'priority':'bad'}, {'name':''}):
            with self.assertRaises(ValueError):
                self.projects.update(self.project, **changes)

    def test_v3_missing_schedule_fields_are_rejected(self):
        payload = json.loads(encode(self.sync.snapshot()))
        task = next(r['fields'] for r in payload['records'].values() if r['kind'] == 'tasks')
        del task['range_end']
        with self.assertRaises(SyncError):
            decode(json.dumps(payload))


class BoardMigrationTests(unittest.TestCase):
    def fixture(self, path):
        db = sqlite3.connect(path)
        try:
            with db:
                for statement in RECORDING_SCHEMA + JOB_SCHEMA + PROJECT_SCHEMA + TASK_SCHEMA + PROJECT_V5_SCHEMA + TASK_V5_SCHEMA + FINANCE_SCHEMA:
                    db.execute(statement)
                db.execute("INSERT INTO projects(name,name_key,status) VALUES('保留项目','保留项目','暂停')")
                db.execute("INSERT INTO tasks(title,project_id,status) VALUES('保留事项',1,'受阻')")
                db.execute("CREATE TABLE sync_entities(uid TEXT PRIMARY KEY,kind TEXT,local_id INTEGER,UNIQUE(kind,local_id))")
                db.execute("INSERT INTO sync_entities VALUES(?, 'projects', 1)", ('1' * 32,))
                db.execute('PRAGMA user_version=6')
        finally:
            db.close()

    def test_v6_migration_preserves_identity_status_and_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'v6.sqlite3'
            self.fixture(path)
            with Store(path) as store:
                project = ProjectRepository(store.db).get(1)
                self.assertEqual(project.key, '1' * 32)
                self.assertEqual(project.lane, 'Planning')
                self.assertEqual(project.mode, '目标型')
                self.assertEqual(TaskRepository(store.db).get(1).status, '受阻')
                self.assertEqual(store.db.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(SyncRepository(store).snapshot()['1' * 32]['kind'], 'projects')

    def test_failed_upgrade_rolls_back_columns_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'v6.sqlite3'
            self.fixture(path)
            with patch('activitylog.storage.PROJECT_V7_SCHEMA', PROJECT_V7_SCHEMA + ('INVALID SQL',)):
                with self.assertRaises(sqlite3.Error):
                    Store(path)
            db = sqlite3.connect(path)
            try:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)
                self.assertNotIn('project_key', [r[1] for r in db.execute('PRAGMA table_info(projects)')])
                self.assertEqual(db.execute('SELECT status FROM tasks').fetchone()[0], '受阻')
            finally:
                db.close()
