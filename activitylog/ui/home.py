"""Daily dashboard with shared tasks, quick notes and masked finance totals."""

import sqlite3
import math
import tkinter as tk
from tkinter import ttk

from ..finance import money_text
from .app_time import AppTimeChart
from .task_editor import TaskDialog
from .today import TodayList


class TaskPicker(tk.Toplevel):
    def __init__(self, parent, service, on_saved):
        candidates = service.all_tasks()
        included = {t.id for t in service.today_tasks()}
        super().__init__(parent)
        self.title('从已有事项添加到今日')
        self.geometry('620x400')
        self.transient(parent)
        self.service, self.on_saved = service, on_saved
        self.tasks = {t.id: t for t in candidates if t.id not in included}
        self.keyword = tk.StringVar()
        self.error = tk.StringVar()
        body = ttk.Frame(self, padding=14)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='搜索名称、备注或项目编号').pack(anchor='w')
        entry = ttk.Entry(body, textvariable=self.keyword)
        entry.pack(fill='x', pady=(4, 10))
        container = ttk.Frame(body)
        container.pack(fill='both', expand=True)
        self.table = ttk.Treeview(container, columns=('title', 'day'), show='headings', selectmode='browse')
        self.table.heading('title', text='事项')
        self.table.column('title', width=420)
        self.table.heading('day', text='原安排日期')
        self.table.column('day', width=120, stretch=False)
        scroll = ttk.Scrollbar(container, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.table.bind('<Double-1>', lambda _: self.submit())
        self.table.bind('<Return>', lambda _: self.submit())
        ttk.Label(body, textvariable=self.error, foreground='#b42318').pack(anchor='w', pady=5)
        ttk.Button(body, text='添加到今日', command=self.submit).pack(anchor='e')
        self.keyword.trace_add('write', lambda *_: self.display())
        self.display()
        self.grab_set()
        entry.focus_set()

    def display(self):
        keyword = self.keyword.get().strip().casefold()
        self.table.delete(*self.table.get_children())
        for task in self.tasks.values():
            if keyword in f'{task.title}\n{task.notes}\n{task.project_code}'.casefold():
                title = f'[{task.project_code}] {task.title}' if task.project_code else task.title
                self.table.insert('', 'end', iid=str(task.id), values=(title, task.planned_on or '待安排'))

    def submit(self):
        selection = self.table.selection()
        if not selection:
            self.error.set('请选择要添加的事项。')
            return
        identifier = int(selection[0])
        try:
            self.service.arrange_today(identifier)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.destroy()
        self.on_saved(identifier)


class HomeOverview(ttk.Frame):
    def __init__(self, parent, service, on_change, navigate, on_project, on_toggle):
        super().__init__(parent, padding=16)
        self.service = service
        self.on_change, self.navigate, self.on_project = on_change, navigate, on_project
        self.snapshot = None
        self.day_timer = None
        self.project_rows = {}
        self.finance_visible = False
        for name in ('date_text', 'today_text', 'today_count', 'finance_title', 'income', 'expense',
                     'project_count', 'jobs_text', 'quick_title', 'error'):
            setattr(self, name, tk.StringVar())
        self.hide_completed = tk.BooleanVar(value=False)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        ttk.Label(header, text='每日信息', font=('Microsoft YaHei UI', 16, 'bold')).pack(side='left')
        ttk.Label(header, textvariable=self.date_text, foreground='#667085').pack(side='left', padx=16)
        self.content = ttk.Frame(self)
        self.content.grid(row=1, column=0, sticky='nsew')
        self.content.columnconfigure(0, weight=30, uniform='home')
        self.content.columnconfigure(1, weight=40, uniform='home')
        self.content.columnconfigure(2, weight=30, uniform='home')
        self.content.rowconfigure(1, weight=1)
        self.notes_panel = ttk.LabelFrame(self.content, text='随笔记录', padding=10)
        self.notes_panel.grid(row=0, column=0, rowspan=2, sticky='nsew', padx=(0, 10))
        self._build_notes()
        self.todo_panel = ttk.LabelFrame(self.content, text='今日待办', padding=10)
        self.todo_panel.grid(row=0, column=1, rowspan=2, sticky='nsew', padx=(0, 10))
        self._build_today()
        self.finance_panel = ttk.LabelFrame(self.content, text='当月财务', padding=10)
        self.finance_panel.grid(row=0, column=2, sticky='ew', pady=(0, 10))
        self._build_finance()
        self.projects_panel = ttk.LabelFrame(self.content, text='进行中的项目', padding=10)
        self.projects_panel.grid(row=1, column=2, sticky='nsew')
        self._build_projects()
        jobs = ttk.Frame(self.content)
        jobs.grid(row=2, column=0, columnspan=3, sticky='ew', pady=8)
        ttk.Button(jobs, text='求职一览', command=lambda: navigate('jobs')).pack(side='left')
        ttk.Label(jobs, textvariable=self.jobs_text, foreground='#667085').pack(side='left', padx=12)
        self.records_panel = ttk.Frame(self.content, padding=10, relief='solid', borderwidth=1)
        self.records_panel.grid(row=3, column=0, columnspan=3, sticky='ew')
        self.time_chart = AppTimeChart(self.records_panel)
        self.time_chart.pack(fill='both', expand=True)
        self.record_button = ttk.Button(self.time_chart.heading, text='开始记录', command=on_toggle)
        self.record_button.pack(side='right', padx=(8, 12))
        ttk.Button(self.time_chart.heading, text='查看记录', command=lambda: navigate('records')).pack(side='right')
        ttk.Label(self, textvariable=self.error, foreground='#b42318').grid(row=2, column=0, sticky='ew', pady=(4, 0))
        self.refresh()
        self.day_timer = self.after(30000, self._check_day)

    def _build_notes(self):
        self.note_title = tk.StringVar()
        self.note_error = tk.StringVar()
        quick = ttk.Frame(self.notes_panel)
        quick.pack(fill='x', pady=(0, 6))
        self.note_entry = ttk.Entry(quick, width=14, textvariable=self.note_title)
        self.note_entry.pack(side='left', fill='x', expand=True)
        self.note_entry.bind('<Return>', lambda _: self.add_note())
        self.note_button = ttk.Button(quick, text='确定', width=5, command=self.add_note)
        self.note_button.pack(side='right', padx=(6, 0))
        ttk.Label(self.notes_panel, textvariable=self.note_error, foreground='#b42318',
                  wraplength=220).pack(anchor='w')
        container = ttk.Frame(self.notes_panel)
        container.pack(fill='both', expand=True)
        self.note_table = ttk.Treeview(container, columns=('time', 'title'), show='headings', selectmode='browse', height=1)
        self.note_table.heading('time', text='时间')
        self.note_table.column('time', width=108, minwidth=108, stretch=False)
        self.note_table.heading('title', text='事件')
        self.note_table.column('title', width=90, minwidth=60)
        scroll = ttk.Scrollbar(container, orient='vertical', command=self.note_table.yview)
        self.note_table.configure(yscrollcommand=scroll.set)
        self.note_table.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.note_table.bind('<Double-1>', self.open_note)
        self.note_table.bind('<Return>', self.open_note)
        ttk.Label(self.notes_panel, text='最近 200 条 · 双击查看全文', foreground='#667085').pack(anchor='w', pady=(6, 0))
        self.note_rows = {}

    def refresh_notes(self):
        try:
            notes = self.service.notes.latest()
        except (ValueError, sqlite3.Error) as error:
            self.note_error.set(str(error))
            return
        selection = self.note_table.selection()
        position = self.note_table.yview()[0]
        self.note_table.delete(*self.note_table.get_children())
        self.note_rows = {str(note.id): note for note in notes}
        for note in notes:
            at = note.created_at.astimezone()
            self.note_table.insert('', 'end', iid=str(note.id),
                                   values=(at.strftime('%m/%d %H:%M:%S'), ' '.join(note.title.splitlines())))
        if selection and selection[0] in self.note_rows:
            self.note_table.selection_set(selection[0])
        self.note_table.yview_moveto(position)
        self.note_error.set('')

    def add_note(self):
        try:
            identifier = self.service.notes.add(self.note_title.get())
        except (ValueError, sqlite3.Error) as error:
            self.note_error.set(str(error))
            return
        self.note_title.set('')
        self.refresh_notes()
        if str(identifier) in self.note_rows:
            self.note_table.selection_set(str(identifier))
            self.note_table.see(str(identifier))
        self.note_entry.focus_set()

    def open_note(self, event=None):
        selection = self.note_table.selection()
        if not selection:
            return
        note = self.note_rows[selection[0]]
        dialog = tk.Toplevel(self)
        dialog.title('随笔记录')
        dialog.geometry('560x320')
        dialog.transient(self.winfo_toplevel())
        ttk.Label(dialog, text=note.created_at.astimezone().strftime('%Y/%m/%d %H:%M:%S'), padding=12).pack(anchor='w')
        body = ttk.Frame(dialog, padding=(12, 0, 12, 12))
        body.pack(fill='both', expand=True)
        text = tk.Text(body, wrap='word', width=1, height=1)
        scroll = ttk.Scrollbar(body, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        text.insert('1.0', note.title)
        text.configure(state='disabled')
        dialog.bind('<Escape>', lambda _: dialog.destroy())
        return dialog

    def _build_today(self):
        parent = self.todo_panel
        ttk.Label(parent, textvariable=self.today_text, foreground='#667085').pack(anchor='w', pady=(0, 6))
        quick = ttk.Frame(parent)
        quick.pack(fill='x', pady=(0, 6))
        self.quick_entry = ttk.Entry(quick, width=16, textvariable=self.quick_title)
        self.quick_entry.pack(side='left', fill='x', expand=True)
        self.quick_entry.bind('<Return>', lambda _: self.add_today())
        self.quick_button = ttk.Button(quick, text='＋', width=3, command=self.add_today)
        self.quick_button.pack(side='left', padx=(6, 0))
        actions = ttk.Frame(parent)
        actions.pack(fill='x', pady=(0, 8))
        ttk.Button(actions, text='新增事项…', command=self.add_task).pack(side='left')
        ttk.Button(actions, text='从已有事项添加…', command=self.choose_task).pack(side='left', padx=6)
        self.today_list = TodayList(parent, self.complete_task, self.edit_task, self.remove_today)
        self.today_list.canvas.configure(height=1)
        self.today_list.pack(fill='both', expand=True)
        footer = ttk.Frame(parent)
        footer.pack(fill='x', pady=(8, 0))
        ttk.Label(footer, textvariable=self.today_count, foreground='#667085').pack(side='left')
        ttk.Checkbutton(footer, text='隐藏已完成', variable=self.hide_completed, command=self._display_today).pack(side='right')

    def _build_finance(self):
        parent = self.finance_panel
        heading = ttk.Frame(parent)
        heading.pack(fill='x')
        ttk.Label(heading, textvariable=self.finance_title, foreground='#667085').pack(side='left')
        ttk.Button(heading, text='查看', width=5, command=lambda: self.navigate('finance')).pack(side='right')
        self.eye_icons = (self._eye_icon(True), self._eye_icon(False))
        self.finance_eye = ttk.Button(heading, text='显示金额', image=self.eye_icons[0], width=3,
                                      command=self.toggle_finance)
        self.finance_eye.pack(side='right', padx=(4, 6))
        amounts = ttk.Frame(parent)
        amounts.pack(fill='x', pady=(4, 0))
        for column, label, variable in ((0, '总收入', self.income), (1, '总支出', self.expense)):
            amounts.columnconfigure(column, weight=1)
            box = ttk.Frame(amounts)
            box.grid(row=0, column=column, sticky='ew', padx=(0, 12) if column == 0 else 0)
            ttk.Label(box, text=label, foreground='#667085').pack(anchor='w')
            ttk.Label(box, textvariable=variable, font=('Microsoft YaHei UI', 15)).pack(anchor='w')

    def _eye_icon(self, crossed):
        icon = tk.PhotoImage(master=self, width=20, height=16)
        for x in range(1, 19):
            height = round(5 * math.sin(math.pi * (x - 1) / 17))
            for y in (8 - height, 8 + height):
                icon.put('#475467', (x, y))
        for x in range(7, 13):
            for y in range(5, 11):
                if (x - 9.5) ** 2 + (y - 8) ** 2 <= 7:
                    icon.put('#475467', (x, y))
        if crossed:
            for x in range(2, 18):
                icon.put('#475467', (x, round(2 + (x - 2) * 11 / 15)))
        return icon

    def toggle_finance(self):
        self.finance_visible = not self.finance_visible
        self._display_finance()

    def _display_finance(self):
        if self.snapshot is None:
            return
        self.income.set(money_text(self.snapshot.finance.income) if self.finance_visible else '••••')
        self.expense.set(money_text(self.snapshot.finance.expense) if self.finance_visible else '••••')
        self.finance_eye.configure(image=self.eye_icons[int(self.finance_visible)],
                                   text='隐藏金额' if self.finance_visible else '显示金额')

    def _build_projects(self):
        parent = self.projects_panel
        heading = ttk.Frame(parent)
        heading.pack(fill='x', pady=(0, 5))
        ttk.Label(heading, textvariable=self.project_count, foreground='#667085').pack(side='left')
        ttk.Button(heading, text='查看全部', command=lambda: self.navigate('projects')).pack(side='right')
        container = ttk.Frame(parent)
        container.pack(fill='both', expand=True)
        self.project_canvas = tk.Canvas(container, width=220, height=1, highlightthickness=0)
        scroll = ttk.Scrollbar(container, orient='vertical', command=self.project_canvas.yview)
        self.project_canvas.configure(yscrollcommand=scroll.set)
        self.project_canvas.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.project_body = ttk.Frame(self.project_canvas)
        self.project_window = self.project_canvas.create_window(0, 0, anchor='nw', window=self.project_body)
        self.project_body.bind('<Configure>', lambda _: self.project_canvas.configure(scrollregion=self.project_canvas.bbox('all')))
        self.project_canvas.bind('<Configure>', self._resize_projects)
        self.project_canvas.bind('<MouseWheel>', self._scroll_projects)

    def _resize_projects(self, event):
        self.project_canvas.itemconfigure(self.project_window, width=event.width)
        for row in self.project_rows.values():
            row['stage'].configure(wraplength=max(100, event.width - 16))

    def _scroll_projects(self, event):
        if self.project_body.winfo_height() > self.project_canvas.winfo_height():
            self.project_canvas.yview_scroll(-int(event.delta / 120), 'units')
        return 'break'

    def _bind_scroll(self, widget):
        widget.bind('<MouseWheel>', self._scroll_projects)
        for child in widget.winfo_children():
            self._bind_scroll(child)

    def refresh(self):
        try:
            snapshot = self.service.dashboard.snapshot()
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.snapshot = snapshot
        self.error.set('')
        day = snapshot.day
        self.date_text.set(f'{day:%Y 年 %m 月 %d 日} · 周{"一二三四五六日"[day.weekday()]}')
        self.today_text.set(f'{day:%m/%d} · 周{"一二三四五六日"[day.weekday()]}')
        self.finance_title.set(day.strftime('%Y 年 %m 月'))
        self._display_finance()
        self.refresh_notes()
        self.project_count.set(f'Active · {len(snapshot.projects)} 个项目')
        jobs = snapshot.jobs
        self.jobs_text.set(f'已投 {jobs.applications} 个岗位 · 面试中 {jobs.interviews} 个 · Offer {jobs.offers} 个')
        self._display_today()
        self._display_projects()
        self.time_chart.display(snapshot.activity)

    def _display_today(self):
        if self.snapshot is None:
            return
        tasks = self.snapshot.tasks
        visible = tuple(t for t in tasks if not self.hide_completed.get() or not t.completed)
        self.today_list.display(visible, self.snapshot.day)
        completed = sum(t.completed for t in tasks)
        self.today_count.set(f'已完成 {completed} / {len(tasks)} · 剩余 {len(tasks) - completed} 项')

    def _display_projects(self):
        position = self.project_canvas.yview()[0]
        for child in self.project_body.winfo_children():
            child.destroy()
        self.project_rows.clear()
        for item in self.snapshot.projects:
            summary, project = item.summary, item.summary.project
            row = ttk.Frame(self.project_body, padding=(0, 3, 4, 8))
            row.pack(fill='x')
            ttk.Button(row, text=f'[{project.code}] {project.name}',
                       command=lambda identifier=project.id: self.on_project(identifier)).pack(anchor='w')
            if project.mode == '目标型':
                value = 100 * summary.completed / summary.total if summary.total else 0
                text = f'{value:.0f}% · {summary.completed}/{summary.total} 完成'
                bar = tk.Canvas(row, height=8, background='#edf0f4', highlightthickness=0)
                bar.create_rectangle(0, 0, 0, 8, fill='#3672a9', outline='', tags='fill')
                bar.bind('<Configure>', lambda event, canvas=bar, percent=value:
                         canvas.coords('fill', 0, 0, event.width * percent / 100, event.height))
            else:
                text = f'累计完成 {item.completion_count} 次 · 当前 {summary.completed}/{summary.total}'
                strength = item.completion_count / (item.completion_count + 8)
                color = '#' + ''.join(f'{round(255 + (channel - 255) * strength):02x}' for channel in (37, 99, 235))
                bar = tk.Canvas(row, height=9, background=color, highlightthickness=0)
            label = ttk.Label(row, text=text, foreground='#667085')
            label.pack(anchor='w', pady=(3, 2))
            bar.pack(fill='x')
            stage = ttk.Label(row, text=item.stage or project.mode, foreground='#667085',
                              wraplength=max(100, self.project_canvas.winfo_width() - 16))
            stage.pack(anchor='w', pady=(2, 0))
            self.project_rows[project.id] = dict(label=label, bar=bar, stage=stage)
            self._bind_scroll(row)
        if not self.snapshot.projects:
            ttk.Label(self.project_body, text='暂无进行中的项目', foreground='#667085', padding=6).pack(anchor='w')
        self.project_body.update_idletasks()
        self.project_canvas.configure(scrollregion=self.project_canvas.bbox('all'))
        self.project_canvas.yview_moveto(position)

    def refresh_activity(self, snapshot=None):
        try:
            day = self.service.tasks.today()
            if self.snapshot is None or self.snapshot.day != day:
                self.refresh()
            else:
                self.time_chart.display(snapshot if snapshot is not None and snapshot.day == day
                                        else self.service.day_snapshot(day))
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))

    def _changed(self, _identifier=None):
        self.on_change()
        self.refresh()

    def _run(self, action):
        try:
            action()
        except (ValueError, sqlite3.Error) as error:
            self._display_today()
            self.error.set(str(error))
            return
        self._changed()

    def add_today(self):
        try:
            self.service.tasks.add_today(self.quick_title.get())
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.quick_title.set('')
        self._changed()

    def add_task(self):
        return self._open_editor()

    def edit_task(self, identifier):
        return self._open_editor(identifier)

    def _open_editor(self, identifier=None):
        try:
            task = self.service.tasks.get(identifier) if identifier is not None else None
            return TaskDialog(self.winfo_toplevel(), self.service.tasks, self._changed,
                              self.service.tasks.today(), task=task)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))

    def choose_task(self):
        try:
            return TaskPicker(self.winfo_toplevel(), self.service.tasks, self._changed)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))

    def remove_today(self, identifier):
        self._run(lambda: self.service.tasks.remove_today(identifier))

    def complete_task(self, identifier, completed):
        self._run(lambda: self.service.tasks.complete(identifier, completed))

    def _check_day(self):
        self.day_timer = None
        if self.snapshot is None or self.service.tasks.today() != self.snapshot.day:
            self.refresh()
        self.day_timer = self.after(30000, self._check_day)

    def cancel_refresh(self):
        if self.day_timer is not None:
            self.after_cancel(self.day_timer)
            self.day_timer = None
