"""Hidden-window task flows with fixture data; never records the real desktop."""

from datetime import date
from pathlib import Path
import sqlite3
import sys
import tempfile
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from activitylog.models import Activity
from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.task_service import TaskService
from activitylog.task_store import TaskRepository
from activitylog.tasks import TaskDraft
from activitylog.projects import ProjectDraft, MilestoneDraft
from activitylog.project_store import ProjectRepository
from activitylog.project_service import ProjectService
from activitylog.ui.app import LoggerApp
from activitylog.ui.tasks import TaskDialog


class Reader:
    def is_locked(self):
        return False

    def read(self):
        return Activity("fixture.exe", "测试事项界面", -1)


def check_compact_editor():
    with Store(':memory:') as store:
        root = tk.Tk()
        root.withdraw()
        failures = []
        root.report_callback_exception = lambda kind, error, trace: failures.append(error)
        tasks = TaskService(TaskRepository(store.db), today=lambda: date(2026, 10, 6))
        projects = ProjectService(ProjectRepository(store.db), tasks)
        project = projects.save(ProjectDraft('原项目'))
        other = projects.save(ProjectDraft('新项目'))
        stage = projects.save_milestone(project, MilestoneDraft('原阶段', '旧条件'))
        identifier = tasks.save(TaskDraft('旧事项', '2026-10-08', priority='紧急', kind='问题', status='受阻', project_id=project, milestone_id=stage, acceptance='保留验收', outcome='保留成果'), in_today=True)
        tasks.complete(identifier, True)
        original = tasks.get(identifier)
        try:
            dialog = TaskDialog(root, tasks, lambda _: None, None, task=original)
            dialog.notes.insert('1.0', '新的备注')
            dialog.submit()
            saved = tasks.get(identifier)
            for field in ('priority', 'kind', 'status', 'milestone_id', 'acceptance', 'outcome', 'completed_at', 'resume_status'):
                assert getattr(saved, field) == getattr(original, field), field
            assert len(projects.completion_records(project)) == 1 and tasks.is_in_today(identifier)
            dialog = TaskDialog(root, tasks, lambda _: None, None, task=saved)
            dialog.project_combo.current(next(i+1 for i, p in enumerate(dialog.projects) if p.id == other))
            dialog.submit()
            assert tasks.get(identifier).milestone_id is None
            assert tasks.get(identifier).status == '已完成'

            dialog = TaskDialog(root, tasks, lambda _: None, None)
            dialog.title_var.set('日期验证')
            dialog.range_end_var.set('2026-10-08')
            dialog.submit()
            assert '开始日期' in dialog.error.get() and store.db.execute('SELECT count(*) FROM tasks').fetchone()[0] == 1
            dialog.date_var.set('2026-10-09')
            dialog.submit()
            assert dialog.error.get() and dialog.winfo_exists()
            dialog.date_var.set('2028-02-01')
            dialog.range_end_var.set('')
            picker = dialog.end_field.open_picker()
            assert (picker.year, picker.month) == (2028, 2)
            picker.destroy()
            assert root.grab_current() == dialog
            picker = dialog.start_field.open_picker()
            next(child for child in picker.days.winfo_children() if child.winfo_class() == 'TButton' and child['text'] == '29').invoke()
            assert dialog.date_var.get() == '2028-02-29' and root.grab_current() == dialog
            dialog.date_var.set('2026-10-06')
            dialog.range_end_var.set('2026-10-08')
            added = []
            dialog.on_saved = added.append
            dialog.submit()
            ranged = tasks.get(added[0])
            assert ranged.range_end == date(2026, 10, 8) and tasks.is_in_today(ranged.id)
            tasks.remove_today(ranged.id)
            dialog = TaskDialog(root, tasks, lambda _: None, None, task=tasks.get(ranged.id))
            dialog.notes.insert('1.0', '跳过当天仍保留')
            dialog.submit()
            assert not tasks.is_in_today(ranged.id)
            dialog = TaskDialog(root, tasks, lambda _: None, None)
            dialog.title_var.set('待安排事项')
            added = []
            dialog.on_saved = added.append
            dialog.submit()
            assert tasks.get(added[0]).planned_on is None and not tasks.is_in_today(added[0])
            assert not failures, failures
        finally:
            root.destroy()


