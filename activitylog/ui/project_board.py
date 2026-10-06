"""Project lanes, collapsible stages, inline notes and shared schedules."""
import calendar
from datetime import date, timedelta
import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk
from ..projects import PROJECT_LANES, PROJECT_MODES, LANE_STATUS, ProjectDraft, MilestoneDraft
from ..tasks import TASK_PRIORITIES, TaskDraft
from .priority import PriorityDots


class ProjectDialog(tk.Toplevel):
    def __init__(self, parent, service, on_saved, project=None):
        super().__init__(parent)
        self.title('编辑项目' if project else '新增项目')
        self.transient(parent)
        self.service, self.on_saved = service, on_saved
        self.identifier = project.id if project else None
        self.name_var = tk.StringVar(value=project.name if project else '')
        self.lane_var = tk.StringVar(value=project.lane if project else 'Active')
        self.priority_var = tk.StringVar(value=project.priority if project else '普通')
        self.mode_var = tk.StringVar(value=project.mode if project else '目标型')
        self.error = tk.StringVar()
        body = ttk.Frame(self, padding=16)
        body.pack(fill='both', expand=True)
        for row, (label, variable, choices) in enumerate((('名称', self.name_var, None), ('状态', self.lane_var, PROJECT_LANES), ('优先级', self.priority_var, TASK_PRIORITIES), ('项目类型', self.mode_var, PROJECT_MODES))):
            ttk.Label(body, text=label).grid(row=row, column=0, padx=(0, 12), pady=6, sticky='w')
            widget = ttk.Combobox(body, textvariable=variable, values=choices, state='readonly') if choices else ttk.Entry(body, textvariable=variable, width=38)
            widget.grid(row=row, column=1, sticky='ew', pady=6)
        ttk.Label(body, text='目标（可留空）').grid(row=4, column=0, sticky='nw')
        self.goal = tk.Text(body, width=38, height=3, wrap='word')
        self.goal.grid(row=4, column=1)
        self.goal.insert('1.0', project.goal if project else '')
        ttk.Label(body, textvariable=self.error, foreground='#b42318', wraplength=440).grid(row=5, column=0, columnspan=2)
        ttk.Button(body, text='保存', command=self.submit).grid(row=6, column=1, sticky='e', pady=10)
        self.bind('<Escape>', lambda _: self.destroy())
        self.grab_set()

    def submit(self):
        try:
            identifier = self.service.save(ProjectDraft(self.name_var.get(), self.goal.get('1.0', 'end-1c'), LANE_STATUS[self.lane_var.get()], self.priority_var.get(), self.mode_var.get()), self.identifier)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.destroy()
        self.on_saved(identifier)


