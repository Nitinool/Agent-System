"""Hidden-window checks for the complete milestone, feedback and editing flow."""

from datetime import date
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

from activitylog.models import Activity
from activitylog.demo_project import create_demo_plan
from activitylog.projects import MilestoneDraft, ProjectDraft
from activitylog.project_service import ProjectService
from activitylog.project_store import ProjectRepository
from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.task_service import TaskService
from activitylog.task_store import TaskRepository
from activitylog.tasks import TaskDraft
from activitylog.ui.app import LoggerApp


class Reader:
    def is_locked(self):
        return False

    def read(self):
        return Activity('fixture.exe', '测试窗口', -1)


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk()
        root.withdraw()
        service = ActivityService(Store(Path(directory) / 'test.sqlite3'), Reader())
        service.tasks = TaskService(TaskRepository(service.store.db), today=lambda: date(2026, 10, 4))
        service.projects = ProjectService(ProjectRepository(service.store.db), service.tasks)
        project = create_demo_plan(service.projects)
        assert create_demo_plan(service.projects) == project
        assert len(service.projects.items(project)) == 10
        app = LoggerApp(root, service)
        try:
            app.select_page('projects')
            panel = app.projects_panel
            stages = service.projects.milestones(project)
            assert panel.selected_milestone_id == stages[0].id
            assert len(panel.table.get_children()) == 3
            assert '0/3' in panel.stage_progress.get()
            assert str(panel.finish_stage_button['state']) == 'disabled'
            item = service.projects.items(project)[0]
            service.tasks.set_status(item.id, '受阻')
            service.tasks.arrange_today(item.id)
            panel.refresh(item_id=item.id)
            panel.toggle_selected()
            assert '1/3' in panel.stage_progress.get()
            assert panel.feedback.get().startswith('✓')
            assert str(panel.undo_button['state']) == 'normal'
            assert len(panel.history_table.get_children()) == 1
            assert service.tasks.get(item.id).completed_at
            panel.undo_button.invoke()
            assert service.tasks.get(item.id).status == '受阻'
            assert '0/3' in panel.stage_progress.get()
            assert '已重新打开' in panel.history_table.item(panel.history_table.get_children()[0], 'values')
            panel.keyword.set('找不到')
            panel._apply_filters()
            assert not panel.table.get_children() and '0/3' in panel.stage_progress.get()
            panel.clear_filters()
            for task in service.projects.items(project):
                if task.milestone_id == stages[0].id:
                    service.tasks.complete(task.id, True)
            panel.refresh()
            assert str(panel.finish_stage_button['state']) == 'normal'
            with patch('activitylog.ui.projects.messagebox.askyesno', return_value=True):
                panel.finish_stage_button.invoke()
            assert service.projects.milestones(project)[0].completed_at
            assert '里程碑已达成' in panel.feedback.get()
            service.tasks.save(TaskDraft('新的未来想法', '', project_id=project))
            panel.refresh()
            assert '3/3' in panel.stage_progress.get() and len(panel.backlog_table.get_children()) == 3

            dialog = panel.add_item()
            assert dialog.milestone_combo.current() == 1
            dialog.title_var.set('补充验收')
            dialog.acceptance.insert('1.0', '完整条件' * 300)
            dialog.outcome.insert('1.0', '成果说明' * 1000)
            dialog.submit()
            added = panel._selected()
            assert added.milestone_id == stages[0].id
            assert len(panel.detail.get()) < 380
            assert not service.projects.milestones(project)[0].completed_at
            dialog = panel.edit_item()
            assert dialog.acceptance.get('1.0', 'end-1c') == added.acceptance
            assert dialog.outcome.get('1.0', 'end-1c') == added.outcome
            other = service.projects.save(ProjectDraft('另一项目'))
            other_stage = service.projects.save_milestone(other, MilestoneDraft('其他阶段'))
            dialog.destroy()
            dialog = panel.edit_item()
            dialog.project_combo.current(next(i+1 for i, p in enumerate(dialog.projects) if p.id == other))
            dialog._project_changed()
            assert dialog.milestone_combo.current() == 0
            dialog.milestone_combo.current(1)
            dialog.submit()
            assert panel.selected_project_id == other
            assert panel._selected().milestone_id == other_stage
            panel.show_history.set(True)
            panel._toggle_history()
            panel.show_backlog.set(True)
            panel._toggle_backlog()
            root.geometry('1100x700')
            root.update_idletasks()
            assert panel.table.winfo_width() >= 550
            assert panel.table.winfo_height() >= 65

            app.select_page('tasks')
            assert service.tasks.is_in_today(item.id)
            app.tasks_panel.today_list.checks[item.id][1].invoke()
            app.select_page('projects')
            panel.refresh(project)
            assert '2/3' in panel.stage_progress.get()
            assert not service.projects.milestones(project)[0].completed_at
            dialog = panel.add_milestone()
            dialog.name_var.set('下一轮')
            dialog.submit()
            assert panel._milestone().name == '下一轮'
            dialog = panel.edit_milestone()
            dialog.acceptance.insert('1.0', '可核对的成果')
            dialog.submit()
            assert panel._milestone().acceptance == '可核对的成果'
            with patch('activitylog.ui.projects.messagebox.askyesno', return_value=True):
                panel.delete_milestone()
            assert len(service.projects.milestones(project)) == 3
        finally:
            app.close()
    print('Milestone UI smoke passed: stage progress, feedback, undo, history, backlog, editors and shared calendar/today.')


if __name__ == '__main__':
    main()
