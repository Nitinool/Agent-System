"""Hidden-window smoke check using temporary data; never captures desktop activity."""

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import sys
import tempfile
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from activitylog.models import Activity
from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.ui.app import LoggerApp


class FixtureReader:
    def is_locked(self):
        return False

    def read(self):
        return Activity("chrome.exe", "界面验证 · 测试页面", -1)


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk()
        root.withdraw()
        app = None
        path = Path(directory) / "ui.sqlite3"
        try:
            app = LoggerApp(root, ActivityService(Store(path, recover=True), FixtureReader()))
            root.update_idletasks()
            assert not app.running
            assert len(app.table.get_children()) == 0
            app.toggle()
            assert app.running
            assert len(app.table.get_children()) == 1
            assert "浏览器" in app.summary.get()
            app.toggle()
            assert not app.running
            assert app.timer is None

            yesterday = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
            identifier = app.service.store.begin(Activity("Codex.exe", "历史记录", -2), yesterday)
            app.service.store.finish(identifier, yesterday + timedelta(seconds=10), 10)
            app.date_text.set(yesterday.date().isoformat())
            app.apply_date()
            assert app.selected_date == yesterday.date()
            assert len(app.table.get_children()) == 1
            assert "10 秒" in app.summary.get()
            assert "Codex" in app.summary.get()
            values = app.table.item(app.table.get_children()[0], "values")
            assert values[4] == "历史记录"
            start = yesterday + timedelta(minutes=5)
            video = Activity("chrome.exe", "合并视频", -1)
            identifier = app.service.store.begin(video, start)
            app.service.store.finish(identifier, start + timedelta(seconds=10), 10, "查看日志")
            identifier = app.service.store.begin(video, start + timedelta(seconds=20), resume_reason="查看日志")
            app.service.store.finish(identifier, start + timedelta(seconds=25), 5, "暂停记录")
            app.refresh()
            assert len(app.table.get_children()) == 2
            assert any("合并 2 段" in app.table.item(item, "values")[5] for item in app.table.get_children())
            assert "25 秒" in app.summary.get()
            merged_item = next(item for item in app.table.get_children()
                               if "合并 2 段" in app.table.item(item, "values")[5])
            app.table.selection_set(merged_item)
            app.assign_category.set("学习")
            app.classify_selection()
            assert app.charts.totals["学习"] == 15
            assert app.charts.totals["未分类"] == 10
            assert len(app.table.selection()) == 1
            assert app.table.item(app.table.selection()[0], "values")[6] == "学习"
            app.notebook.select(app.charts)
            root.update_idletasks()
            assert len(app.charts.timeline.find_withtag("activity-block")) == 3
            assert "60.0%" in app.charts.info.get()
            app.charts.choose("学习")
            assert app.notebook.select() == str(app.timeline_tab)
            assert len(app.table.get_children()) == 1
            app.filter_keyword.set("不存在的内容")
            app.refresh()
            assert len(app.table.get_children()) == 0
            assert app.charts.totals["学习"] == 15  # Charts always describe the entire day.
            app.clear_filters()
            assert len(app.table.get_children()) == 2
            app.merge_view.set(False)
            app.refresh()
            assert len(app.table.get_children()) == 3
            assert "25 秒" in app.summary.get()
            app.merge_view.set(True)
            app.refresh()
            assert len(app.table.get_children()) == 2
            app.move_day(1)
            assert app.selected_date == datetime.now().date()
            assert len(app.table.get_children()) == 1
            app.today()
            app.service.store.export(Path(directory) / "today.csv", app.selected_date)
        finally:
            if app is not None:
                app.close()
            else:
                root.destroy()
        connection = sqlite3.connect(path)
        try:
            assert connection.execute("SELECT count(*) FROM segments WHERE status='running'").fetchone()[0] == 0
        finally:
            connection.close()
    print("UI smoke OK: start/pause, dates, grouping, batch classification, filters, charts, export, close.")


if __name__ == "__main__":
    main()
