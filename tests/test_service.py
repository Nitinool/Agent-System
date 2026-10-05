"""Service boundaries, deterministic clocks, schema creation and resource failures."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from activitylog.config import CapturePolicy
from activitylog.models import Activity
from activitylog.recording import Recorder
from activitylog.service import ActivityService
from activitylog.storage import SCHEMA, Store, UnsupportedSchemaError


class FakeReader:
    def __init__(self):
        self.locked = False
        self.activity = Activity("chrome.exe", "测试页面", 100)
        self.reads = 0

    def is_locked(self):
        return self.locked

    def read(self):
        self.reads += 1
        return self.activity


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.base = datetime(2026, 10, 3, 12, tzinfo=timezone(timedelta(hours=8)))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "test.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        self.reader = FakeReader()

    def service(self, ticks=(0, 1, 2, 3, 4), **kwargs):
        wall = iter(self.base + timedelta(seconds=tick) for tick in ticks)
        mono = iter(ticks)
        recorder = Recorder(self.store, wall_clock=lambda: next(wall), monotonic=lambda: next(mono),
                            process_id=200, **kwargs)
        return ActivityService(self.store, self.reader, recorder=recorder)

    def test_injected_clock_and_process_id_support_logger_visits(self):
        service = self.service()
        service.capture()
        service.capture()
        self.reader.activity = Activity("python.exe", "日志窗口", 200)
        service.capture()
        self.reader.activity = Activity("chrome.exe", "测试页面", 100)
        service.capture()
        service.capture()
        service.pause()
        snapshot = service.day_snapshot(self.base.date())
        grouped = service.visible_rows(snapshot)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0].seconds, 3)
        self.assertEqual(snapshot.summary.total, 3)
        self.assertEqual(len(snapshot.rows), 2)

    def test_locked_and_unknown_session_do_not_read_foreground(self):
        service = self.service()
        self.reader.locked = True
        locked = service.capture()
        self.assertIn("已锁屏", locked.status)
        self.reader.locked = None
        unknown = service.capture()
        self.assertIn("等待恢复", unknown.status)
        self.assertEqual(self.reader.reads, 0)
        self.reader.locked = False
        service.capture()
        self.assertEqual(self.reader.reads, 1)
        self.assertEqual([row.kind for row in self.store.rows()], ["activity", "locked"])

    def test_exclusion_normalization_and_snapshot_filtering(self):
        service = self.service()
        service.capture(" PRIVATE.EXE ， Other.exe ")
        service.capture()
        self.reader.activity = Activity("PRIVATE.exe", "不记录的页面", 101)
        service.capture(" PRIVATE.EXE ， Other.exe ")
        snapshot = service.day_snapshot(self.base.date())
        service.classify(snapshot.rows[0].references, "学习")
        classified = service.day_snapshot(self.base.date())
        self.assertEqual(classified.summary.total, 2)
        self.assertEqual(classified.summary.classified_percent, 100)
        self.assertEqual(classified.summary.category_totals["学习"], 2)
        self.assertEqual(service.visible_rows(classified, keyword="不匹配"), [])
        self.assertEqual(classified.summary.total, snapshot.summary.total)
        self.assertEqual(len(self.store.rows()), 1)

    def test_capture_policy_changes_gap_detection(self):
        service = self.service(ticks=(0, 1, 4), policy=CapturePolicy(max_sample_gap=2))
        service.capture()
        service.capture()
        service.capture()
        service.pause()
        snapshot = service.day_snapshot(self.base.date())
        self.assertEqual(snapshot.summary.total, 1)
        self.assertEqual([row.kind for row in reversed(snapshot.rows)], ["activity", "gap", "activity"])

    def test_close_releases_database_even_when_finish_fails(self):
        service = self.service()
        service.capture()
        with patch.object(self.store, "finish", side_effect=sqlite3.OperationalError("写入失败")):
            with self.assertRaisesRegex(sqlite3.OperationalError, "写入失败"):
                service.close()
        self.assertIsNone(service.recorder.current)
        with self.assertRaises(sqlite3.ProgrammingError):
            self.store.rows()

    def test_database_cannot_be_overwritten_by_csv(self):
        service = self.service()
        service.capture()
        service.pause()
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            service.export(self.path)
        self.assertEqual(self.path.read_bytes(), original)

    def test_failed_checkpoint_does_not_advance_confirmed_duration(self):
        service = self.service()
        service.capture()
        service.capture()
        with patch.object(self.store, "checkpoint", side_effect=sqlite3.OperationalError("保存失败")):
            with self.assertRaises(sqlite3.OperationalError):
                service.capture()
            service.pause()
        row = self.store.rows()[0]
        self.assertEqual(row.seconds, 1)
        self.assertEqual(row.end, self.base + timedelta(seconds=1))

    def test_failed_new_segment_does_not_rewrite_finished_previous_segment(self):
        service = self.service()
        service.capture()
        self.reader.activity = Activity("other.exe", "另一窗口", 101)
        with patch.object(self.store, "begin", side_effect=sqlite3.OperationalError("新段保存失败")):
            with self.assertRaises(sqlite3.OperationalError):
                service.capture()
            service.pause()
        row = self.store.rows()[0]
        self.assertEqual(row.seconds, 1)
        self.assertEqual(row.end, self.base + timedelta(seconds=1))
        self.assertEqual(row.reason, "窗口切换")


class SchemaTests(unittest.TestCase):
    def test_schema_creation_is_atomic_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.sqlite3"
            with patch("activitylog.storage.SCHEMA", (SCHEMA[0], "INVALID SQL")):
                with self.assertRaises(sqlite3.OperationalError):
                    Store(path)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
            finally:
                connection.close()
            with Store(path) as store:
                self.assertEqual(store.rows(), [])

    def test_unknown_database_version_is_rejected_without_modification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA user_version=99")
            connection.close()
            before = path.read_bytes()
            with self.assertRaises(UnsupportedSchemaError):
                Store(path)
            self.assertEqual(path.read_bytes(), before)
            # Windows can rename it only if the failed constructor released its connection.
            path.rename(path.with_suffix(".closed"))

    def test_core_imports_do_not_load_tk_or_windows(self):
        code = "import sys; import activitylog.service; assert 'tkinter' not in sys.modules; assert 'activitylog.windows' not in sys.modules"
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
