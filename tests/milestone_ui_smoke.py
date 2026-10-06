"""Stage titles, folds, checkbox completion and guarded inline drafts."""
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
from unittest.mock import patch
from activitylog.demo_project import create_demo_plan
from activitylog.models import Activity
from activitylog.projects import ProjectDraft
from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.ui.app import LoggerApp

class Reader:
    def is_locked(self): return False
    def read(self): return Activity('fixture.exe', '测试', -1)

def main():
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk()
        root.withdraw()
        failures = []
        root.report_callback_exception = lambda kind, error, trace: failures.append(error)
        service = ActivityService(Store(Path(directory) / 'test.sqlite3'), Reader())
        project = create_demo_plan(service.projects)
        assert create_demo_plan(service.projects) == project
        app = LoggerApp(root, service)
        try:
            app.select_page('projects')
            panel = app.projects_panel
            assert len(panel.rows) == 10 and len(panel.stages) == 3
            stage = panel.milestones[0]
            body = panel.stages[stage.id][2]
            fold = body.master.winfo_children()[0].winfo_children()[0]
            fold.invoke()
            assert not body.winfo_manager()
            fold.invoke()
            assert body.winfo_manager()
            panel.stages[stage.id][1].set('新的阶段标题')
            assert panel.save_stage(stage.id)
            assert service.projects.milestones(project)[0].acceptance == stage.acceptance
            assert all(child.winfo_class() != 'TEntry' for child in body.winfo_children())
            identifier = next(t.id for t in service.projects.items(project) if t.milestone_id == stage.id)
            row = panel.rows[identifier]
            row.title_var.set('')
            assert not row.save_fields()
            app.select_page('tasks')
            assert app.current_page == 'projects' and panel.error.get()
            row.title_var.set('有效标题')
            assert row.save_fields()
            row.toggle_notes()
            row.notes.insert('end', '保留失败草稿')
            with patch.object(service.tasks, 'update', side_effect=sqlite3.OperationalError('测试失败')):
                assert not row.save_notes()
                assert row.dirty() and '保留失败草稿' in row.notes.get('1.0', 'end-1c')
            assert row.save_notes() and not row.dirty()
            window = row.full_notes()
            assert window is not None and root.grab_current() == window
            window.destroy()
            for task in service.projects.items(project):
                if task.milestone_id == stage.id:
                    panel.rows[task.id].done.set(True)
                    panel.rows[task.id].complete()
            assert not service.projects.milestones(project)[0].completed_at
            assert not hasattr(panel, 'accept_stage')
            assert panel.stages[stage.id][3]['text'] == '3/3'
            service.tasks.complete(identifier, False)
            panel.refresh()
            assert not service.projects.milestones(project)[0].completed_at
            panel.quick_title.set('补充事项')
            panel.stage_combo.current(1)
            panel.add_task()
            added = panel.selected_task_id
            assert panel.rows[added].task.milestone_id == stage.id
            panel.rows[added].toggle_notes()
            panel.rows[added].notes.insert('end', '关闭前的笔记')
            panel.rows[added].queue_notes()
            assert panel.rows[added].timer is not None
            assert not failures, failures
        finally:
            app.close()
        with Store(Path(directory) / 'test.sqlite3') as reopened:
            assert reopened.db.execute('SELECT notes FROM tasks WHERE id=?', (added,)).fetchone()[0] == '关闭前的笔记'
    print('Milestone UI smoke passed: titles, folds, checkbox completion, drafts, save failure, navigation guard, full notes, legacy data preservation and close flush.')

if __name__ == '__main__': main()