def main():
    check_compact_editor()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ui.sqlite3"
        root = tk.Tk()
        root.withdraw()
        today = [date(2026, 10, 4)]
        service = ActivityService(Store(path), Reader())
        service.tasks = TaskService(TaskRepository(service.store.db), today=lambda: today[0])
        app = LoggerApp(root, service)
        try:
            app.toggle()
            timer = app.timer
            app.nav_buttons["tasks"].invoke()
            panel = app.tasks_panel
            assert app.current_page == "tasks" and app.running and app.timer == timer
            assert panel.month_text.get() == "2026年 10月"
            assert len(panel.calendar.days) == 35
            assert len(panel.table.get_children()) == 0
            assert "剩余 0 项" in panel.today_count.get()

            dialog = panel.add_task()
            assert isinstance(dialog, TaskDialog)
            labels = [child['text'] for child in dialog.title_entry.master.winfo_children() if child.winfo_class() == 'TLabel']
            for removed in ('里程碑', '类型', '优先级', '状态', '加入今日待办', '验收条件', '成果说明'):
                assert removed not in labels
            picker = dialog.start_field.open_picker()
            assert root.grab_current() == picker
            picker.move(1)
            assert (picker.year, picker.month) == (2026, 11)
            picker.choose(date(2026, 10, 6))
            assert dialog.date_var.get() == '2026-10-06' and root.grab_current() == dialog
            picker = dialog.end_field.open_picker()
            picker.choose(None)
            assert dialog.range_end_var.get() == '' and root.grab_current() == dialog
            root.update_idletasks()
            assert dialog.start_field.winfo_y() == dialog.end_field.winfo_y()
            assert dialog.winfo_reqheight() < 480
            dialog.title_var.set("修改简历")
            dialog.date_var.set("无效日期")
            dialog.submit()
            assert "安排日期" in dialog.error.get() and service.tasks.repository.count() == 0
            dialog.date_var.set("2026-10-06")
            dialog.category_var.set("求职")
            dialog.notes.insert("1.0", "检查项目介绍\n导出 PDF")
            dialog.submit()
            first = panel._selected()
            assert first.title == "修改简历" and first.category == "求职"
            assert first.range_start == first.range_end == date(2026, 10, 6)
            dialog = panel.edit_task()
            assert dialog.range_end_var.get() == ''
            dialog.destroy()
            assert panel.selected_date == date(2026, 10, 6)
            assert len(panel.today_list.checks) == 0
            panel.arrange_button.invoke()
            assert len(panel.today_list.checks) == 1
            assert first.id in panel.today_list.checks
            assert str(panel.arrange_button["state"]) == "disabled"
            variable, check = panel.today_list.checks[first.id]
            check.invoke()
            assert panel._selected().completed
            assert panel.today_list.checks[first.id][0].get()
            assert panel.table.item(f"task-{first.id}", "values")[0] == "☑"
            assert "已完成 1 / 1" in panel.today_count.get()
            panel.toggle_selected()
            assert not panel.today_list.checks[first.id][0].get()

            panel.move_month(1)
            assert panel.month_text.get() == "2026年 11月"
            assert "10/04" in panel.today_text.get() and len(panel.today_list.checks) == 1
            panel.remove_today(first.id)
            assert len(panel.today_list.checks) == 0 and service.tasks.get(first.id).title == "修改简历"
            panel.select_date(date(2026, 10, 6))
            panel.table.selection_set(f"task-{first.id}")
            panel._selection_changed()
            service.tasks.arrange_today(first.id)
            dialog = panel.edit_task()
            assert dialog.notes.get("1.0", "end-1c") == "检查项目介绍\n导出 PDF"
            dialog.title_var.set("修改简历第二版")
            dialog.date_var.set("2026-12-02")
            dialog.submit()
            assert panel.month_text.get() == "2026年 12月"
            assert panel._selected().title == "修改简历第二版"
            assert len(panel.today_list.checks) == 1

            # Failure restores the checkbox, leaves fields saved, and does not pause capture.
            with patch.object(service.tasks, "complete", side_effect=sqlite3.OperationalError("测试写入失败")):
                panel.today_list.checks[first.id][1].invoke()
            assert not panel.today_list.checks[first.id][0].get()
            assert panel.error.get() == "测试写入失败" and app.running

            panel.quick_title.set("跑步 30 分钟")
            panel.quick_button.invoke()
            second = panel._selected()
            from activitylog.ui.task_colors import task_color
            assert task_color(first) != task_color(second)
            assert second.planned_on == today[0]
            assert second.id in panel.today_list.checks and panel.quick_title.get() == ""
            with patch("activitylog.ui.tasks.messagebox.askyesno", return_value=False):
                panel.delete_button.invoke()
            assert service.tasks.repository.count() == 2
            with patch("activitylog.ui.tasks.messagebox.askyesno", return_value=True):
                panel.delete_button.invoke()
            assert service.tasks.repository.count() == 1 and second.id not in panel.today_list.checks

            for index in range(40):
                service.tasks.save(TaskDraft(f"批量测试事项 {index}", "2026-10-04"), in_today=True)
            panel.go_today()
            root.update_idletasks()
            assert len(panel.table.get_children()) == 40
            assert len(panel.today_list.checks) == 41
            assert len(panel.calendar.by_day[date(2026, 10, 4)]) == 40
            assert len(panel.today_list.labels) == 41
            assert any("项" in panel.calendar.itemcget(item, "text")
                       for item in panel.calendar.find_all() if panel.calendar.type(item) == "text")
            root.geometry("1100x700")
            root.update_idletasks()
            assert panel.calendar.winfo_width() >= 400
            assert panel.today_list.canvas.winfo_width() >= 200
            # Calendar day clicks and arrow navigation also update the dated detail list.
            from types import SimpleNamespace
            day_index = panel.calendar.days.index(date(2026, 10, 6))
            row, column = divmod(day_index, 7)
            width, height = panel.calendar._geometry()
            panel.calendar._click(SimpleNamespace(x=(column + .5) * width, y=28 + (row + .5) * height))
            assert panel.selected_date == date(2026, 10, 6) and len(panel.table.get_children()) == 0
            panel.calendar._move_selection(-2)
            assert panel.selected_date == date(2026, 10, 4) and len(panel.table.get_children()) == 40
            root.geometry("1440x880")
            root.update_idletasks()

            # Midnight updates the right list while the selected calendar date stays fixed.
            today[0] = date(2026, 10, 5)
            panel.after_cancel(panel.day_timer)
            panel.day_timer = None
            panel._check_day()
            assert panel.selected_date == date(2026, 10, 4)
            assert "10/05" in panel.today_text.get() and len(panel.today_list.checks) == 0
            panel.move_month(2)
            assert panel.month == 12
            panel.move_month(1)
            assert (panel.year, panel.month) == (2027, 1)
            panel.move_month(-1)
            assert (panel.year, panel.month) == (2026, 12)
            app.nav_buttons["jobs"].invoke()
            app.nav_buttons["records"].invoke()
            assert app.running and len(app.table.get_children()) == 1
        finally:
            app.close()

        with Store(path) as store:
            tasks = TaskService(TaskRepository(store.db), today=lambda: date(2026, 10, 4))
            assert tasks.get(first.id).notes == "检查项目介绍\n导出 PDF"
            assert len(tasks.snapshot(2026, 12, date(2026, 12, 2)).today_tasks) == 41
            assert len(store.rows()) == 1
        print("Task UI smoke passed: calendar, editing, shared completion, dated today list, restart and navigation.")


if __name__ == "__main__":
    main()