class TaskRow(tk.Frame):
    def __init__(self, parent, board, task):
        super().__init__(parent, background='white', padx=4, pady=4)
        self.board, self.task, self.timer = board, task, None
        self.title_var = tk.StringVar(value=task.title)
        self.done = tk.BooleanVar(value=task.completed)
        self.priority = tk.StringVar(value=task.priority)
        bar = tk.Frame(self, background='white')
        bar.pack(fill='x')
        bar.columnconfigure(1, weight=1)
        ttk.Checkbutton(bar, variable=self.done, command=self.complete).grid(row=0, column=0)
        self.title_entry = ttk.Entry(bar, textvariable=self.title_var, width=1)
        self.title_entry.grid(row=0, column=1, sticky='ew', padx=4)
        for event in ('<Return>', '<FocusOut>'):
            self.title_entry.bind(event, lambda _: self.save_fields())
        combo = ttk.Combobox(bar, textvariable=self.priority, values=TASK_PRIORITIES, state='readonly', width=6)
        combo.grid(row=0, column=2, padx=3)
        combo.bind('<<ComboboxSelected>>', lambda _: self.save_fields())
        self.date_button = ttk.Button(bar, text=self.date_text(), width=11, command=lambda: board.select_task(task.id))
        self.date_button.grid(row=0, column=3, padx=3)
        self.note_button = ttk.Button(bar, text='笔记 ▸' + (' ●' if task.notes else ''), width=7, command=self.toggle_notes)
        self.note_button.grid(row=0, column=4, padx=3)
        ttk.Button(bar, text='×', width=2, command=lambda: board.delete_task(task.id)).grid(row=0, column=5)
        self.note_frame = tk.Frame(self, background='#f5f7fb', padx=8, pady=6)
        self.notes = tk.Text(self.note_frame, width=1, height=3, wrap='word', relief='flat', background='#f5f7fb', font=('Microsoft YaHei UI', 9))
        self.notes.pack(fill='x')
        self.notes.insert('1.0', task.notes)
        self.notes.edit_modified(False)
        self.notes.bind('<<Modified>>', self.queue_notes)
        self.notes.bind('<FocusOut>', lambda _: self.save_notes())
        actions = tk.Frame(self.note_frame, background='#f5f7fb')
        actions.pack(fill='x')
        self.saved = tk.StringVar(value='已保存')
        tk.Label(actions, textvariable=self.saved, background='#f5f7fb', foreground='#667085').pack(side='left')
        ttk.Button(actions, text='全览', command=self.full_notes).pack(side='right')
        ttk.Button(actions, text='更多设置', command=self.more_settings).pack(side='right', padx=6)
        ttk.Button(actions, text='保存', command=self.save_notes).pack(side='right', padx=6)
        self.bind('<Destroy>', self.cleanup)

    def date_text(self):
        if self.task.range_start and self.task.range_start != self.task.range_end:
            return f'{self.task.range_start:%m/%d}—{self.task.range_end:%m/%d}'
        return self.task.planned_on.isoformat() if self.task.planned_on else '安排日期'

    def dirty(self):
        return self.title_var.get() != self.task.title or self.priority.get() != self.task.priority or self.notes.get('1.0', 'end-1c') != self.task.notes

    def save_fields(self):
        changes = dict(title=self.title_var.get(), priority=self.priority.get())
        if all(getattr(self.task, key) == value for key, value in changes.items()):
            return True
        if not self.board.run(lambda: self.board.service.tasks.update(self.task.id, **changes)):
            return False
        self.task = self.board.service.tasks.get(self.task.id)
        self.title_var.set(self.task.title)
        self.done.set(self.task.completed)
        self.board.update_counts()
        return True

    def complete(self):
        previous = self.task.status
        if self.board.run(lambda: self.board.service.tasks.complete(self.task.id, self.done.get())):
            self.task = self.board.service.tasks.get(self.task.id)
            if self.task.completed:
                self.board.undo_state = (self.task.id, previous)
                self.board.feedback.set('✓ 已完成，可撤销')
            self.board.update_counts()
        else:
            self.done.set(self.task.completed)

    def toggle_notes(self):
        if self.note_frame.winfo_manager():
            if not self.save_notes():
                return
            self.note_frame.pack_forget()
        else:
            self.note_frame.pack(fill='x', padx=(24, 0), pady=(4, 0))
            self.notes.focus_set()
        self.note_button.configure(text=('笔记 ▾' if self.note_frame.winfo_manager() else '笔记 ▸') + (' ●' if self.task.notes else ''))

    def queue_notes(self, _event=None):
        if self.notes.edit_modified():
            self.notes.edit_modified(False)
            if self.timer is not None:
                self.after_cancel(self.timer)
            self.saved.set('待保存')
            self.timer = self.after(800, self.save_notes)

    def save_notes(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        value = self.notes.get('1.0', 'end-1c')
        if value != self.task.notes:
            if not self.board.run(lambda: self.board.service.tasks.update(self.task.id, notes=value)):
                self.saved.set('保存失败，内容仍保留')
                return False
            self.task = self.board.service.tasks.get(self.task.id)
            if value != self.task.notes:
                self.notes.delete('1.0', 'end')
                self.notes.insert('1.0', self.task.notes)
                self.notes.edit_modified(False)
        self.saved.set('已保存')
        return True

    def full_notes(self):
        if not self.save_notes():
            return
        window = tk.Toplevel(self)
        window.title('笔记全览 · ' + self.task.title)
        window.geometry('760x540')
        window.transient(self.winfo_toplevel())
        window.grab_set()
        text = tk.Text(window, wrap='word', font=('Microsoft YaHei UI', 11), padx=16, pady=12)
        text.pack(fill='both', expand=True)
        text.insert('1.0', self.task.notes)
        def save():
            if self.board.run(lambda: self.board.service.tasks.update(self.task.id, notes=text.get('1.0', 'end-1c'))):
                self.task = self.board.service.tasks.get(self.task.id)
                self.notes.delete('1.0', 'end')
                self.notes.insert('1.0', self.task.notes)
                self.notes.edit_modified(False)
                window.destroy()
        ttk.Button(window, text='保存并关闭', command=save).pack(anchor='e', padx=16, pady=10)
        window.protocol('WM_DELETE_WINDOW', save)
        window.bind('<Control-Return>', lambda _: save())
        return window

    def more_settings(self):
        from .task_editor import TaskDialog
        if self.board.flush_edits():
            return TaskDialog(self.winfo_toplevel(), self.board.service.tasks,
                lambda identifier: self.board.task_saved(identifier), None,
                task=self.board.service.tasks.get(self.task.id), in_today=self.board.service.tasks.is_in_today(self.task.id))

    def cleanup(self, event):
        if event.widget == self and self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None


class ProjectOverview(ttk.Frame):
    def __init__(self, parent, service):
        super().__init__(parent, padding=14)
        self.service, self.project = service, None
        self.selected_project_id = self.selected_task_id = None
        self.rows, self.stages, self.stage_open = {}, {}, {}
        self.milestones = ()
        self.undo_state = self.filter_timer = None
        for key, value in (('error', ''), ('feedback', ''), ('project_keyword', ''), ('name', ''), ('goal', ''), ('lane', 'Active'), ('mode', '目标型'), ('priority', '普通'), ('progress', ''), ('quick_title', ''), ('schedule_start', ''), ('schedule_end', ''), ('schedule_label', '请选择事项的日期按钮')):
            setattr(self, key, tk.StringVar(value=value))
        self.schedule_original = ('', '')
        self.dots = PriorityDots(self)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 14))
        ttk.Label(left, text='搜索项目名称 / 编号', foreground='#667085').pack(anchor='w', pady=(0, 5))
        ttk.Entry(left, textvariable=self.project_keyword, width=25).pack(fill='x', pady=(0, 8))
        project_list = ttk.Frame(left)
        project_list.pack(fill='both', expand=True)
        self.project_table = ttk.Treeview(project_list, columns=('priority',), show=('tree', 'headings'), selectmode='browse')
        self.project_table.heading('#0', text='项目')
        self.project_table.column('#0', width=183, minwidth=110)
        self.project_table.heading('priority', text='优先级')
        self.project_table.column('priority', width=45, stretch=False)
        self.project_table.pack(side='left', fill='both', expand=True)
        project_scroll = ttk.Scrollbar(project_list, command=self.project_table.yview)
        self.project_table.configure(yscrollcommand=project_scroll.set)
        project_scroll.pack(side='right', fill='y')
        self.project_table.bind('<<TreeviewSelect>>', self.project_selected)
        actions = ttk.Frame(left)
        actions.pack(fill='x', pady=(8, 0))
        for label, action in (('＋新增', self.add_project), ('编辑', self.edit_project), ('删除', self.delete_project)):
            ttk.Button(actions, text=label, command=action, width=7).pack(side='left', padx=(0, 4))
        self.right = ttk.Frame(self)
        self.right.grid(row=0, column=1, sticky='nsew')
        self.build_header()
        self.build_schedule()
        work = ttk.Frame(self.right)
        work.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(work, background='white', highlightthickness=0)
        scroll = ttk.Scrollbar(work, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.body = tk.Frame(self.canvas, background='white')
        self.window = self.canvas.create_window(0, 0, anchor='nw', window=self.body)
        self.body.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(self.window, width=event.width))
        self.canvas.bind('<MouseWheel>', self.scroll)
        feedback = ttk.Frame(self)
        feedback.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(4, 0))
        ttk.Label(feedback, textvariable=self.error, foreground='#b42318', wraplength=850).pack(side='left')
        ttk.Label(feedback, textvariable=self.feedback, foreground='#276943').pack(side='left', padx=8)
        self.project_keyword.trace_add('write', lambda *_: self.schedule_refresh())
        self.refresh()

    def build_header(self):
        heading = ttk.Frame(self.right)
        heading.pack(fill='x')
        entry = ttk.Entry(heading, textvariable=self.name, font=('Microsoft YaHei UI', 14, 'bold'), width=1)
        entry.pack(side='left', fill='x', expand=True)
        for event in ('<Return>', '<FocusOut>'):
            entry.bind(event, lambda _: self.save_project_fields())
        ttk.Label(heading, text='状态').pack(side='left', padx=(12, 6))
        combo = ttk.Combobox(heading, textvariable=self.lane, values=PROJECT_LANES, state='readonly', width=9)
        combo.pack(side='left')
        combo.bind('<<ComboboxSelected>>', lambda _: self.change_lane())
        meta = ttk.Frame(self.right)
        meta.pack(fill='x', pady=8)
        for label, variable, choices in (('类型', self.mode, PROJECT_MODES), ('优先级', self.priority, TASK_PRIORITIES)):
            ttk.Label(meta, text=label).pack(side='left', padx=(0, 6))
            combo = ttk.Combobox(meta, textvariable=variable, values=choices, state='readonly', width=7)
            combo.pack(side='left', padx=(0, 12))
            combo.bind('<<ComboboxSelected>>', lambda _: self.save_project_fields())
        ttk.Label(meta, textvariable=self.progress, foreground='#667085').pack(side='right')
        goal = ttk.Entry(self.right, textvariable=self.goal)
        goal.pack(fill='x', pady=(0, 6))
        for event in ('<Return>', '<FocusOut>'):
            goal.bind(event, lambda _: self.save_project_fields())
        self.progress_bar = ttk.Progressbar(self.right, maximum=100)
        self.progress_bar.pack(fill='x', pady=(0, 8))
        self.exploration_bar = tk.Canvas(self.right, height=14, background='white', highlightthickness=1, highlightbackground='#d0d5dd')
        self.exploration_fill = self.exploration_bar.create_rectangle(0, 0, 0, 14, fill='white', outline='')
        self.exploration_bar.bind('<Configure>', lambda event: self.exploration_bar.coords(self.exploration_fill, 0, 0, event.width, event.height))
        self.tools = ttk.Frame(self.right)
        self.tools.pack(fill='x', pady=(0, 8))
        ttk.Button(self.tools, text='＋阶段', command=self.add_stage).pack(side='left')
        quick = ttk.Entry(self.tools, textvariable=self.quick_title, width=1)
        quick.pack(side='left', fill='x', expand=True, padx=6)
        quick.bind('<Return>', lambda _: self.add_task())
        self.stage_combo = ttk.Combobox(self.tools, state='readonly', width=15)
        self.stage_combo.pack(side='left')
        self.add_item_button = ttk.Button(self.tools, text='＋事项', command=self.add_task)
        self.add_item_button.pack(side='left', padx=(6, 0))

    def build_schedule(self):
        self.schedule = schedule = ttk.LabelFrame(self.right, text='事项安排 · 点击事项的日期按钮', padding=5)
        schedule.pack(side='bottom', fill='x', pady=(8, 0))
        for text in ('今天', '一周', '一个月'):
            ttk.Button(schedule, text=text, width=5, command=lambda kind=text: self.preset(kind)).pack(side='left', padx=(0, 3))
        ttk.Entry(schedule, textvariable=self.schedule_start, width=10).pack(side='left')
        ttk.Label(schedule, text=' 至 ').pack(side='left')
        ttk.Entry(schedule, textvariable=self.schedule_end, width=10).pack(side='left')
        ttk.Button(schedule, text='应用', width=4, command=self.apply_schedule).pack(side='left', padx=3)
        ttk.Button(schedule, text='清除', width=4, command=self.clear_schedule).pack(side='left')
        self.undo_button = ttk.Button(schedule, text='撤销完成', width=8, command=self.undo_completion, state='disabled')
        self.undo_button.pack(side='right')

    def run(self, action):
        try:
            action()
            self.error.set('')
            return True
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return False

    def has_drafts(self):
        return bool(self.project and (self.name.get() != self.project.name or self.goal.get() != self.project.goal)) or any(row.dirty() for row in self.rows.values()) or (self.schedule_start.get(), self.schedule_end.get()) != self.schedule_original or any(name.get() != stage.name for stage, name, _body, _count in self.stages.values())

    def inline_editing(self):
        widget = self.focus_get()
        if isinstance(widget, (ttk.Combobox,)) or not isinstance(widget, (ttk.Entry, tk.Entry, tk.Text)):
            return self.has_drafts()
        parent = widget
        while parent is not None:
            if parent == self:
                return True
            parent = getattr(parent, 'master', None)
        return self.has_drafts()

    def flush_edits(self):
        if not self.save_project_fields():
            return False
        for identifier in self.stages:
            if not self.save_stage(identifier):
                return False
        for row in self.rows.values():
            if row.dirty() and (not row.save_fields() or not row.save_notes()):
                return False
        if (self.schedule_start.get(), self.schedule_end.get()) != self.schedule_original:
            return self.apply_schedule()
        return True

    def save_project_fields(self):
        if not self.project:
            return True
        changes = dict(name=self.name.get(), goal=self.goal.get(), priority=self.priority.get(), mode=self.mode.get())
        if all(getattr(self.project, key) == value for key, value in changes.items()):
            return True
        if self.run(lambda: self.service.update(self.project.id, **changes)):
            self.project = self.service.get(self.project.id)
            self.name.set(self.project.name)
            self.goal.set(self.project.goal)
            item = f'project-{self.project.id}'
            if self.project_table.exists(item):
                self.project_table.item(item, text=f'[{self.project.code}] {self.project.name}', values=(self.project.priority,), image=self.dots.images[self.project.priority, self.project.status == '已完成'])
                peers = sorted((s.project for s in self.service.summaries() if s.project.lane == self.project.lane and self.project_table.exists(f'project-{s.project.id}')), key=lambda p: (TASK_PRIORITIES.index(p.priority), p.id))
                self.project_table.move(item, 'group-' + self.project.lane, next(i for i, p in enumerate(peers) if p.id == self.project.id))
            self.update_counts()
            return True
        return False

    def change_lane(self):
        if self.project and self.flush_edits() and self.run(lambda: self.service.set_lane(self.project.id, self.lane.get())):
            self.refresh(self.project.id)

    def refresh(self, project_id=None, item_id=None):
        if not self.flush_edits():
            return
        selected = project_id if project_id is not None else self.selected_project_id
        groups = {lane: self.project_table.item('group-' + lane, 'open') if self.project_table.exists('group-' + lane) else lane == 'Active' for lane in PROJECT_LANES}
        try:
            query = self.project_keyword.get().strip().casefold()
            visible = [s.project for s in self.service.summaries() if query in (s.project.code + ' ' + s.project.name + ' ' + s.project.goal).casefold()]
            selected = selected if selected in {p.id for p in visible} else (visible[0].id if visible else None)
            project = self.service.get(selected) if selected else None
            tasks = self.service.items(selected) if selected else ()
            milestones = self.service.milestones(selected) if selected else ()
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        if selected != self.selected_project_id:
            self.undo_state = None
            self.feedback.set('')
        self.selected_project_id, self.project = selected, project
        self.project_table.delete(*self.project_table.get_children())
        for lane in PROJECT_LANES:
            items = [p for p in visible if p.lane == lane]
            self.project_table.insert('', 'end', iid='group-' + lane, text=f'{lane} · {len(items)}', open=bool(query) or groups[lane])
            for value in sorted(items, key=lambda p: (TASK_PRIORITIES.index(p.priority), p.id)):
                self.project_table.insert('group-' + lane, 'end', iid=f'project-{value.id}', text=f'[{value.code}] {value.name}', values=(value.priority,), image=self.dots.images[value.priority, value.status == '已完成'])
        if project:
            self.project_table.selection_set(f'project-{project.id}')
        for key, value in (('name', project.name if project else ''), ('goal', project.goal if project else ''), ('lane', project.lane if project else 'Active'), ('mode', project.mode if project else '目标型'), ('priority', project.priority if project else '普通')):
            getattr(self, key).set(value)
        for child in self.body.winfo_children():
            child.destroy()
        self.rows, self.stages, self.milestones = {}, {}, milestones
        self.unassigned_count = None
        self.stage_combo.configure(values=['未分阶段'] + [f'阶段 {i+1} · {stage.name}' for i, stage in enumerate(milestones)])
        self.stage_combo.current(0)
        for index, stage in enumerate(milestones):
            self.build_stage(stage, index + 1, [task for task in tasks if task.milestone_id == stage.id])
        self.build_stage(None, 0, [task for task in tasks if task.milestone_id is None])
        self.add_item_button.configure(state='normal' if project else 'disabled')
        self.selected_task_id = item_id if item_id in self.rows else None
        self.select_task(self.selected_task_id)
        self.update_counts()
        self.bind_wheel(self.body)

    def build_stage(self, stage, number, tasks):
        if not stage and not tasks and self.milestones:
            return
        identifier = stage.id if stage else None
        frame = tk.Frame(self.body, background='white', padx=6, pady=7)
        frame.pack(fill='x')
        heading = tk.Frame(frame, background='white')
        heading.pack(fill='x')
        body = tk.Frame(frame, background='white')
        expanded = self.stage_open.get(identifier, True)
        button = ttk.Button(heading, text=('▾' if expanded else '▸') + (f' 阶段 {number}' if stage else ' 未分阶段'), width=11, command=lambda: self.toggle_stage(identifier, body, button))
        button.pack(side='left')
        count = tk.Label(heading, text=f'{sum(t.completed for t in tasks)}/{len(tasks)}', background='white', foreground='#667085')
        count.pack(side='right')
        if stage is None:
            self.unassigned_count = count
        if stage:
            name = tk.StringVar(value=stage.name)
            entry = ttk.Entry(heading, textvariable=name, width=1)
            entry.pack(side='left', fill='x', expand=True, padx=6)
            for event in ('<Return>', '<FocusOut>'):
                entry.bind(event, lambda _, key=identifier: self.save_stage(key))
            ttk.Button(heading, text='×', width=2, command=lambda: self.delete_stage(identifier)).pack(side='right', padx=4)
            self.stages[identifier] = (stage, name, body, count)
        for task in tasks:
            row = TaskRow(body, self, task)
            row.pack(fill='x')
            self.rows[task.id] = row
        if not tasks:
            tk.Label(body, text='暂无事项，可在上方选择阶段后新增', background='white', foreground='#98a2b3', pady=8).pack(anchor='w')
        if expanded:
            body.pack(fill='x')

    def toggle_stage(self, identifier, body, button):
        if not self.flush_edits():
            return
        expanded = not bool(body.winfo_manager())
        self.stage_open[identifier] = expanded
        body.pack(fill='x') if expanded else body.pack_forget()
        button.configure(text=button['text'].replace('▸', '▾') if expanded else button['text'].replace('▾', '▸'))

    def save_stage(self, identifier):
        stage, name, body, count = self.stages[identifier]
        if name.get() == stage.name:
            return True
        if self.run(lambda: self.service.save_milestone(stage.project_id, MilestoneDraft(name.get(), stage.acceptance), identifier)):
            latest = next(s for s in self.service.milestones(stage.project_id) if s.id == identifier)
            name.set(latest.name)
            self.stages[identifier] = (latest, name, body, count)
            self.update_counts()
            return True
        return False

    def project_selected(self, _event=None):
        selection = self.project_table.selection()
        if selection and selection[0].startswith('project-'):
            identifier = int(selection[0].split('-')[1])
            if identifier != self.selected_project_id:
                self.refresh(identifier)

    def add_project(self):
        if self.flush_edits():
            return ProjectDialog(self.winfo_toplevel(), self.service, self.saved_project)

    def saved_project(self, identifier):
        self.project_keyword.set('')
        self.refresh(identifier)

    def task_saved(self, identifier):
        task = self.service.tasks.get(identifier)
        self.project_keyword.set('')
        self.stage_open[task.milestone_id] = True
        self.refresh(task.project_id, identifier)

    def edit_project(self):
        if self.project and self.flush_edits():
            return ProjectDialog(self.winfo_toplevel(), self.service, self.saved_project, self.project)

    def delete_project(self):
        if self.project and self.flush_edits() and messagebox.askyesno('删除项目', '删除项目？事项保留并解除项目关联。', parent=self.winfo_toplevel()):
            if self.run(lambda: self.service.delete(self.project.id)):
                self.project = None
                self.refresh()

    def add_stage(self):
        if self.project and self.flush_edits() and self.run(lambda: self.service.save_milestone(self.project.id, MilestoneDraft('新阶段'))):
            self.refresh(self.project.id)
            self.stage_combo.current(len(self.milestones))

    def delete_stage(self, identifier):
        if self.flush_edits() and messagebox.askyesno('删除阶段', '事项会保留在未分阶段中，确认删除阶段？', parent=self.winfo_toplevel()) and self.run(lambda: self.service.delete_milestone(identifier)):
            self.refresh()

    def add_task(self):
        if not self.project or not self.flush_edits():
            return
        index = self.stage_combo.current()
        milestone = self.milestones[index - 1].id if index > 0 else None
        result = []
        if self.run(lambda: result.append(self.service.tasks.save(TaskDraft(self.quick_title.get(), '', project_id=self.project.id, milestone_id=milestone)))):
            self.quick_title.set('')
            self.stage_open[milestone] = True
            self.refresh(item_id=result[0])

    def delete_task(self, identifier):
        if self.flush_edits() and messagebox.askyesno('删除事项', '删除项目、日历和待办中的该事项？', parent=self.winfo_toplevel()) and self.run(lambda: self.service.tasks.delete(identifier)):
            self.rows[identifier].destroy()
            del self.rows[identifier]
            if self.undo_state and self.undo_state[0] == identifier:
                self.undo_state = None
            self.refresh()

    def select_task(self, identifier):
        if identifier != self.selected_task_id and (self.schedule_start.get(), self.schedule_end.get()) != self.schedule_original:
            if not self.apply_schedule():
                return
        self.selected_task_id = identifier
        task = self.service.tasks.get(identifier) if identifier else None
        start = (task.range_start or task.planned_on) if task else None
        end = (task.range_end or start) if task else None
        self.schedule_original = (start.isoformat() if start else '', end.isoformat() if end else '')
        self.schedule_start.set(self.schedule_original[0])
        self.schedule_end.set(self.schedule_original[1])
        self.schedule_label.set(f'[{task.project_code}] {task.title}' if task else '点击事项的日期按钮；结束日期留空表示单日')
        label = self.schedule_label.get()
        self.schedule.configure(text='事项安排 · ' + (label[:28] + '…' if len(label) > 28 else label))

    def preset(self, kind):
        if self.selected_task_id is None:
            self.error.set('请先点击事项的日期按钮。')
            return
        start = self.service.tasks.today()
        try:
            if kind == '一个月':
                year, month = divmod(start.year * 12 + start.month, 12)
                end = date(year, month + 1, min(start.day, calendar.monthrange(year, month + 1)[1])) - timedelta(days=1)
            else:
                end = start + timedelta(days=6 if kind == '一周' else 0)
        except (ValueError, OverflowError):
            self.error.set('日期超出可安排范围。')
            return
        self.schedule_start.set(start.isoformat())
        self.schedule_end.set(end.isoformat())
        self.apply_schedule()

    def apply_schedule(self):
        if self.selected_task_id is None:
            self.error.set('请先选择要安排的事项。')
            return False
        if not self.run(lambda: self.service.tasks.schedule(self.selected_task_id, self.schedule_start.get().strip(), self.schedule_end.get().strip())):
            return False
        self.schedule_original = (self.schedule_start.get(), self.schedule_end.get())
        row = self.rows.get(self.selected_task_id)
        if row:
            row.task = self.service.tasks.get(row.task.id)
            row.date_button.configure(text=row.date_text())
        self.feedback.set('已保存安排')
        return True

    def clear_schedule(self):
        self.schedule_start.set('')
        self.schedule_end.set('')
        self.apply_schedule()

    def update_counts(self):
        if not self.project:
            self.progress.set('暂无项目')
            self.exploration_bar.pack_forget()
            self.progress_bar.configure(value=0)
            return
        tasks = self.service.items(self.project.id)
        completed = sum(task.completed for task in tasks)
        if self.project.mode == '目标型':
            self.progress.set(f'{completed / len(tasks):.1%} · {completed}/{len(tasks)} 完成' if tasks else '0% · 0/0 完成')
            self.exploration_bar.pack_forget()
            self.progress_bar.pack(fill='x', pady=(0, 8), before=self.tools)
            self.progress_bar.configure(value=100 * completed / len(tasks) if tasks else 0)
        else:
            self.progress_bar.pack_forget()
            count = len(self.service.completion_records(self.project.id))
            self.progress.set(f'累计完成 {count} 次 · 当前完成 {completed}/{len(tasks)} 项')
            # No target total: deepen the whole strip with accumulated real events.
            strength = count / (count + 8)
            color = '#' + ''.join(f'{round(255 + (channel - 255) * strength):02x}' for channel in (37, 99, 235))
            self.exploration_bar.itemconfigure(self.exploration_fill, fill=color)
            self.exploration_bar.pack(fill='x', pady=(0, 8), before=self.tools)
        if self.unassigned_count is not None:
            unassigned = [task for task in tasks if task.milestone_id is None]
            self.unassigned_count.configure(text=f'{sum(t.completed for t in unassigned)}/{len(unassigned)}')
        for identifier, (_stage, _name, _body, label) in self.stages.items():
            values = [task for task in tasks if task.milestone_id == identifier]
            label.configure(text=f'{sum(t.completed for t in values)}/{len(values)}')
        self.undo_button.configure(state='normal' if self.undo_state else 'disabled')

    def undo_completion(self):
        if self.undo_state:
            identifier, status = self.undo_state
            tasks = []
            if not self.run(lambda: tasks.append(self.service.tasks.get(identifier))):
                return
            if not tasks[0].completed:
                self.error.set('事项状态已改变，无法撤销。')
                return
            if self.run(lambda: self.service.tasks.set_status(identifier, status)):
                self.undo_state = None
                self.refresh(item_id=identifier)
                self.feedback.set('已撤销完成')

    def scroll(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), 'units')
        return 'break'

    def bind_wheel(self, widget):
        if not isinstance(widget, (tk.Text, ttk.Combobox)):
            widget.bind('<MouseWheel>', self.scroll)
        for child in widget.winfo_children():
            self.bind_wheel(child)

    def schedule_refresh(self):
        if self.filter_timer is not None:
            self.after_cancel(self.filter_timer)
        self.filter_timer = self.after(180, self.apply_filters)

    def apply_filters(self):
        self.filter_timer = None
        self.refresh()

    def cancel_refresh(self):
        if self.filter_timer is not None:
            self.after_cancel(self.filter_timer)
            self.filter_timer = None
        for row in self.rows.values():
            if row.timer is not None:
                row.after_cancel(row.timer)
                row.timer = None
