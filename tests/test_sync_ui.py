"""Hidden-window scheduling tests with a fake clock, network and temporary data."""

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.sync import SyncError
from activitylog.sync_settings import SyncSettings
from activitylog.tasks import TaskDraft
from activitylog.ui.app import LoggerApp
from tests.ui_smoke import FixtureReader


@unittest.skipUnless(sys.platform == "win32", "Hidden Tk checks require Windows")
class SyncUITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "a" / "ui.sqlite3"
        self.path.parent.mkdir()
        peer_path = Path(directory.name) / "b" / "peer.sqlite3"
        peer_path.parent.mkdir()
        self.peer = ActivityService(Store(peer_path), FixtureReader())
        self.addCleanup(self.peer.close)
        self.now = 1000
        clock = patch("activitylog.ui.sync.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.remote = {}
        self.fetch_count = self.publish_count = 0
        self.worker_ids = []
        self.fetch_error = None
        self.fetch_entered = threading.Event()
        self.fetch_release = threading.Event()
        self.fetch_release.set()
        self.publish_entered = threading.Event()
        self.publish_release = threading.Event()
        self.publish_release.set()
        case = self

        class Transport:
            def __init__(self, token):
                case.assertEqual(token, "test-only-token")

            def fetch(self):
                case.fetch_count += 1
                case.worker_ids.append(threading.get_ident())
                case.fetch_entered.set()
                if not case.fetch_release.wait(3):
                    raise SyncError("测试网络等待超时")
                if case.fetch_error:
                    raise case.fetch_error
                return deepcopy(case.remote), "a" * 40

            def publish(self, records, sha):
                case.assertEqual(sha, "a" * 40)
                case.publish_count += 1
                case.worker_ids.append(threading.get_ident())
                case.publish_entered.set()
                if not case.publish_release.wait(3):
                    raise SyncError("测试上传等待超时")
                case.remote = deepcopy(records)

        transport = patch("activitylog.ui.sync.GitHubSync", Transport)
        transport.start()
        self.addCleanup(transport.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = LoggerApp(self.root, ActivityService(Store(self.path), FixtureReader()))
        self.controller = self.app.sync_controller
        self.addCleanup(lambda: self.app.close())
        self.addCleanup(self.fetch_release.set)
        self.addCleanup(self.publish_release.set)
        self.cancel_timer("startup_timer")

    def cancel_timer(self, name):
        timer = getattr(self.controller, name)
        if timer is not None:
            self.root.after_cancel(timer)
            setattr(self.controller, name, None)

    def tick(self, seconds=0):
        self.now += seconds
        self.cancel_timer("status_timer")
        self.controller._watch_status()

    def wait(self):
        deadline = time.perf_counter() + 4
        while self.controller.busy and time.perf_counter() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.controller.busy, self.controller.notice.get())

    def enable_auto(self):
        self.controller.token = "test-only-token"
        self.controller.auto_sync.set(True)
        self.controller._save_settings()

    def publish_peer(self):
        self.remote = self.peer.sync.snapshot()

    def test_sidebar_updates_without_opening_settings(self):
        self.app.service.tasks.save(TaskDraft("本机新增", ""))
        self.tick()
        self.assertIsNone(self.controller.dialog)
        self.assertEqual(str(self.controller.sidebar_label.cget("textvariable")), str(self.controller.sidebar_status))
        self.assertIn("待同步 1 条", self.controller.sidebar_status.get())
        self.assertEqual(self.fetch_count, 0)

    def test_startup_check_uses_saved_token_and_never_writes(self):
        self.peer.tasks.save(TaskDraft("远端新增", ""))
        self.publish_peer()
        self.controller.tokens.save("test-only-token")
        before = self.app.service.sync.snapshot()
        self.controller._startup()
        self.wait()
        self.assertEqual(self.fetch_count, 1)
        self.assertEqual(self.publish_count, 0)
        self.assertEqual(self.app.service.sync.snapshot(), before)
        self.assertEqual(self.app.service.sync.baseline(), {})
        self.assertIn("远端有更新", self.controller.sidebar_status.get())
        self.assertIsNone(self.controller.dialog)

    def test_no_token_or_disabled_startup_makes_no_request(self):
        self.controller._startup()
        self.assertIn("未配置 Token", self.controller.sidebar_status.get())
        self.controller.settings = SyncSettings(False, False)
        self.controller.token = "test-only-token"
        self.controller._startup()
        self.assertEqual(self.fetch_count, 0)
        self.assertFalse(self.controller.busy)

    def test_auto_sync_waits_for_edits_to_settle_and_keeps_capture_running(self):
        self.enable_auto()
        self.app.toggle()
        identifier = self.app.service.tasks.save(TaskDraft("第一版", ""))
        self.tick()
        self.tick(4)
        self.assertEqual(self.fetch_count, 0)
        self.app.service.tasks.save(TaskDraft("第二版", ""), identifier)
        self.tick(1)
        self.tick(4)
        self.assertEqual(self.fetch_count, 0)
        self.tick(1)
        self.wait()
        self.assertEqual(self.publish_count, 1)
        self.assertEqual(self.remote, self.app.service.sync.snapshot())
        self.assertTrue(self.app.running)
        self.assertEqual(self.app.service.sync.status()[0], 0)
        self.assertIsNone(self.controller.dialog)
        self.assertTrue(all(identifier != threading.get_ident() for identifier in self.worker_ids))
        self.assertTrue(self.controller.auto_sync.get())
        self.app.service.tasks.save(TaskDraft("第三版", ""), identifier)
        self.tick()
        self.assertIn("本机有修改", self.controller.sidebar_status.get())
        self.assertIn("待同步 1 条", self.controller.sidebar_status.get())

    def test_auto_fetches_remote_changes_every_five_minutes(self):
        self.enable_auto()
        self.tick(5)
        self.wait()
        self.assertEqual(self.fetch_count, 1)
        self.peer.tasks.save(TaskDraft("另一台修改", ""))
        self.publish_peer()
        self.tick(299)
        self.assertEqual(self.fetch_count, 1)
        self.tick(1)
        self.wait()
        self.assertEqual(self.fetch_count, 2)
        self.assertEqual(self.publish_count, 0)
        self.assertEqual(self.remote, self.app.service.sync.snapshot())

    def test_auto_conflicts_pause_until_manual_choice(self):
        identifier = self.app.service.tasks.save(TaskDraft("共享事项", ""))
        original = self.app.service.sync.snapshot()
        self.app.service.sync.apply(original, original)
        self.remote = deepcopy(original)
        self.app.service.tasks.save(TaskDraft("本机编辑", ""), identifier)
        next(iter(self.remote.values()))["fields"]["title"] = "远端编辑"
        before = self.app.service.sync.snapshot()
        self.enable_auto()
        with patch("activitylog.ui.sync.resolve_conflict") as resolver:
            self.controller.start(automatic=True)
            self.wait()
            resolver.assert_not_called()
        self.assertTrue(self.controller.automatic_paused)
        self.assertIn("冲突", self.controller.sidebar_status.get())
        self.assertEqual(self.app.service.sync.snapshot(), before)
        self.assertEqual(self.app.service.sync.baseline(), original)
        self.assertEqual(self.publish_count, 0)
        self.tick(1000)
        self.assertEqual(self.fetch_count, 1)
        self.controller.open()
        with patch("activitylog.ui.sync.resolve_conflict", return_value="local") as resolver:
            self.controller.start()
            self.wait()
            resolver.assert_called_once()
        self.assertFalse(self.controller.automatic_paused)
        self.assertEqual(self.app.service.sync.status()[0], 0)

    def test_network_failure_backs_off_and_recovers(self):
        self.enable_auto()
        self.app.service.tasks.save(TaskDraft("离线修改", ""))
        before = self.app.service.sync.snapshot()
        self.fetch_error = SyncError("测试离线")
        self.tick()
        self.tick(5)
        self.wait()
        self.assertEqual(self.app.service.sync.snapshot(), before)
        self.assertEqual(self.app.service.sync.baseline(), {})
        self.assertIn("失败", self.controller.sidebar_status.get())
        self.tick(29)
        self.assertEqual(self.fetch_count, 1)
        self.fetch_error = None
        self.tick(1)
        self.wait()
        self.assertEqual(self.fetch_count, 2)
        self.assertEqual(self.app.service.sync.status()[0], 0)

    def test_clean_device_retries_failed_remote_check_after_backoff(self):
        self.enable_auto()
        self.fetch_error = SyncError("测试离线")
        self.controller._startup()
        self.wait()
        self.assertEqual(self.fetch_count, 1)
        self.assertEqual(self.app.service.sync.status()[0], 0)
        self.tick(29)
        self.assertEqual(self.fetch_count, 1)
        self.fetch_error = None
        self.tick(1)
        self.wait()
        self.assertEqual(self.fetch_count, 2)
        self.assertEqual(self.publish_count, 0)

    def test_edit_during_download_is_reconsidered_without_upload(self):
        self.enable_auto()
        identifier = self.app.service.tasks.save(TaskDraft("开始前", ""))
        self.fetch_release.clear()
        self.controller.start(automatic=True)
        self.assertTrue(self.fetch_entered.wait(2))
        self.app.service.tasks.save(TaskDraft("下载时修改", ""), identifier)
        self.fetch_release.set()
        self.wait()
        self.assertEqual(self.publish_count, 0)
        self.assertEqual(self.app.service.sync.baseline(), {})
        self.assertEqual(self.app.service.tasks.get(identifier).title, "下载时修改")

    def test_edit_during_upload_retains_local_content_and_old_baseline(self):
        self.enable_auto()
        identifier = self.app.service.tasks.save(TaskDraft("上传前", ""))
        self.publish_release.clear()
        self.controller.start(automatic=True)
        deadline = time.perf_counter() + 3
        while not self.publish_entered.is_set() and time.perf_counter() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(self.publish_entered.is_set())
        self.app.service.tasks.save(TaskDraft("上传时修改", ""), identifier)
        self.publish_release.set()
        self.wait()
        self.assertEqual(self.app.service.sync.baseline(), {})
        self.assertEqual(self.app.service.tasks.get(identifier).title, "上传时修改")
        self.assertIn("待同步 1 条", self.controller.sidebar_status.get())

    def test_modal_editor_defers_automatic_sync(self):
        self.enable_auto()
        self.app.service.tasks.save(TaskDraft("编辑中", ""))
        self.tick()
        with patch.object(self.root, "grab_current", return_value=object()):
            self.tick(5)
            self.assertEqual(self.fetch_count, 0)
        self.tick()
        self.wait()
        self.assertEqual(self.fetch_count, 1)

    def test_editor_opened_during_download_defers_import(self):
        self.enable_auto()
        self.peer.tasks.save(TaskDraft("远端新增", ""))
        self.publish_peer()
        self.fetch_release.clear()
        self.controller.start(automatic=True)
        self.assertTrue(self.fetch_entered.wait(2))
        with patch.object(self.root, "grab_current", return_value=object()):
            self.fetch_release.set()
            self.wait()
        self.assertEqual(self.app.service.sync.snapshot(), {})
        self.assertEqual(self.publish_count, 0)

    def test_editor_opened_during_upload_defers_local_import(self):
        self.enable_auto()
        self.app.service.tasks.save(TaskDraft("本机事项", ""))
        before = self.app.service.sync.snapshot()
        self.peer.tasks.save(TaskDraft("远端新增", ""))
        self.publish_peer()
        self.publish_release.clear()
        self.controller.start(automatic=True)
        deadline = time.perf_counter() + 3
        while not self.publish_entered.is_set() and time.perf_counter() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(self.publish_entered.is_set())
        with patch.object(self.root, "grab_current", return_value=object()):
            self.publish_release.set()
            self.wait()
        self.assertEqual(self.app.service.sync.snapshot(), before)
        self.assertEqual(self.app.service.sync.baseline(), {})
        self.tick()
        self.tick(30)
        self.wait()
        self.assertEqual(self.remote, self.app.service.sync.snapshot())
        self.assertEqual(self.app.service.sync.status()[0], 0)

    def test_settings_dialog_can_close_while_background_sync_finishes(self):
        self.enable_auto()
        self.app.service.tasks.save(TaskDraft("后台同步", ""))
        self.controller.open()
        self.fetch_release.clear()
        self.controller.start(automatic=True)
        self.assertTrue(self.fetch_entered.wait(2))
        self.controller._close_dialog()
        self.fetch_release.set()
        self.wait()
        self.assertIsNone(self.controller.dialog)
        self.assertIn("待同步 0 条", self.controller.sidebar_status.get())

    def test_forgetting_token_stops_auto_requests(self):
        self.enable_auto()
        self.controller.open()
        self.controller.tokens.save("test-only-token")
        self.controller.forget()
        self.app.service.tasks.save(TaskDraft("尚未同步", ""))
        self.tick()
        self.tick(600)
        self.assertEqual(self.fetch_count, 0)
        self.assertEqual(self.controller.tokens.load(), "")
        self.assertEqual(self.controller.token, "")

    def test_auto_does_not_consume_unsubmitted_token_input(self):
        self.enable_auto()
        self.controller.open()
        self.controller.token_var.set("new-token-being-typed")
        self.controller.start(automatic=True)
        self.wait()
        self.assertEqual(self.controller.token_var.get(), "new-token-being-typed")

    def test_preferences_survive_restart(self):
        self.controller.check_on_start.set(False)
        self.controller.auto_sync.set(True)
        self.controller._save_settings()
        self.app.close()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = LoggerApp(self.root, ActivityService(Store(self.path), FixtureReader()))
        self.controller = self.app.sync_controller
        self.assertTrue(self.controller.auto_sync.get())
        self.assertFalse(self.controller.check_on_start.get())

    def test_failed_preferences_save_keeps_previous_behavior(self):
        self.controller.auto_sync.set(True)
        with patch.object(self.controller.settings_store, "save", side_effect=OSError()):
            self.controller._save_settings()
        self.assertFalse(self.controller.auto_sync.get())
        self.assertFalse(self.controller.settings.auto_sync)
        self.assertIn("未保存", self.controller.notice.get())

    def test_dialog_reserves_space_for_controls_and_long_notice(self):
        self.controller.open()
        self.controller.notice.set("自动同步已暂停：两台电脑修改了同一条记录，请点击立即同步，逐条选择保留的版本。")
        self.root.update_idletasks()
        frame = self.controller.notice_label.master
        self.assertLessEqual(frame.winfo_reqheight(), self.controller.dialog.minsize()[1])
        self.assertGreater(self.controller.notice_label.winfo_reqheight(), 10)

    def test_corrupt_preferences_disable_network_on_restart(self):
        self.controller.settings_store.path.write_text('{"auto_sync":"yes"}')
        self.app.close()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = LoggerApp(self.root, ActivityService(Store(self.path), FixtureReader()))
        self.controller = self.app.sync_controller
        self.assertFalse(self.controller.settings.auto_sync)
        self.assertIsNone(self.controller.startup_timer)
        self.assertIn("无法读取", self.controller.notice.get())

    def test_close_cancels_callbacks_and_skips_late_import(self):
        self.controller.token = "test-only-token"
        self.peer.tasks.save(TaskDraft("关闭后远端内容", ""))
        self.publish_peer()
        self.fetch_release.clear()
        self.controller.start(automatic=True)
        self.assertTrue(self.fetch_entered.wait(2))
        with patch.object(self.app.service.sync, "apply") as apply:
            self.controller.close()
            self.fetch_release.set()
            self.controller.future.result(timeout=3)
            self.root.update()
            apply.assert_not_called()
        self.assertIsNone(self.controller.timer)
        self.assertIsNone(self.controller.status_timer)
        self.assertIsNone(self.controller.startup_timer)
        self.assertEqual(self.controller.token, "")
