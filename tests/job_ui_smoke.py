"""Hidden-window application entry/history/table checks using temporary data."""

from pathlib import Path
import sys
import tempfile
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from activitylog.job_service import JobService
from activitylog.job_store import JobRepository
from activitylog.jobs import ApplicationDraft
from activitylog.models import Activity
from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.ui.app import LoggerApp
from activitylog.ui.jobs import ApplicationDialog


class Reader:
    def is_locked(self):
        return False

    def read(self):
        return Activity("fixture.exe", "测试活动", -1)


def current_dialog(root):
    return next(child for child in root.winfo_children() if isinstance(child, ApplicationDialog))


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ui.sqlite3"
        root = tk.Tk()
        root.withdraw()
        app = LoggerApp(root, ActivityService(Store(path), Reader()))
        try:
            app.toggle()
            timer = app.timer
            app.nav_buttons["jobs"].invoke()
            assert app.current_page == "jobs" and app.running and app.timer == timer
            panel = app.jobs_panel
            panel.add_button.invoke()
            dialog = current_dialog(root)
            assert str(dialog.company_combo["state"]) == "normal"
            assert str(dialog.title_combo["state"]) == "normal"
            dialog.company_var.set("测试甲公司")
            dialog.title_var.set("Python 开发")
            dialog.date_var.set("错误日期")
            dialog.submit()
            assert "投递日期" in dialog.error.get()
            assert panel.service.snapshot().groups == ()
            dialog.date_var.set("2026-10-04")
            dialog.url_var.set("https://example.com/jobs/1")
            dialog.notes.insert("1.0", "已投简历\n准备技术面试")
            dialog.submit()
            first = panel._selected().application
            assert len(panel.table.get_children()) == 1
            assert panel.table.item(f"job-{first.id}", "values")[0] == "测试甲公司"
            assert "1 家公司" in panel.summary.get()
            dialog = panel.add_application()
            assert tuple(dialog.company_combo["values"]) == ("测试甲公司",)
            assert tuple(dialog.title_combo["values"]) == ("Python 开发",)
            dialog.company_combo.current(0)
            dialog.title_combo.current(0)
            dialog.title_var.set("后端工程师")
            dialog.status_var.set("面试中")
            dialog.submit()
            assert len(panel.table.get_children()) == 2
            assert "1 家公司" in panel.summary.get() and "2 个岗位" in panel.summary.get()
            dialog = panel.add_application()
            dialog.company_var.set("测试乙公司")
            dialog.title_combo.current(0)
            dialog.submit()
            third = panel._selected().application
            assert "2 家公司" in panel.summary.get() and "3 个岗位" in panel.summary.get()
            panel.table.selection_set(f"job-{first.id}")
            panel._selection_changed()
            panel.edit_button.invoke()
            dialog = current_dialog(root)
            assert dialog.company_var.get() == "测试甲公司"
            assert set(dialog.company_combo["values"]) == {"测试甲公司", "测试乙公司"}
            dialog.company_var.set("测试乙公司")
            dialog.status_var.set("已获 Offer")
            dialog.submit()
            assert "Offer 1" in panel.summary.get()
            assert panel.table.item(f"job-{first.id}", "values")[0] == "测试乙公司"
            panel.keyword.set("测试乙公司")
            panel.status_filter.set("已获 Offer")
            panel.refresh()
            assert len(panel.table.get_children()) == 1
            assert "3 个岗位" in panel.summary.get()
            panel.clear_filters()
            panel.table.selection_set(f"job-{first.id}")
            panel._selection_changed()
            with patch("activitylog.ui.jobs.webbrowser.open") as browser:
                panel.link_button.invoke()
                browser.assert_called_once_with(first.url)
            panel.table.selection_set(f"job-{third.id}")
            panel._selection_changed()
            with patch("activitylog.ui.jobs.messagebox.askyesno", return_value=False):
                panel.delete_button.invoke()
            assert len(panel.table.get_children()) == 3
            with patch("activitylog.ui.jobs.messagebox.askyesno", return_value=True):
                panel.delete_button.invoke()
            assert len(panel.table.get_children()) == 2
            # A large list uses the same single table, with one row per application.
            for index in range(30):
                panel.service.save_application(f"列表测试公司{index}", ApplicationDraft("开发", "2026-10-04"))
            panel.refresh()
            assert len(panel.table.get_children()) == 32
            assert panel.table["columns"] == ("company", "title", "date", "status", "url", "notes")
            assert "32 个岗位" in panel.summary.get()
            dialog = panel.add_application()
            assert "Python 开发" in dialog.title_combo["values"]
            assert len(dialog.company_combo["values"]) == 32
            dialog.destroy()
            app.nav_buttons["records"].invoke()
            assert app.running and len(app.table.get_children()) == 1
            app.toggle()
        finally:
            app.close()
        with Store(path) as store:
            service = JobService(JobRepository(store.db))
            assert service.snapshot().summary.applications == 32
            assert service.snapshot().summary.offers == 1
            assert "Python 开发" in service.history().titles
            assert len(store.rows()) == 1
    print("Job UI smoke OK: direct entry, company/title dropdown history, company changes, compact table, search, delete, persistence.")


if __name__ == "__main__":
    main()
