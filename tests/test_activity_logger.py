import csv
import ctypes
from ctypes import wintypes
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import tempfile
import unittest
import sqlite3

from activitylog.models import Activity, Segment
from activitylog.recording import Recorder
from activitylog.storage import Store
from activitylog.windows import WindowsReader, SingleInstance
from activitylog.analysis import merge_for_display


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.base = datetime(2026, 10, 2, 14, tzinfo=timezone(timedelta(hours=8)))

    def store(self, path=":memory:", **kwargs):
        store = Store(path, **kwargs)
        self.addCleanup(store.db.close)
        return store

    def directory(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return directory.name

    def sample(self, recorder, activity, second, **kwargs):
        return recorder.sample(activity, at=self.base + timedelta(seconds=second), tick=second, **kwargs)

    def test_user_timeline_survives_restart_and_exports_chinese_titles(self):
        directory = self.directory()
        path = Path(directory) / "timeline.sqlite3"
        store = self.store(path)
        recorder = Recorder(store)
        browser = Activity("chrome.exe", "Python 教程 - 浏览器", -1)
        job = Activity("chrome.exe", "某个招聘界面", -1)
        wow = Activity("Wow.exe", "魔兽世界", -2)
        codex = Activity("Codex.exe", "Codex", -3)
        for second, activity in enumerate((browser, browser, wow, job, job, codex)):
            self.sample(recorder, activity, second)
        self.assertEqual(len(store.rows()), 4)
        recorder.stop()
        self.assertTrue(self.sample(recorder, codex, 6))
        store.db.close()
        reopened = self.store(path, recover=True)
        rows = list(reversed(reopened.rows()))
        self.assertEqual([row.app for row in rows],
                         ["浏览器 · Chrome", "魔兽世界", "浏览器 · Chrome", "Codex", "Codex"])
        self.assertEqual([row.seconds for row in rows], [2, 1, 2, 0, 0])
        self.assertTrue(all(row.start.tzinfo is not None for row in rows))
        output = Path(directory) / "日志.csv"
        self.assertEqual(reopened.export(output), 5)
        with output.open(encoding="utf-8-sig", newline="") as stream:
            exported = list(csv.reader(stream))
        self.assertEqual(exported[3][3], "某个招聘界面")
        self.assertEqual(exported[1][3], browser.title)

    def test_exclusions_own_window_and_unavailable_sample(self):
        store = self.store()
        recorder = Recorder(store)
        visible = Activity("chrome.exe", "页面", -1)
        self.assertTrue(self.sample(recorder, visible, 0))
        self.assertTrue(self.sample(recorder, None, 1))
        self.assertTrue(self.sample(recorder, visible, 2))
        self.assertTrue(self.sample(recorder, Activity("private.exe", "私有内容", -2), 3, excluded={"private.exe"}))
        self.assertTrue(self.sample(recorder, visible, 4))
        self.assertTrue(self.sample(recorder, Activity("python.exe", "日志窗口", os.getpid()), 5))
        self.assertTrue(self.sample(recorder, visible, 6))
        self.assertEqual(len(store.rows()), 4)
        self.assertNotIn("私有内容", str(store.rows()))
        self.assertEqual(sum(row.seconds for row in store.rows()), 2)

    def test_csv_keeps_delimiters_and_neutralizes_formula_titles(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(":memory:")
            self.addCleanup(store.db.close)
            identifier = store.begin(Activity("app.exe", '=HYPERLINK("test")'), self.base)
            store.finish(identifier, self.base, 0)
            title = '招聘,职位 "Python"\n详情'
            identifier = store.begin(Activity("app.exe", title), self.base + timedelta(seconds=1))
            store.finish(identifier, self.base + timedelta(seconds=2), 1)
            output = Path(directory) / "export.csv"
            store.export(output)
            with output.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(rows[1][3], '\'=HYPERLINK("test")')
            self.assertEqual(rows[2][3], title)

    def test_lock_and_unlock_do_not_charge_locked_time_to_browser(self):
        store = self.store()
        recorder = Recorder(store)
        browser = Activity("chrome.exe", "文章", -1)
        for second in range(5):
            self.sample(recorder, browser, second)
        for second in range(5, 16):
            self.sample(recorder, None, second, locked=True)
        self.sample(recorder, browser, 16)
        self.sample(recorder, browser, 17)
        recorder.stop()
        rows = list(reversed(store.rows()))
        self.assertEqual([row.kind for row in rows], ["activity", "locked", "activity"])
        self.assertEqual([row.seconds for row in rows], [4, 11, 1])

    def test_sleep_or_delayed_callback_creates_gap_without_inflating_duration(self):
        store = self.store()
        recorder = Recorder(store)
        browser = Activity("chrome.exe", "文章", -1)
        for second in range(6):
            self.sample(recorder, browser, second)
        self.sample(recorder, browser, 3605)
        self.sample(recorder, browser, 3606)
        recorder.stop()
        rows = list(reversed(store.rows()))
        self.assertEqual([row.kind for row in rows], ["activity", "gap", "activity"])
        self.assertEqual(rows[0].status, "interrupted")
        self.assertIsNone(rows[1].seconds)
        self.assertEqual(sum(row.seconds or 0 for row in rows), 6)

    def test_pause_and_crash_recovery_keep_only_confirmed_time(self):
        directory = self.directory()
        path = Path(directory) / "timeline.sqlite3"
        store = self.store(path)
        recorder = Recorder(store)
        activity = Activity("app.exe", "窗口", -1)
        for second in range(4):
            self.sample(recorder, activity, second)
        recorder.stop()
        self.sample(recorder, activity, 100)
        self.sample(recorder, activity, 101)
        store.db.close()  # Simulate process death without Recorder.stop().
        recovered = self.store(path, recover=True)
        rows = list(reversed(recovered.rows()))
        self.assertEqual([row.seconds for row in rows], [3, 1])
        self.assertEqual([row.status for row in rows], ["closed", "interrupted"])
        self.assertFalse(any(row.kind == "gap" for row in rows))

    def test_midnight_split_and_day_export(self):
        directory = self.directory()
        store = self.store()
        recorder = Recorder(store)
        self.base = self.base.replace(hour=23, minute=59, second=58)
        for second in range(5):
            self.sample(recorder, Activity("app.exe", "跨午夜", -1), second)
        recorder.stop()
        before = store.rows(date(2026, 10, 2))
        after = store.rows(date(2026, 10, 3))
        self.assertEqual(before[0].seconds, 2)
        self.assertEqual(after[0].seconds, 2)
        self.assertEqual(after[0].start.hour, 0)
        self.assertEqual(store.rows(date(2026, 10, 4)), [])
        output = Path(directory) / "day.csv"
        store.export(output, date(2026, 10, 3))
        with output.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[1][0].startswith("2026-10-03"))
        self.assertEqual(float(rows[1][5]), 2)


    def test_system_clock_change_never_creates_negative_duration(self):
        store = self.store()
        recorder = Recorder(store)
        activity = Activity("app.exe", "窗口", -1)
        self.sample(recorder, activity, 0)
        self.sample(recorder, activity, 1)
        recorder.sample(activity, at=self.base - timedelta(hours=1), tick=2)
        recorder.stop()
        self.assertEqual(len(store.rows()), 2)
        self.assertTrue(all(row.seconds >= 0 for row in store.rows()))
        self.assertEqual(sum(row.seconds for row in store.rows()), 1)

    def test_three_logger_visits_merge_without_counting_logger_time(self):
        directory = self.directory()
        store = self.store()
        recorder = Recorder(store)
        video = Activity("chrome.exe", "视频页面", -1)
        logger = Activity("python.exe", "行为日志", os.getpid())
        for second in range(14):
            self.sample(recorder, logger if second in (2, 3, 6, 7, 10, 11) else video, second)
        recorder.stop()
        raw = store.rows()
        merged = merge_for_display(raw)
        self.assertEqual(len(raw), 4)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0].parts), 4)
        self.assertEqual(merged[0].seconds, 7)
        self.assertEqual((merged[0].end - merged[0].start).total_seconds(), 13)
        self.assertEqual(sum(row.seconds for row in raw), merged[0].seconds)
        output = Path(directory) / "merged.csv"
        self.assertEqual(store.export(output, merged=True), 1)
        with output.open(encoding="utf-8-sig", newline="") as stream:
            exported = list(csv.reader(stream))
        self.assertEqual(float(exported[1][5]), 7)
        self.assertEqual(exported[1][8], "4")
        self.assertEqual(len(store.rows()), 4)



    def test_logger_then_excluded_or_unavailable_window_is_not_merged(self):
        for unavailable in (None, Activity("private.exe", "私密", -2)):
            with self.subTest(unavailable=unavailable):
                store = self.store()
                recorder = Recorder(store)
                video = Activity("chrome.exe", "视频页面", -1)
                self.sample(recorder, video, 0)
                self.sample(recorder, Activity("python.exe", "日志", os.getpid()), 1)
                self.sample(recorder, unavailable, 2, excluded={"private.exe"})
                self.sample(recorder, video, 3)
                recorder.stop()
                self.assertEqual(len(merge_for_display(store.rows())), 2)

    def test_pause_or_lock_or_long_visit_does_not_merge(self):
        for interruption in ("pause", "lock", "long"):
            with self.subTest(interruption=interruption):
                store = self.store()
                recorder = Recorder(store)
                video = Activity("chrome.exe", "视频页面", -1)
                logger = Activity("python.exe", "日志", os.getpid())
                self.sample(recorder, video, 0)
                self.sample(recorder, logger, 1)
                if interruption == "pause":
                    recorder.stop()
                    self.sample(recorder, video, 3)
                elif interruption == "lock":
                    self.sample(recorder, None, 2, locked=True)
                    self.sample(recorder, video, 3)
                else:
                    for second in range(2, 124):
                        self.sample(recorder, logger, second)
                    self.sample(recorder, video, 124)
                recorder.stop()
                grouped = merge_for_display(store.rows())
                self.assertEqual(len([row for row in grouped if row.kind == "activity"]), 2)
                self.assertFalse(any(row.parts for row in grouped))


