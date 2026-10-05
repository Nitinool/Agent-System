"""Stage integrity, truthful completion history and additive upgrades."""

from dataclasses import replace
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from activitylog.project_service import ProjectService
from activitylog.project_store import PROJECT_SCHEMA, ProjectRepository
from activitylog.demo_project import create_demo_plan
from activitylog.projects import MilestoneDraft, ProjectDraft
from activitylog.storage import JOB_SCHEMA, RECORDING_SCHEMA, SCHEMA_VERSION, Store
from activitylog.task_service import TaskService
from activitylog.task_store import TASK_SCHEMA, TASK_V5_SCHEMA, TaskRepository
from activitylog.tasks import TaskDraft


class MilestoneTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.addCleanup(self.store.close)
        self.tasks = TaskService(TaskRepository(self.store.db), today=lambda: date(2026, 10, 4))
        self.projects = ProjectService(ProjectRepository(self.store.db), self.tasks)
        self.project = self.projects.save(ProjectDraft('Demo'))
        self.stage = self.projects.save_milestone(self.project, MilestoneDraft('第一轮', '同步数据且可撤销'))

    def draft(self, **changes):
        return replace(TaskDraft('第一项', '', project_id=self.project, milestone_id=self.stage,
                                  acceptance='状态在三个页面同步'), **changes)

    def test_stage_progress_excludes_backlog_and_search(self):
        identifier = self.tasks.save(self.draft())
        self.tasks.complete(identifier, True)
        for i in range(4):
            self.tasks.save(self.draft(title=f'未来想法 {i}', milestone_id=None))
        self.assertEqual(self.projects.items(self.project, '找不到'), ())
        stage = self.projects.milestones(self.project)[0]
        self.assertEqual((stage.total, stage.completed), (1, 1))

    def test_completion_history_covers_editor_calendar_and_today_without_duplicate(self):
        identifier = self.tasks.save(self.draft(status='受阻'), in_today=True)
        self.tasks.complete(identifier, True)
        completed_at = self.tasks.get(identifier).completed_at
        self.assertIsNotNone(completed_at)
        self.tasks.complete(identifier, True)
        self.tasks.save(self.draft(title='更新名称', status='已完成', outcome='同步验证通过'), identifier, in_today=True)
        self.assertEqual(self.tasks.get(identifier).completed_at, completed_at)
        self.assertEqual(len(self.projects.completion_records(self.project)), 1)
        self.assertEqual(self.projects.completion_records(self.project)[0].outcome, '同步验证通过')
        self.tasks.complete(identifier, False)
        task = self.tasks.get(identifier)
        self.assertEqual(task.status, '受阻')
        self.assertIsNone(task.completed_at)
        self.assertIsNotNone(self.projects.completion_records(self.project)[0].reopened_at)
        self.tasks.set_status(identifier, '已完成')
        self.assertEqual(len(self.projects.completion_records(self.project)), 2)
        self.assertEqual(self.tasks.today_tasks()[0], self.projects.items(self.project)[0])

    def test_wrong_project_stage_does_not_change_item_or_today(self):
        identifier = self.tasks.save(self.draft())
        before = self.tasks.get(identifier)
        other = self.projects.save(ProjectDraft('另一个'))
        with self.assertRaises(ValueError):
            self.tasks.save(self.draft(project_id=other, status='已完成'), identifier, in_today=True)
        self.assertEqual(self.tasks.get(identifier), before)
        self.assertFalse(self.tasks.is_in_today(identifier))
        self.assertEqual(self.projects.completion_records(self.project), ())

    def test_failed_save_rolls_back_fields_completion_and_membership(self):
        identifier = self.tasks.save(self.draft())
        before = self.tasks.get(identifier)
        with patch.object(self.tasks.repository, '_record_transition', side_effect=sqlite3.OperationalError('失败')):
            with self.assertRaises(sqlite3.Error):
                self.tasks.save(self.draft(status='已完成'), identifier, in_today=True)
        self.assertEqual(self.tasks.get(identifier), before)
        self.assertFalse(self.tasks.is_in_today(identifier))

    def test_milestone_requires_tasks_completed_and_reopens_when_new_work_added(self):
        with self.assertRaises(ValueError):
            self.projects.finish_milestone(self.stage)
        identifier = self.tasks.save(self.draft())
        with self.assertRaises(ValueError):
            self.projects.finish_milestone(self.stage)
        self.tasks.complete(identifier, True)
        self.projects.finish_milestone(self.stage)
        stamp = self.projects.milestones(self.project)[0].completed_at
        self.assertIsNotNone(stamp)
        self.projects.finish_milestone(self.stage)
        self.assertEqual(self.projects.milestones(self.project)[0].completed_at, stamp)
        self.tasks.save(self.draft(title='以后再做', milestone_id=None))
        self.assertEqual(self.projects.milestones(self.project)[0].completed_at, stamp)
        self.tasks.save(self.draft(title='补充验收'))
        self.assertIsNone(self.projects.milestones(self.project)[0].completed_at)

    def test_reopen_and_empty_stage_invalidate_confirmed_milestone(self):
        identifier = self.tasks.save(self.draft(status='已完成'))
        self.projects.finish_milestone(self.stage)
        self.tasks.complete(identifier, False)
        self.assertIsNone(self.projects.milestones(self.project)[0].completed_at)
        self.tasks.complete(identifier, True)
        self.projects.finish_milestone(self.stage)
        self.tasks.save(self.draft(status='已完成', milestone_id=None), identifier)
        self.assertIsNone(self.projects.milestones(self.project)[0].completed_at)

    def test_delete_stage_or_project_retains_shared_items_and_membership(self):
        identifier = self.tasks.save(self.draft(), in_today=True)
        self.projects.delete_milestone(self.stage)
        self.assertIsNone(self.tasks.get(identifier).milestone_id)
        self.assertEqual(self.tasks.get(identifier).project_id, self.project)
        new_stage = self.projects.save_milestone(self.project, MilestoneDraft('第二轮'))
        self.tasks.save(self.draft(milestone_id=new_stage), identifier, in_today=True)
        self.tasks.complete(identifier, True)
        self.projects.delete(self.project)
        self.assertIsNone(self.tasks.get(identifier).project_id)
        self.assertIsNone(self.tasks.get(identifier).milestone_id)
        self.assertTrue(self.tasks.is_in_today(identifier))
        self.assertEqual(self.store.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_validation_and_wrong_project_stage_edit(self):
        for draft in (MilestoneDraft(' '), MilestoneDraft('x' * 61), MilestoneDraft('合法', 'x' * 2001)):
            with self.assertRaises(ValueError):
                self.projects.save_milestone(self.project, draft)
        other = self.projects.save(ProjectDraft('其他'))
        with self.assertRaises(ValueError):
            self.projects.save_milestone(other, MilestoneDraft('错误'), self.stage)
        for draft in (self.draft(milestone_id=999), self.draft(milestone_id='bad'), self.draft(acceptance='x'*2001)):
            with self.assertRaises(ValueError):
                self.tasks.save(draft)

    def test_starter_plan_is_idempotent_and_retains_user_edits(self):
        identifier = create_demo_plan(self.projects)
        task = self.projects.items(identifier)[0]
        self.tasks.save(TaskDraft(task.title, '', project_id=identifier, milestone_id=task.milestone_id,
                                 notes='用户后续修改'), task.id)
        self.assertEqual(create_demo_plan(self.projects), identifier)
        self.assertEqual(len(self.projects.items(identifier)), 10)
        self.assertEqual(self.tasks.get(task.id).notes, '用户后续修改')

    def test_starter_plan_failure_leaves_no_partial_project(self):
        before = self.projects.summaries()
        self.store.db.execute("""CREATE TRIGGER reject_seed BEFORE INSERT ON tasks
            BEGIN SELECT RAISE(ABORT, '测试失败'); END""")
        with self.assertRaises(sqlite3.Error):
            create_demo_plan(self.projects)
        self.assertEqual(self.projects.summaries(), before)


class VersionFourTests(unittest.TestCase):
    def fixture(self, path):
        db = sqlite3.connect(path)
        for sql in RECORDING_SCHEMA + JOB_SCHEMA + PROJECT_SCHEMA + TASK_SCHEMA:
            db.execute(sql)
        db.execute('PRAGMA user_version=4')
        db.execute("INSERT INTO projects VALUES(5,'旧项目','旧项目','保留','进行中')")
        db.execute("INSERT INTO tasks(id,title,project_id,status) VALUES(9,'已完成但时间未知',5,'已完成')")
        db.execute("INSERT INTO task_day_entries VALUES(9,'2026-10-04')")
        db.commit()
        db.close()

    def test_upgrade_keeps_existing_data_and_unknown_completion_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.sqlite3'
            self.fixture(path)
            with Store(path) as store:
                item = TaskRepository(store.db).get(9)
                self.assertTrue(item.completed)
                self.assertIsNone(item.completed_at)
                self.assertEqual(ProjectRepository(store.db).completion_records(5), ())
                self.assertTrue(TaskRepository(store.db).is_on_day(9, date(2026, 10, 4)))
                self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)
                self.assertEqual(store.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_failed_upgrade_rolls_back_tables_and_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.sqlite3'
            self.fixture(path)
            with patch('activitylog.storage.TASK_V5_SCHEMA', TASK_V5_SCHEMA[:2] + ('INVALID SQL',)):
                with self.assertRaises(sqlite3.Error):
                    Store(path)
            db = sqlite3.connect(path)
            try:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
                self.assertNotIn('milestone_id', [row[1] for row in db.execute('PRAGMA table_info(tasks)')])
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='milestones'").fetchone())
                self.assertEqual(db.execute('SELECT title FROM tasks WHERE id=9').fetchone()[0], '已完成但时间未知')
            finally:
                db.close()


if __name__ == '__main__':
    unittest.main()
