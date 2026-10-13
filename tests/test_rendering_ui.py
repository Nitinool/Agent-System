"""Fixture-only regressions for startup, retained widgets and read invalidation."""

from datetime import date
from pathlib import Path
import sqlite3
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from activitylog import bootstrap
from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.tasks import TaskDraft
from activitylog.ui.app import LoggerApp
from tests.ui_smoke import FixtureReader


@unittest.skipUnless(sys.platform == 'win32', 'Tk checks require Windows')
class RenderingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'render.sqlite3'
        service = ActivityService(Store(self.path), FixtureReader())
        service.tasks.today = lambda: date(2026, 10, 13)
        with service.store.db:
            service.store.db.executemany('INSERT INTO tasks(title,planned_on) VALUES(?,?)',
                                        ((f'待办 {index}', '2026-10-13') for index in range(60)))
            service.store.db.executemany('INSERT INTO task_day_entries(task_id,day) VALUES(?,?)',
                                        ((index, '2026-10-13') for index in range(1, 61)))
        self.root = tk.Tk()
        self.root.withdraw()
        self.failures = []
        self.root.report_callback_exception = lambda kind, error, trace: self.failures.append(error)
        self.app = LoggerApp(self.root, service)
        self.addCleanup(self.app.close)

    def test_unchanged_home_keeps_widgets_selection_and_draft(self):
        home = self.app.home_panel
        checks = dict(home.today_list.checks)
        home.note_title.set('尚未提交的输入')
        self.app.service.notes.add('已经保存')
        home.refresh()
        identifier = home.note_table.get_children()[0]
        home.note_table.selection_set(identifier)
        with patch.object(home.today_list.body, 'winfo_children', wraps=home.today_list.body.winfo_children) as children:
            home.refresh()
            children.assert_not_called()
        self.assertEqual(home.today_list.checks, checks)
        self.assertEqual(home.note_table.selection(), (identifier,))
        self.assertEqual(home.note_title.get(), '尚未提交的输入')
        self.assertEqual(home.income.get(), '••••')

    def test_only_changed_task_row_is_replaced_and_failed_checkbox_restores(self):
        home = self.app.home_panel
        old = dict(home.today_list.checks)
        self.app.service.tasks.complete(1, True)
        home.refresh()
        self.assertIsNot(home.today_list.checks[1][1], old[1][1])
        self.assertTrue(home.today_list.checks[1][0].get())
        self.assertTrue(all(home.today_list.checks[i][1] is old[i][1] for i in range(2, 61)))
        with patch.object(self.app.service.tasks, 'complete', side_effect=sqlite3.OperationalError('失败')):
            home.today_list.checks[2][1].invoke()
        self.assertFalse(home.today_list.checks[2][0].get())
        self.assertIs(home.today_list.checks[2][1], old[2][1])
        self.assertEqual([row for task, row in home.today_list.rows.values()], home.today_list.body.pack_slaves())

    def test_home_edit_defers_hidden_calendar_refresh_until_navigation(self):
        panel = self.app.tasks_panel
        with patch.object(panel, 'refresh', wraps=panel.refresh) as refresh:
            self.app.home_panel.quick_title.set('主页新增后检查日历')
            self.app.home_panel.add_today()
            refresh.assert_not_called()
            self.app.select_page('tasks')
            refresh.assert_called_once()
        self.assertIn('主页新增后检查日历', [task.title for task in panel.snapshot.selected_tasks])

    def test_page_cache_detects_own_external_and_midnight_changes(self):
        service = self.app.service
        with patch.object(service.dashboard, 'snapshot', wraps=service.dashboard.snapshot) as read:
            self.app.select_page('home')
            read.assert_not_called()
            service.tasks.save(TaskDraft('本机新任务', '2026-10-13'), in_today=True)
            self.app.select_page('home')
            self.assertEqual(read.call_count, 1)
            with sqlite3.connect(self.path) as peer:
                peer.execute("UPDATE tasks SET title='其他连接更新' WHERE id=1")
            peer.close()
            self.app.select_page('home')
            self.assertEqual(read.call_count, 2)
            self.assertEqual(self.app.home_panel.snapshot.tasks[0].title, '其他连接更新')
            service.tasks.today = lambda: date(2026, 10, 14)
            self.app.select_page('home')
            self.assertEqual(read.call_count, 3)
            self.assertEqual(self.app.home_panel.snapshot.day, date(2026, 10, 14))

    def test_idle_sync_does_not_scan_records_but_notices_new_data(self):
        controller = self.app.sync_controller
        with patch.object(controller.repo, 'snapshot', wraps=controller.repo.snapshot) as read:
            self.root.after_cancel(controller.status_timer)
            controller._watch_status()
            read.assert_not_called()
            self.app.service.notes.add('新随笔')
            self.root.after_cancel(controller.status_timer)
            controller._watch_status()
            self.assertEqual(read.call_count, 1)
            self.assertIn('待同步 61 条', controller.status.get())

    def test_snapshot_bulk_reads_have_bounded_query_count(self):
        queries = []
        db = self.app.service.store.db
        db.set_trace_callback(queries.append)
        try:
            snapshot = self.app.service.sync.snapshot()
        finally:
            db.set_trace_callback(None)
        self.assertEqual(len(snapshot), 60)
        self.assertLessEqual(sum(q.upper().startswith('SELECT') for q in queries), 12)

    def test_only_selected_page_is_mapped_and_old_callbacks_close_cleanly(self):
        self.root.geometry('1100x700+30+30')
        self.root.attributes('-alpha', 0.0)
        self.root.deiconify()
        self.root.update()
        self.assertGreater(self.app.home_panel.winfo_width(), 800)
        self.assertGreater(self.app.home_panel.today_list.canvas.winfo_height(), 100)
        self.root.attributes('-alpha', 1.0)
        for page in ('home', 'tasks', 'projects', 'home', 'finance', 'records'):
            self.app.select_page(page)
            self.root.update()
            self.assertEqual([key for key, frame in self.app.pages.items() if frame.winfo_ismapped()], [page])
        self.assertEqual(self.failures, [])


class StartupTests(unittest.TestCase):
    def test_root_stays_hidden_until_application_and_layout_are_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = MagicMock()
            instance = MagicMock(already_running=False)
            def build(window, service):
                self.assertEqual(window.method_calls[0][0], 'withdraw')
                window.deiconify.assert_not_called()
            with patch.object(bootstrap, '__file__', str(Path(directory) / 'activitylog' / 'bootstrap.py')), \
                    patch.object(bootstrap.sys, 'platform', 'win32'), \
                    patch.object(bootstrap.tk, 'Tk', return_value=root), \
                    patch.object(bootstrap, 'SingleInstance', return_value=instance), \
                    patch.object(bootstrap, 'WindowsReader'), \
                    patch.object(bootstrap, 'Store'), \
                    patch.object(bootstrap, 'ActivityService'), \
                    patch.object(bootstrap, 'LoggerApp', side_effect=build):
                bootstrap.main()
            self.assertEqual([call[0] for call in root.method_calls],
                             ['withdraw', 'attributes', 'deiconify', 'update', 'attributes', 'mainloop'])
            self.assertEqual(root.attributes.call_args_list[0].args, ('-alpha', 0.0))
            self.assertEqual(root.attributes.call_args_list[1].args, ('-alpha', 1.0))


if __name__ == '__main__':
    unittest.main()