@unittest.skipUnless(sys.platform == "win32", "Requires Windows")
class WindowsIntegrationTests(unittest.TestCase):
    def test_current_session_lock_state_is_readable(self):
        self.assertIsInstance(WindowsReader().is_locked(), bool)

    def test_single_instance_handles_are_released(self):
        path = Path(tempfile.gettempdir()) / f"activity-mutex-test-{os.getpid()}"
        first = SingleInstance(path)
        self.addCleanup(first.close)
        second = SingleInstance(path)
        self.addCleanup(second.close)
        self.assertFalse(first.already_running)
        self.assertTrue(second.already_running)
        first.close()
        second.close()
        third = SingleInstance(path)
        self.addCleanup(third.close)
        self.assertFalse(third.already_running)

    def test_unicode_window_title_and_real_process_lookup(self):
        reader = WindowsReader()
        user32 = reader.user32
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                          wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                          wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        # Invisible Win32 window: never activates or samples the user's desktop.
        title = "招聘页面 · Python 开发"
        hwnd = user32.CreateWindowExW(0, "STATIC", title, 0x80000000,
                                     0, 0, 0, 0, None, None, None, None)
        self.assertTrue(hwnd, ctypes.get_last_error())
        try:
            activity = reader.read_window(hwnd)
            self.assertEqual(activity.title, title)
            self.assertEqual(activity.pid, os.getpid())
            self.assertEqual(activity.process.lower(), Path(sys.executable).name.lower())
        finally:
            self.assertTrue(user32.DestroyWindow(hwnd))
        self.assertIsNone(reader.read_window(None))


if __name__ == "__main__":
    unittest.main()
