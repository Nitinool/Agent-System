"""Compact shared task editor; hidden legacy fields are preserved on save."""
import sqlite3
import tkinter as tk
from tkinter import ttk

from ..tasks import TASK_CATEGORIES, TaskDraft
from .date_picker import DateField


class TaskDialog(tk.Toplevel):
    def __init__(self, parent, service, on_saved, selected, task=None, in_today=False, project_id=None, milestone_id=None):
        projects = service.projects()
        super().__init__(parent)
        self.title('编辑事项' if task else '新增事项')
        self.transient(parent)
        self.resizable(False, False)
        self.service, self.on_saved = service, on_saved
        self.identifier = task.id if task else None
        self.initial_project = task.project_id if task else project_id
        self.initial_milestone = task.milestone_id if task else milestone_id
        planned = (task.range_start or task.planned_on) if task else selected
        end = task.range_end if task and task.range_end != planned else None
        self.title_var = tk.StringVar(value=task.title if task else '')
        self.date_var = tk.StringVar(value=planned.isoformat() if planned else '')
        self.range_end_var = tk.StringVar(value=end.isoformat() if end else '')
        self.category_var = tk.StringVar(value=task.category if task else '其他')
        self.error = tk.StringVar()
        self.projects = projects
        body = ttk.Frame(self, padding=16)
        body.pack(fill='both', expand=True)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text='事项名称 *').grid(row=0, column=0, sticky='w', padx=(0, 12), pady=6)
        self.title_entry = ttk.Entry(body, textvariable=self.title_var, width=46)
        self.title_entry.grid(row=0, column=1, sticky='ew', pady=6)
        ttk.Label(body, text='安排日期').grid(row=1, column=0, sticky='nw', padx=(0, 12), pady=6)
        dates = ttk.Frame(body)
        dates.grid(row=1, column=1, sticky='ew', pady=6)
        dates.columnconfigure((0, 2), weight=1)
        ttk.Label(dates, text='开始日期').grid(row=0, column=0, sticky='w')
        ttk.Label(dates, text='结束日期（可选）').grid(row=0, column=2, sticky='w')
        self.start_field = DateField(dates, self.date_var, service.today)
        self.start_field.grid(row=1, column=0, sticky='ew', pady=4)
        ttk.Label(dates, text=' 至 ').grid(row=1, column=1, padx=4)
        self.end_field = DateField(dates, self.range_end_var, service.today, self.date_var)
        self.end_field.grid(row=1, column=2, sticky='ew', pady=4)
        ttk.Label(dates, text='结束日期留空表示单日；两项留空表示待安排', foreground='#667085').grid(row=2, column=0, columnspan=3, sticky='w')
        ttk.Label(body, text='所属项目').grid(row=2, column=0, sticky='w', pady=6)
        self.project_combo = ttk.Combobox(body, values=('不属于项目',) + tuple(p.name for p in projects), state='readonly')
        self.project_combo.grid(row=2, column=1, sticky='ew', pady=6)
        self.project_combo.current(next((i + 1 for i, p in enumerate(projects) if p.id == self.initial_project), 0))
        ttk.Label(body, text='分类').grid(row=3, column=0, sticky='w', pady=6)
        ttk.Combobox(body, textvariable=self.category_var, values=TASK_CATEGORIES, state='readonly', width=16).grid(row=3, column=1, sticky='w', pady=6)
        ttk.Label(body, text='备注').grid(row=4, column=0, sticky='nw', pady=6)
        self.notes = tk.Text(body, width=46, height=4, wrap='word', font=('Microsoft YaHei UI', 10))
        self.notes.grid(row=4, column=1, sticky='ew', pady=6)
        self.notes.insert('1.0', task.notes if task else '')
        ttk.Label(body, textvariable=self.error, foreground='#b42318', wraplength=470).grid(row=5, column=0, columnspan=2, sticky='w')
        actions = ttk.Frame(body)
        actions.grid(row=6, column=0, columnspan=2, sticky='ew', pady=(12, 0))
        ttk.Button(actions, text='保存', command=self.submit).pack(side='right')
        ttk.Button(actions, text='取消', command=self.destroy).pack(side='right', padx=8)
        self.bind('<Escape>', lambda _: self.destroy())
        self.grab_set()
        self.title_entry.focus_set()

    def _project_id(self):
        index = self.project_combo.current()
        return self.projects[index - 1].id if index > 0 else None

    def submit(self):
        try:
            existing = self.service.get(self.identifier) if self.identifier else None
            project_id = self._project_id()
            start, end = self.date_var.get().strip(), self.range_end_var.get().strip()
            if end and not start:
                raise ValueError('请先选择开始日期。')
            milestone = existing.milestone_id if existing else self.initial_milestone
            previous_project = existing.project_id if existing else self.initial_project
            # An omitted end is a one-day range, so future single dates also enter Today.
            draft = TaskDraft(
                title=self.title_var.get(), planned_on=start, category=self.category_var.get(),
                notes=self.notes.get('1.0', 'end-1c'), project_id=project_id,
                milestone_id=milestone if project_id == previous_project else None,
                priority=existing.priority if existing else '普通',
                kind=existing.kind if existing else '任务', status=existing.status if existing else None,
                acceptance=existing.acceptance if existing else '', outcome=existing.outcome if existing else '',
                range_start=start, range_end=(end or start),
            )
            identifier = self.service.save(draft, self.identifier, in_today=None)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.destroy()
        self.on_saved(identifier)
