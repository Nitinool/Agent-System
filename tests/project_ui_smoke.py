"""Hidden project/calendar/today flows on fixture data, with no real capture."""

from datetime import date
from pathlib import Path
import sqlite3
import sys
import tempfile
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from activitylog.models import Activity
from activitylog.project_service import ProjectService
from activitylog.project_store import ProjectRepository
from activitylog.projects import ProjectDraft
from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.task_service import TaskService
from activitylog.task_store import TaskRepository
from activitylog.tasks import TaskDraft
from activitylog.ui.app import LoggerApp
from activitylog.ui.projects import ProjectDialog
from activitylog.ui.task_editor import TaskDialog


class Reader:
    def is_locked(self):
        return False

    def read(self):
        return Activity("fixture.exe", "项目界面测试", -1)


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ui.sqlite3"
        root = tk.Tk()
        root.withdraw()
        service = ActivityService(Store(path), Reader())
        service.tasks = TaskService(TaskRepository(service.store.db), today=lambda: date(2026, 10, 4))
        service.projects = ProjectService(ProjectRepository(service.store.db), service.tasks)
        app = LoggerApp(root, service)
        try:
            app.toggle()
            timer = app.timer
            app.nav_buttons["projects"].invoke()
            panel = app.projects_panel
            assert app.current_page == "projects" and app.running and app.timer == timer
            assert not panel.project_table.get_children()
            assert str(panel.add_item_button["state"]) == "disabled"
            dialog = panel.add_project()
            assert isinstance(dialog, ProjectDialog)
            dialog.submit()
            assert dialog.error.get() and service.projects.summaries() == ()
            dialog.name_var.set("个人记录")
            dialog.goal.insert("1.0", "客观记录生活和时间分配")
            dialog.submit()
            first_project = panel.selected_project_id
            assert panel.project_name.get() == "个人记录"
            assert "0/0" in panel.progress.get()
            with patch.object(service.tasks, "projects", side_effect=sqlite3.OperationalError("项目列表不可读")):
                assert panel.add_item() is None
            assert panel.error.get() == "项目列表不可读"
            assert not any(isinstance(child, TaskDialog) for child in root.winfo_children())
            panel.refresh()

            dialog = panel.add_item()
            assert isinstance(dialog, TaskDialog)
            assert dialog.date_var.get() == "" and dialog.priority_var.get() == "普通"
            assert dialog.project_combo.get() == "个人记录"
            dialog.title_var.set("开发项目管理")
            dialog.kind_var.set("功能")
            dialog.priority_var.set("高")
            dialog.status_var.set("进行中")
            dialog.notes.insert("1.0", "共用事项数据\n优先级显示圆点")
            dialog.submit()
            task = panel._selected()
            identifier = task.id
            assert task.project_id == first_project and task.planned_on is None
            assert "0/1" in panel.progress.get()
            assert panel.table.item(f"task-{identifier}", "image")[0] == str(panel.dots.for_task(task))
            original_pixel = panel.dots.for_task(task).get(5, 5)
            panel.arrange_button.invoke()
            assert panel._selected().planned_on == date(2026, 10, 4)
            assert service.tasks.is_in_today(identifier)
            panel.toggle_selected()
            assert panel._selected().completed and "1/1" in panel.progress.get()
            assert panel.dots.for_task(panel._selected()).get(5, 5) != original_pixel

            app.nav_buttons["tasks"].invoke()
            calendar = app.tasks_panel
            assert identifier in calendar.today_list.checks
            assert calendar.table.item(f"task-{identifier}", "values")[3] == "已完成"
            calendar.today_list.checks[identifier][1].invoke()
            assert service.tasks.get(identifier).status == "进行中"
            app.nav_buttons["projects"].invoke()
            assert "0/1" in panel.progress.get()
            panel.table.selection_set(f"task-{identifier}")
            panel._selection_changed()
            panel.selected_status.set("受阻")
            panel.change_status()
            assert service.tasks.get(identifier).status == "受阻"
            with patch.object(service.tasks, "set_status", side_effect=sqlite3.OperationalError("测试保存失败")):
                panel.selected_status.set("已完成")
                panel.change_status()
            assert panel.selected_status.get() == "受阻" and panel.error.get() == "测试保存失败"
            assert app.running
            panel.keyword.set("圆点")
            panel.status_filter.set("受阻")
            panel._apply_filters()
            assert len(panel.table.get_children()) == 1
            panel.status_filter.set("已完成")
            panel._apply_filters()
            assert not panel.table.get_children() and "0/1" in panel.progress.get()
            panel.clear_filters()

            dialog = panel.edit_project()
            dialog.status_var.set("暂停")
            dialog.submit()
            assert "暂停" in panel.progress.get()
            dialog = panel.add_project()
            dialog.name_var.set("第二个项目")
            dialog.submit()
            second_project = panel.selected_project_id
            panel.project_table.selection_set(f"project-{first_project}")
            panel._project_selected(None)
            panel.table.selection_set(f"task-{identifier}")
            panel._selection_changed()
            dialog = panel.edit_item()
            assert dialog.notes.get("1.0", "end-1c") == "共用事项数据\n优先级显示圆点"
            assert dialog.status_var.get() == "受阻" and dialog.priority_var.get() == "高"
            dialog.priority_var.set("紧急")
            dialog.date_var.set("2026-11-02")
            dialog.project_combo.current(next(index + 1 for index, project in enumerate(dialog.projects)
                                               if project.id == second_project))
            dialog.submit()
            assert panel.selected_project_id == second_project
            assert panel._selected().priority == "紧急" and panel._selected().project_id == second_project
            app.nav_buttons["tasks"].invoke()
            calendar.select_date(date(2026, 11, 2))
            assert calendar.table.item(f"task-{identifier}", "values")[2] == "紧急"
            assert identifier in calendar.today_list.checks
            assert any(calendar.calendar.itemcget(item, "fill") == "#d92d20"
                       for item in calendar.calendar.find_all() if calendar.calendar.type(item) == "oval")
            app.nav_buttons["projects"].invoke()
            with patch("activitylog.ui.projects.messagebox.askyesno", return_value=False):
                panel.delete_project_button.invoke()
            assert len(service.projects.summaries()) == 2
            with patch("activitylog.ui.projects.messagebox.askyesno", return_value=True):
                panel.delete_project_button.invoke()
            assert len(service.projects.summaries()) == 1
            assert service.tasks.get(identifier).project_id is None
            assert service.tasks.is_in_today(identifier)

            dialog = panel.add_item()
            dialog.title_var.set("后续功能清单")
            dialog.submit()
            backlog = panel._selected().id
            app.nav_buttons["tasks"].invoke()
            calendar.select_unscheduled()
            assert f"task-{backlog}" in calendar.table.get_children()
            calendar.table.selection_set(f"task-{backlog}")
            calendar._selection_changed()
            calendar.arrange_button.invoke()
            assert calendar.selected_date == date(2026, 10, 4)
            assert not calendar.show_unscheduled and backlog in calendar.today_list.checks
            app.nav_buttons["projects"].invoke()
            panel.table.selection_set(f"task-{backlog}")
            panel._selection_changed()
            with patch("activitylog.ui.projects.messagebox.askyesno", return_value=True):
                panel.delete_item_button.invoke()
            assert backlog not in {item.id for item in service.tasks.today_tasks()}

            for index in range(35):
                service.projects.save(ProjectDraft(f"列表测试项目 {index}"))
            for index in range(40):
                service.tasks.save(TaskDraft(f"功能测试 {index}", "", project_id=first_project,
                                            priority=("紧急", "高", "普通", "低")[index % 4]))
            panel.refresh(first_project)
            assert len(panel.project_table.get_children()) == 36
            assert len(panel.table.get_children()) == 40 and "0/40" in panel.progress.get()
            pixels = {panel.dots.images[priority, False].get(5, 5) for priority in ("紧急", "高", "普通", "低")}
            assert len(pixels) == 4
            root.geometry("1100x700")
            root.update_idletasks()
            assert app.sidebar.winfo_width() <= 155
            assert all(button.winfo_height() < 50 for button in app.nav_buttons.values())
            assert panel.table.winfo_width() >= 550
            assert panel.project_table.winfo_width() <= 260
            app.nav_buttons["records"].invoke()
            assert app.running and len(app.table.get_children()) == 1
        finally:
            app.close()

        with Store(path) as reopened:
            tasks = TaskRepository(reopened.db)
            assert tasks.get(identifier).priority == "紧急" and tasks.get(identifier).status == "受阻"
            assert tasks.get(identifier).project_id is None
            assert len(tasks.day_tasks(date(2026, 10, 4))) == 1
            assert tasks.count() == 41 and len(reopened.rows()) == 1
        print("Project UI smoke passed: project CRUD, priority dots, shared tasks/calendar/today, status, filters, compact layout and restart.")


if __name__ == "__main__":
    main()
