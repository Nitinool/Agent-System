"""Hidden Tk windows exercise error recovery without collecting desktop activity."""

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform == "win32", "Hidden Tk check requires Windows")
class UIErrorTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from activitylog.models import Activity
        from activitylog.service import ActivityService
        from activitylog.storage import Store
        from activitylog.ui.app import LoggerApp

        class Reader:
            def is_locked(self):
                return False

            def read(self):
                return Activity("fixture.exe", "测试界面", -1)

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        store = Store(Path(directory.name) / "ui.sqlite3")
        self.app = LoggerApp(self.root, ActivityService(store, Reader()))
        self.addCleanup(self.app.close)

    def test_capture_failure_stops_timers_and_keeps_original_error(self):
        app = self.app
        app.toggle()
        self.root.after_cancel(app.timer)
        app.timer = None  # Simulate the pending callback being delivered.
        app.filter_keyword.set("测试")
        self.assertIsNotNone(app.filter_timer)
        with patch.object(app.service.store, "checkpoint", side_effect=sqlite3.OperationalError("原始采集错误")), \
                patch.object(app.service.store, "finish", side_effect=sqlite3.OperationalError("后续暂停错误")), \
                patch("activitylog.ui.app.messagebox.showerror") as dialog:
            app.poll()
        self.assertFalse(app.running)
        self.assertIsNone(app.timer)
        self.assertIsNone(app.filter_timer)
        self.assertIsNone(app.service.recorder.current)
        self.assertEqual(dialog.call_count, 1)
        self.assertEqual(dialog.call_args.args[1], "原始采集错误")

    def test_refresh_failure_preserves_rows_and_stops_capture(self):
        app = self.app
        app.toggle()
        rows = app.table.get_children()
        with patch.object(app.service, "day_snapshot", side_effect=sqlite3.OperationalError("查询失败")), \
                patch("activitylog.ui.app.messagebox.showerror") as dialog:
            app.refresh()
        self.assertFalse(app.running)
        self.assertIsNone(app.timer)
        self.assertEqual(app.table.get_children(), rows)
        self.assertEqual(dialog.call_args.args[1], "查询失败")


if __name__ == "__main__":
    unittest.main()
