"""Project links, priorities, shared progress and atomic schema v3 upgrades."""

from dataclasses import replace
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from activitylog.job_store import JOB_SCHEMA
from activitylog.project_service import ProjectService
from activitylog.project_store import ProjectRepository
from activitylog.projects import ProjectDraft
from activitylog.storage import RECORDING_SCHEMA, SCHEMA_VERSION, Store
from activitylog.task_service import TaskService
from activitylog.task_store import TASK_SCHEMA_V3, TASK_V4_MIGRATION, TaskRepository
from activitylog.tasks import TaskDraft


class ProjectTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "projects.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        self.tasks = TaskService(TaskRepository(self.store.db), today=lambda: date(2026, 10, 4))
        self.projects = ProjectService(ProjectRepository(self.store.db), self.tasks)
        self.project = self.projects.save(ProjectDraft("个人记录", "客观记录生活和时间分配"))

    def draft(self, **values):
        return replace(TaskDraft("完善项目管理", "", project_id=self.project, kind="功能"), **values)

    def test_backlog_calendar_today_and_progress_share_one_record(self):
        identifier = self.tasks.save(self.draft(priority="紧急", status="进行中"))
        snapshot = self.tasks.snapshot(2026, 10, date(2026, 10, 4))
        self.assertEqual(snapshot.calendar_tasks, ())
        self.assertEqual(len(snapshot.unscheduled_tasks), 1)
        self.assertIsNone(self.projects.items(self.project)[0].planned_on)
        self.tasks.arrange_today(identifier)
        snapshot = self.tasks.snapshot(2026, 10, date(2026, 10, 4))
        self.assertEqual(snapshot.unscheduled_tasks, ())
        self.assertEqual(snapshot.selected_tasks, snapshot.today_tasks)
        self.assertEqual(snapshot.total, 1)
        self.assertEqual(self.projects.items(self.project)[0].id, identifier)
        self.tasks.complete(identifier, True)
        self.assertTrue(self.projects.items(self.project)[0].completed)
        self.assertEqual(self.projects.summaries()[0].completed, 1)
        self.tasks.complete(identifier, False)
        self.assertEqual(self.tasks.get(identifier).status, "进行中")
        self.assertEqual(self.projects.summaries()[0].completed, 0)

    def test_priority_sorting_and_fading_do_not_change_priority(self):
        identifiers = {priority: self.tasks.save(self.draft(title=priority, priority=priority), in_today=True)
                       for priority in ("低", "普通", "紧急", "高")}
        self.assertEqual([task.priority for task in self.projects.items(self.project)], ["紧急", "高", "普通", "低"])
        self.tasks.complete(identifiers["紧急"], True)
        self.assertEqual([task.priority for task in self.tasks.today_tasks()], ["高", "普通", "低", "紧急"])
        self.assertEqual(self.tasks.get(identifiers["紧急"]).priority, "紧急")

    def test_completion_restores_blocked_or_in_progress_state_after_edit(self):
        identifier = self.tasks.save(self.draft(status="受阻"))
        self.tasks.complete(identifier, True)
        self.tasks.save(self.draft(title="更新备注", status="已完成", priority="高"), identifier)
        self.tasks.complete(identifier, False)
        self.assertEqual(self.tasks.get(identifier).status, "受阻")
        self.tasks.set_status(identifier, "进行中")
        self.tasks.set_status(identifier, "已完成")
        self.tasks.complete(identifier, False)
        self.assertEqual(self.tasks.get(identifier).status, "进行中")

    def test_filters_do_not_change_progress_totals(self):
        self.tasks.save(self.draft(title="修复中文界面", status="受阻", kind="问题", notes="等待复现"))
        self.tasks.save(self.draft(title="README", status="已完成"))
        self.assertEqual(len(self.projects.items(self.project, "复现", "受阻")), 1)
        self.assertEqual(self.projects.items(self.project, "README", "进行中"), ())
        summary = self.projects.summaries()[0]
        self.assertEqual((summary.total, summary.completed), (2, 1))

    def test_reassignment_and_project_deletion_keep_tasks_and_today_membership(self):
        other = self.projects.save(ProjectDraft("另一个项目"))
        identifier = self.tasks.save(self.draft(planned_on="2026-10-06"), in_today=True)
        self.tasks.save(self.draft(project_id=other, planned_on="2026-10-06", priority="高"), identifier, in_today=True)
        self.assertEqual(self.projects.items(self.project), ())
        self.assertEqual(len(self.projects.items(other)), 1)
        self.projects.delete(other)
        self.assertIsNone(self.tasks.get(identifier).project_id)
        self.assertEqual(self.tasks.get(identifier).planned_on, date(2026, 10, 6))
        self.assertTrue(self.tasks.is_in_today(identifier))
        self.assertEqual(self.store.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_validation_does_not_modify_task_or_today_membership(self):
        identifier = self.tasks.save(self.draft())
        before = self.tasks.get(identifier)
        for draft in (self.draft(project_id=999), self.draft(priority="不支持"), self.draft(status="不支持"),
                      self.draft(kind="不支持"), self.draft(project_id="错误编号")):
            with self.subTest(draft=draft), self.assertRaises(ValueError):
                self.tasks.save(draft, identifier, in_today=True)
            self.assertEqual(self.tasks.get(identifier), before)
        self.assertEqual(self.tasks.today_tasks(), ())
        with self.assertRaises(ValueError):
            self.tasks.set_status(identifier, "错误状态")

    def test_failed_today_assignment_rolls_back_automatic_date(self):
        identifier = self.tasks.save(self.draft())
        self.store.db.execute("""CREATE TRIGGER reject_today BEFORE INSERT ON task_day_entries
            BEGIN SELECT RAISE(ABORT, 'cannot arrange today'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.tasks.arrange_today(identifier)
        self.assertIsNone(self.tasks.get(identifier).planned_on)
        self.assertFalse(self.tasks.is_in_today(identifier))

    def test_edit_and_restart_preserve_project_and_task_attributes(self):
        self.projects.save(ProjectDraft("个人记录第二版", "项目目标\n更多说明", "暂停"), self.project)
        identifier = self.tasks.save(self.draft(priority="高", kind="问题", status="受阻", notes="等待复现"))
        self.store.close()
        with Store(self.path) as reopened:
            tasks = TaskService(TaskRepository(reopened.db))
            projects = ProjectService(ProjectRepository(reopened.db), tasks)
            self.assertEqual(projects.get(self.project).status, "暂停")
            self.assertEqual(projects.get(self.project).goal, "项目目标\n更多说明")
            self.assertEqual((tasks.get(identifier).priority, tasks.get(identifier).status), ("高", "受阻"))
            self.assertIsNone(tasks.get(identifier).planned_on)

    def test_project_validation_and_duplicate_rename_preserve_saved_projects(self):
        other = self.projects.save(ProjectDraft("第二个项目"))
        with self.assertRaises(ValueError):
            self.projects.save(ProjectDraft("个人记录"), other)
        self.assertEqual(self.projects.get(other).name, "第二个项目")
        self.assertEqual((self.projects.summaries()[0].total, self.projects.summaries()[0].completed), (0, 0))
        for draft in (ProjectDraft(" "), ProjectDraft("长" * 121), ProjectDraft("测试", status="错误状态")):
            with self.assertRaises(ValueError):
                self.projects.save(draft)


class ProjectSchemaTests(unittest.TestCase):
    def version_three(self, path):
        connection = sqlite3.connect(path)
        for statement in RECORDING_SCHEMA + JOB_SCHEMA + TASK_SCHEMA_V3:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=3")
        connection.execute("""INSERT INTO tasks VALUES
            (5, '待办任务', '2026-10-04', '开发', '原始备注', 0),
            (8, '完成任务', '2026-10-06', '求职', '已完成备注', 1)""")
        connection.execute("INSERT INTO task_day_entries VALUES (5, '2026-10-04'), (8, '2026-10-04'), (5, '2026-10-03')")
        connection.execute("""INSERT INTO segments(start_time, last_seen, app, process, title, kind, status, seconds)
            VALUES ('2026-10-04T12:00:00+08:00', '2026-10-04T12:01:00+08:00', '测试', 'fixture.exe',
                    '原始活动', 'activity', 'closed', 60)""")
        connection.execute("INSERT INTO classifications VALUES (1, '学习')")
        connection.execute("INSERT INTO job_companies VALUES (1, '测试公司', '测试公司')")
        connection.execute("INSERT INTO job_applications VALUES (1, 1, '开发', '2026-10-04', '已投递', '', '')")
        original = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in
                    ("tasks", "task_day_entries", "segments", "classifications", "job_companies", "job_applications")}
        connection.commit()
        connection.close()
        return original

    def test_upgrade_preserves_tasks_memberships_jobs_activity_and_foreign_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v3.sqlite3"
            original = self.version_three(path)
            with Store(path) as store:
                for table in original.keys() - {"tasks"}:
                    self.assertEqual([tuple(row) for row in store.db.execute(f"SELECT * FROM {table}")], original[table])
                tasks = TaskService(TaskRepository(store.db), today=lambda: date(2026, 10, 4))
                self.assertEqual(tasks.get(5).status, "待开始")
                self.assertEqual(tasks.get(8).status, "已完成")
                self.assertEqual(tasks.get(8).notes, "已完成备注")
                self.assertEqual(tasks.get(5).priority, "普通")
                self.assertIsNone(tasks.get(5).project_id)
                self.assertEqual(len(tasks.today_tasks()), 2)
                self.assertEqual(store.db.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                tasks.delete(5)
                self.assertEqual(store.db.execute("SELECT COUNT(*) FROM task_day_entries WHERE task_id=5").fetchone()[0], 0)

    def test_failure_after_old_tables_drop_rolls_back_the_entire_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v3.sqlite3"
            original = self.version_three(path)
            with patch("activitylog.storage.TASK_V4_MIGRATION", TASK_V4_MIGRATION[:6] + ("INVALID SQL",)):
                with self.assertRaises(sqlite3.OperationalError):
                    Store(path)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
                for table, rows in original.items():
                    self.assertEqual(connection.execute(f"SELECT * FROM {table}").fetchall(), rows)
                names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertNotIn("tasks_next", names)
                self.assertNotIn("projects", names)
            finally:
                connection.close()
            with Store(path) as store:
                self.assertEqual(TaskRepository(store.db).count(), 2)


if __name__ == "__main__":
    unittest.main()
