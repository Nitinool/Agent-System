"""Persistence, date boundaries, shared completion and atomic feature upgrades."""

from dataclasses import replace
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from activitylog.job_service import JobService
from activitylog.job_store import JOB_SCHEMA, JobRepository
from activitylog.jobs import ApplicationDraft
from activitylog.storage import RECORDING_SCHEMA, SCHEMA_VERSION, Store
from activitylog.task_service import TaskService
from activitylog.task_store import TASK_SCHEMA, TaskRepository
from activitylog.tasks import TaskDraft, month_days


class TaskTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "tasks.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        self.today = date(2026, 10, 4)
        self.tasks = TaskService(TaskRepository(self.store.db), today=lambda: self.today)
        self.draft = TaskDraft("修改简历", "2026-10-04", "求职", "检查联系方式\n导出 PDF")

    def snapshot(self, selected=None):
        return self.tasks.snapshot(2026, 10, selected or self.today)

    def test_completion_is_shared_by_calendar_and_today_and_survives_restart(self):
        identifier = self.tasks.save(self.draft, in_today=True)
        self.tasks.complete(identifier, True)
        snapshot = self.snapshot()
        self.assertEqual(snapshot.selected_tasks, snapshot.today_tasks)
        self.assertTrue(snapshot.calendar_tasks[0].completed)
        self.store.close()
        with Store(self.path) as reopened:
            tasks = TaskService(TaskRepository(reopened.db), today=lambda: self.today)
            self.assertEqual(tasks.get(identifier).notes, self.draft.notes)
            self.assertTrue(tasks.snapshot(2026, 10, self.today).today_tasks[0].completed)
            tasks.complete(identifier, False)
            self.assertFalse(tasks.get(identifier).completed)

    def test_arrange_is_idempotent_and_remove_only_removes_today_membership(self):
        identifier = self.tasks.save(replace(self.draft, planned_on="2026-10-08"))
        for _ in range(3):
            self.tasks.arrange_today(identifier)
        self.assertEqual(len(self.snapshot().today_tasks), 1)
        self.assertEqual(self.tasks.get(identifier).planned_on, date(2026, 10, 8))
        self.tasks.remove_today(identifier)
        snapshot = self.snapshot(date(2026, 10, 8))
        self.assertEqual(snapshot.today_tasks, ())
        self.assertEqual(len(snapshot.selected_tasks), 1)
        self.assertEqual(snapshot.total, 1)

    def test_today_list_is_dated_and_does_not_carry_unfinished_tasks_automatically(self):
        identifier = self.tasks.add_today("复习 C 指针")
        self.assertTrue(self.tasks.is_in_today(identifier))
        self.today = date(2026, 10, 5)
        self.assertEqual(self.snapshot().today_tasks, ())
        self.assertFalse(self.tasks.is_in_today(identifier))
        self.tasks.arrange_today(identifier)
        self.tasks.remove_today(identifier)
        self.assertEqual(len(self.tasks.repository.day_tasks(date(2026, 10, 4))), 1)
        self.assertEqual(self.tasks.get(identifier).planned_on, date(2026, 10, 4))

    def test_edit_moves_calendar_date_preserves_completion_and_updates_membership(self):
        identifier = self.tasks.save(self.draft, in_today=True)
        self.tasks.complete(identifier, True)
        edited = TaskDraft(" 修改简历第二版 ", " 2026-11-02 ", "学习", " 更新项目介绍 ")
        self.tasks.save(edited, identifier, in_today=False)
        task = self.tasks.get(identifier)
        self.assertTrue(task.completed)
        self.assertEqual(task.title, "修改简历第二版")
        self.assertEqual(task.notes, "更新项目介绍")
        self.assertEqual(self.snapshot().selected_tasks, ())
        self.assertTrue(all(item.planned_on.month != 10 for item in self.snapshot().calendar_tasks))
        self.assertEqual(self.tasks.snapshot(2026, 11, date(2026, 11, 2)).selected_tasks, (task,))
        self.assertFalse(self.tasks.is_in_today(identifier))

    def test_invalid_edit_preserves_original_fields_and_membership(self):
        identifier = self.tasks.save(self.draft, in_today=True)
        before = self.snapshot()
        for draft in (replace(self.draft, title=" "), replace(self.draft, title="长" * 121),
                      replace(self.draft, planned_on="2026-02-30"), replace(self.draft, category="错误分类"),
                      replace(self.draft, notes="长" * 10001)):
            with self.subTest(draft=draft), self.assertRaises(ValueError):
                self.tasks.save(draft, identifier, in_today=False)
            self.assertEqual(self.snapshot(), before)

    def test_membership_insert_failure_rolls_back_new_task_and_edit(self):
        identifier = self.tasks.save(self.draft)
        before = self.snapshot()
        self.store.db.execute("""CREATE TRIGGER reject_entry BEFORE INSERT ON task_day_entries
            BEGIN SELECT RAISE(ABORT, 'cannot add to today'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.tasks.add_today("失败的新增")
        with self.assertRaises(sqlite3.IntegrityError):
            self.tasks.save(replace(self.draft, title="失败的编辑"), identifier, in_today=True)
        self.assertEqual(self.snapshot(), before)

    def test_delete_cascades_membership_and_keeps_jobs(self):
        jobs = JobService(JobRepository(self.store.db))
        jobs.save_application("测试公司", ApplicationDraft("开发", "2026-10-04"))
        before = jobs.snapshot()
        identifier = self.tasks.add_today("测试事项")
        self.today = date(2026, 10, 5)
        self.tasks.arrange_today(identifier)
        self.tasks.delete(identifier)
        self.assertEqual(self.snapshot().total, 0)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM task_day_entries").fetchone()[0], 0)
        self.assertEqual(self.store.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(jobs.snapshot(), before)

    def test_missing_task_cannot_leave_orphan_membership(self):
        for action in (lambda: self.tasks.arrange_today(999), lambda: self.tasks.complete(999, True),
                       lambda: self.tasks.save(self.draft, 999, in_today=True)):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(self.snapshot().total, 0)
        self.assertEqual(self.snapshot().today_tasks, ())

    def test_other_month_selection_does_not_change_today_list(self):
        self.tasks.add_today("今天的事")
        self.tasks.save(replace(self.draft, planned_on="2026-12-03"))
        snapshot = self.tasks.snapshot(2026, 12, date(2026, 12, 3))
        self.assertEqual(snapshot.selected_tasks[0].title, "修改简历")
        self.assertEqual(snapshot.today_tasks[0].title, "今天的事")
        self.assertEqual(snapshot.today, date(2026, 10, 4))


class CalendarTests(unittest.TestCase):
    def test_monday_first_grid_includes_adjacent_month_and_leap_day(self):
        days = month_days(2028, 2)
        self.assertEqual(len(days), 35)
        self.assertEqual(days[0].weekday(), 0)
        self.assertIn(date(2028, 2, 29), days)
        self.assertIn(date(2028, 1, 31), days)
        self.assertIn(date(2028, 3, 1), days)
        self.assertEqual(len(set(days)), 35)

    def test_calendar_does_not_overflow_at_supported_date_limits(self):
        self.assertIn(date.min, month_days(1, 1))
        self.assertIn(date.max, month_days(9999, 12))


class TaskSchemaTests(unittest.TestCase):
    def version_two(self, path):
        connection = sqlite3.connect(path)
        for statement in RECORDING_SCHEMA + JOB_SCHEMA:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=2")
        connection.execute("""INSERT INTO segments(start_time, last_seen, app, process, title, kind, status, seconds)
            VALUES ('2026-10-04T12:00:00+08:00', '2026-10-04T12:01:00+08:00', '测试', 'fixture.exe',
                    '测试记录', 'activity', 'closed', 60)""")
        connection.execute("INSERT INTO classifications VALUES (1, '学习')")
        connection.execute("INSERT INTO job_companies VALUES (1, '测试公司', '测试公司')")
        connection.execute("""INSERT INTO job_applications VALUES
            (1, 1, '开发', '2026-10-04', '已投递', '', '测试备注')""")
        connection.commit()
        original = {table: connection.execute(f"SELECT * FROM {table}").fetchall()
                    for table in ("segments", "classifications", "job_companies", "job_applications")}
        connection.close()
        return original

    def test_upgrade_preserves_all_existing_activity_and_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.sqlite3"
            original = self.version_two(path)
            with Store(path) as store:
                for table, rows in original.items():
                    self.assertEqual([tuple(row) for row in store.db.execute(f"SELECT * FROM {table}")], rows)
                self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                self.assertEqual(TaskRepository(store.db).count(), 0)

    def test_failed_upgrade_rolls_back_all_new_tables_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.sqlite3"
            original = self.version_two(path)
            with patch("activitylog.storage.TASK_SCHEMA", (TASK_SCHEMA[0], "INVALID SQL")):
                with self.assertRaises(sqlite3.OperationalError):
                    Store(path)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE name LIKE 'task%'").fetchall(), [])
                for table, rows in original.items():
                    self.assertEqual(connection.execute(f"SELECT * FROM {table}").fetchall(), rows)
            finally:
                connection.close()
            with Store(path) as store:
                self.assertEqual(TaskRepository(store.db).count(), 0)


if __name__ == "__main__":
    unittest.main()
