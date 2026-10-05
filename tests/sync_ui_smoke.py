"""Hidden Tk two-device sync flow; no real credentials, network or user database."""

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from activitylog.jobs import ApplicationDraft
from activitylog.projects import ProjectDraft
from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.sync import Conflict, decode, encode
from activitylog.tasks import TaskDraft
from activitylog.ui.app import LoggerApp
from activitylog.ui.sync import resolve_conflict, version_text
from tests.ui_smoke import FixtureReader


def wait(root, controller):
    deadline = time.monotonic() + 6
    while controller.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert not controller.busy, "Sync worker failed to finish"
    assert controller.notice.get().startswith("同步完成"), controller.notice.get()


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk()
        root.withdraw()
        a = LoggerApp(root, ActivityService(Store(Path(directory) / "a.sqlite3"), FixtureReader()))
        other_root = tk.Toplevel(root)
        other_root.withdraw()
        b = LoggerApp(other_root, ActivityService(Store(Path(directory) / "b.sqlite3"), FixtureReader()))
        shared = {}
        worker_ids = []

        class Transport:
            def __init__(self, _token):
                pass

            def fetch(self):
                worker_ids.append(threading.get_ident())
                return deepcopy(shared), None

            def publish(self, records, _sha):
                worker_ids.append(threading.get_ident())
                shared.clear()
                shared.update(decode(encode(records)))

        def synchronize(app):
            controller = app.sync_controller
            controller.open()
            controller.token_var.set("test-only-token")
            controller.remember.set(False)
            controller.start()
            assert controller.busy
            assert str(controller.sync_button["state"]) == "disabled"
            wait(root, controller)
            assert "待同步 0 条" in controller.status.get()
            assert str(controller.sync_button["state"]) == "normal"
            assert controller.token_var.get() == ""

        try:
            with patch("activitylog.ui.sync.GitHubSync", Transport):
                p = a.service.projects.save(ProjectDraft("界面项目"))
                t = a.service.tasks.save(TaskDraft("测试事项", "", project_id=p))
                a.service.jobs.save_application("界面公司", ApplicationDraft("测试岗位", "2026-10-05"))
                a.toggle()
                synchronize(a)
                assert a.running
                synchronize(b)
                assert len(b.jobs_panel.table.get_children()) == 1
                assert len(b.projects_panel.project_table.get_children()) == 1
                bt = b.service.tasks.repository.unscheduled()[0].id
                b.service.tasks.complete(bt, True)
                synchronize(b)
                synchronize(a)
                assert a.service.tasks.get(t).completed
                a.service.tasks.save(TaskDraft("本机标题", "", project_id=p), t)
                b.service.tasks.save(TaskDraft("远端标题", "", project_id=b.service.tasks.get(bt).project_id), bt)
                synchronize(b)
                with patch("activitylog.ui.sync.resolve_conflict", return_value="local") as resolver:
                    synchronize(a)
                    resolver.assert_called_once()
                synchronize(b)
                assert b.service.tasks.get(bt).title == "本机标题"
                assert all(identifier != threading.get_ident() for identifier in worker_ids)
                records = a.service.sync.snapshot()
                uid = next(uid for uid, r in records.items() if r["kind"] == "tasks")
                conflict = Conflict(uid, None, records[uid], {"kind": "tasks", "fields": None})
                text = version_text(conflict.local, records)
                assert "所属项目：界面项目" in text
                assert uid not in text

                def choose_remote():
                    def visit(widget):
                        if isinstance(widget, ttk.Button) and widget.cget("text") == "保留远端":
                            widget.invoke()
                            return True
                        return any(visit(child) for child in widget.winfo_children())
                    assert visit(a.sync_controller.dialog)
                root.after(100, choose_remote)
                assert resolve_conflict(a.sync_controller.dialog, conflict, records) == "remote"
                a.sync_controller._close_dialog()
                assert a.sync_controller.status_timer is None
        finally:
            b.close()
            a.close()
    print("Sync UI smoke passed: two-device sync, real worker threads, refresh, conflict choice and continued capture.")


if __name__ == "__main__":
    main()
