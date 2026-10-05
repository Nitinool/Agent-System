"""Local preferences persist independently of records and credentials."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from activitylog.sync import SyncError
from activitylog.sync_settings import SyncSettings, SyncSettingsStore


class SyncSettingsTests(unittest.TestCase):
    def test_defaults_and_restart_preserve_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SyncSettingsStore(directory)
            self.assertEqual(store.load(), SyncSettings(True, False))
            store.save(SyncSettings(False, True))
            self.assertEqual(SyncSettingsStore(directory).load(), SyncSettings(False, True))
            self.assertEqual(json.loads(store.path.read_text()), {"check_on_start": False, "auto_sync": True})

    def test_invalid_settings_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SyncSettingsStore(directory)
            for content in ('{', '[]', '{"check_on_start":true}',
                            '{"check_on_start":true,"auto_sync":"false"}',
                            '{"check_on_start":true,"auto_sync":1}'):
                with self.subTest(content=content):
                    store.path.write_text(content, encoding="utf-8")
                    with self.assertRaises(SyncError):
                        store.load()

    def test_failed_atomic_save_keeps_previous_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SyncSettingsStore(directory)
            store.save(SyncSettings())
            with patch("activitylog.sync_settings.os.replace", side_effect=OSError("测试写入失败")):
                with self.assertRaises(OSError):
                    store.save(SyncSettings(False, True))
            self.assertEqual(store.load(), SyncSettings())
            self.assertEqual([p.name for p in Path(directory).iterdir()], [store.path.name])
