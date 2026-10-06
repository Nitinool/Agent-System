"""Fixture-only checks for grouped navigation, inline editing and daily ranges."""
from datetime import date
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch
from activitylog.models import Activity
from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.task_service import TaskService
from activitylog.task_store import TaskRepository
from activitylog.project_service import ProjectService
from activitylog.project_store import ProjectRepository
from activitylog.ui.app import LoggerApp

class Reader:
    def is_locked(self): return False
    def read(self): return Activity('fixture.exe', '测试', -1)

def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'ui.sqlite3'
        root = tk.Tk()
        root.withdraw()
        failures = []
        root.report_callback_exception = lambda kind, error, trace: failures.append(error)
        service = ActivityService(Store(path), Reader())
        service.tasks = TaskService(TaskRepository(service.store.db), today=lambda: date(2026, 10, 6))
        service.projects = ProjectService(ProjectRepository(service.store.db), service.tasks)
        app = LoggerApp(root, service)
        try:
            app.toggle()
            app.select_page('projects')
            panel = app.projects_panel
            assert len(panel.project_table.get_children()) == 3
            dialog = panel.add_project()
            dialog.submit()
            assert dialog.error.get() and not service.projects.summaries()
            dialog.name_var.set('界面项目')
            dialog.priority_var.set('高')
            dialog.submit()
            project = panel.project.id
            code = panel.project.code
            assert panel.project_table.parent(f'project-{project}') == 'group-Active'
            # Check the mapped window: geometry alone misses a frame covering the tree.
            root.deiconify()
            root.attributes('-topmost', True)
            try:
                for size in ('1440x880', '1100x700'):
                    root.geometry(size + '+0+0')
                    for page in ('tasks', 'projects', 'finance', 'projects'):
                        app.select_page(page)
                        root.lift()
                        root.update()
                        if page != 'projects':
                            continue
                        table = panel.project_table
                        for item in ('group-Active', f'project-{project}'):
                            x, y, width, height = table.bbox(item)
                            hit = root.winfo_containing(
                                table.winfo_rootx() + x + width // 2,
                                table.winfo_rooty() + y + height // 2,
                            )
                            assert hit == table, f'Project navigation is covered by {hit}'
            finally:
                root.attributes('-topmost', False)
                root.withdraw()
            panel.mode.set('探索型')
            assert panel.save_project_fields()
            assert '累计完成 0 次' in panel.progress.get()
            assert panel.exploration_bar.itemcget(panel.exploration_fill, 'fill') == '#ffffff'
            panel.mode.set('目标型')
            assert panel.save_project_fields()
            panel.lane.set('Planning')
            panel.change_lane()
            assert panel.project_table.parent(f'project-{project}') == 'group-Planning'
            panel.lane.set('Active')
            panel.change_lane()
            panel.add_stage()
            stage = panel.milestones[0].id
            panel.stages[stage][1].set('开发阶段')
            assert panel.save_stage(stage)
            panel.quick_title.set('开发功能')
            panel.add_task()
            task = panel.selected_task_id
            row = panel.rows[task]
            assert row.task.milestone_id == stage
            combos = [child for child in row.title_entry.master.winfo_children() if child.winfo_class() == 'TCombobox']
            assert len(combos) == 1 and tuple(combos[0]['values']) == ('紧急', '高', '普通', '低')
            row.title_var.set('直接编辑名称')
            assert row.save_fields()
            row.toggle_notes()
            row.notes.insert('end', '可在页面直接编辑的笔记')
            assert panel.has_drafts() and app.sync_controller._editing()
            assert row.save_notes()
            assert service.tasks.get(task).notes == '可在页面直接编辑的笔记'
            row.toggle_notes()
            assert not row.note_frame.winfo_manager()
            panel.select_task(task)
            panel.preset('一周')
            assert service.tasks.get(task).range_end == date(2026, 10, 12)
            dialog = panel.rows[task].more_settings()
            assert dialog.range_end_var.get() == '2026-10-12'
            assert not dialog.acceptance.winfo_manager()
            labels = [child['text'] for child in dialog.title_entry.master.winfo_children() if child.winfo_class() == 'TLabel']
            assert '状态' not in labels and '验收条件' not in labels
            dialog.submit()
            assert service.tasks.get(task).range_end == date(2026, 10, 12)
            app.select_page('tasks')
            assert app.tasks_panel.today_list.checks[task][1]['text'].startswith('[' + code + ']')
            assert task in {t.id for t in app.tasks_panel.calendar.by_day[date(2026, 10, 7)]}
            app.select_page('projects')
            panel.rows[task].done.set(True)
            panel.rows[task].complete()
            assert not service.tasks.today_tasks()
            assert not hasattr(panel, 'accept_buttons')
            panel.undo_completion()
            assert service.tasks.is_in_today(task)
            panel.mode.set('探索型')
            assert panel.save_project_fields()
            assert not panel.progress_bar.winfo_manager() and panel.exploration_bar.winfo_manager() and '%' not in panel.progress.get()
            assert '累计完成 1 次' in panel.progress.get()
            first_color = panel.exploration_bar.itemcget(panel.exploration_fill, 'fill')
            panel.rows[task].done.set(True)
            panel.rows[task].complete()
            assert '累计完成 2 次' in panel.progress.get()
            second_color = panel.exploration_bar.itemcget(panel.exploration_fill, 'fill')
            assert int(second_color[1:3], 16) < int(first_color[1:3], 16)
            panel.rows[task].complete()
            assert '累计完成 2 次' in panel.progress.get()
            panel.undo_completion()
            assert '累计完成 2 次' in panel.progress.get()
            panel.refresh()
            assert panel.exploration_bar.itemcget(panel.exploration_fill, 'fill') == second_color
            panel.mode.set('目标型')
            panel.save_project_fields()
            assert panel.progress_bar.winfo_manager() and not panel.exploration_bar.winfo_manager()
            panel.select_task(task)
            panel.schedule_start.set('2026-11-01')
            panel.schedule_end.set('2026-11-10')
            assert panel.apply_schedule() and not service.tasks.is_in_today(task)
            panel.project_keyword.set('不存在')
            panel.apply_filters()
            assert panel.project is None and len(panel.project_table.get_children()) == 3
            panel.project_keyword.set(code.lower())
            panel.apply_filters()
            assert panel.project.id == project
            root.geometry('1100x700')
            root.update_idletasks()
            assert panel.canvas.winfo_width() >= 550
            assert panel.canvas.winfo_height() >= 400
            assert panel.schedule.winfo_height() < 65
            controls = panel.schedule.winfo_children()
            assert len({child.winfo_y() for child in controls if child.winfo_class() == 'TButton'}) == 1
            for child in controls:
                assert child.winfo_width() >= child.winfo_reqwidth()
                assert child.winfo_x() + child.winfo_width() <= panel.schedule.winfo_width()
            with patch('activitylog.ui.project_board.messagebox.askyesno', return_value=True):
                panel.delete_stage(stage)
            assert service.tasks.get(task).milestone_id is None
            with patch('activitylog.ui.project_board.messagebox.askyesno', return_value=True):
                panel.delete_project()
            assert service.tasks.get(task).project_id is None
            assert service.tasks.get(task).project_code == ''
            assert service.tasks.get(task).range_end == date(2026, 11, 10)
            assert app.running and not failures, failures
        finally:
            app.close()
        with Store(path) as reopened:
            saved = TaskRepository(reopened.db).get(task)
            assert saved.notes == '可在页面直接编辑的笔记' and saved.range_end == date(2026,11,10)
    print('Project UI smoke passed: lanes, priorities, inline fields/notes, ranges, project prefix, calendar, completion, layouts, deletions and restart.')

if __name__ == '__main__': main()
