"""Full-width month calendar and dated task editing; Today lives on Home."""

from datetime import date
import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk

from ..task_service import TaskService
from .calendar import MonthCalendar
from .task_editor import TaskDialog
from .task_colors import TaskDots


class TaskOverview(ttk.Frame):
    def __init__(self, parent, service: TaskService):
        super().__init__(parent, padding=16)
        self.service = service
        self.selected_date = service.today()
        self.year, self.month = self.selected_date.year, self.selected_date.month
        self.snapshot = None
        self.show_unscheduled = False
        self.dots = TaskDots(self)
        self.displayed_tasks = {}
        self.day_timer = None
        self.on_refresh = None
        self.total_text = tk.StringVar()
        self.month_text = tk.StringVar()
        self.unscheduled_text = tk.StringVar()
        self.selected_text = tk.StringVar()
        self.error = tk.StringVar()
        ttk.Label(self, text="事项管理", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", pady=(0, 14))
        left = ttk.Frame(self)
        left.pack(fill='both', expand=True)
        self._build_calendar(left)
        ttk.Label(self, textvariable=self.error, foreground="#b42318").pack(fill="x", pady=(4, 0))
        self.refresh()
        self.day_timer = self.after(30000, self._check_day)

    def _build_calendar(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=3)
        parent.rowconfigure(4, weight=1)
        heading = ttk.Frame(parent)
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(heading, text="全部事项", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Label(heading, textvariable=self.total_text, foreground="#667085").pack(side="left", padx=10)
        self.add_button = ttk.Button(heading, text="＋ 新增事项", command=self.add_task)
        self.add_button.pack(side="right")
        toolbar = ttk.Frame(parent)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ttk.Button(toolbar, text="‹", width=3, command=lambda: self.move_month(-1)).pack(side="left")
        ttk.Label(toolbar, textvariable=self.month_text, font=("Microsoft YaHei UI", 11)).pack(side="left", padx=12)
        ttk.Button(toolbar, text="›", width=3, command=lambda: self.move_month(1)).pack(side="left")
        ttk.Button(toolbar, textvariable=self.unscheduled_text, command=self.select_unscheduled).pack(side="left", padx=10)
        ttk.Button(toolbar, text="今天", command=self.go_today).pack(side="right")
        self.calendar = MonthCalendar(parent, self.select_date, self.add_task)
        self.calendar.grid(row=2, column=0, sticky="nsew")
        ttk.Label(parent, textvariable=self.selected_text, font=("Microsoft YaHei UI", 10, "bold")).grid(
            row=3, column=0, sticky="w", pady=(14, 6))
        container = ttk.Frame(parent)
        container.grid(row=4, column=0, sticky="nsew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        self.table = ttk.Treeview(container, columns=("done", "title", "category", "today"),
                                  show=("tree", "headings"), selectmode="browse", height=6, style="Priority.Treeview")
        self.table.column("#0", width=24, minwidth=24, stretch=False)
        for key, label, width in (("done", "完成", 48), ("title", "事项", 300),
                                  ("category", "分类", 65), ("today", "今日安排", 90)):
            self.table.heading(key, text=label, anchor="w")
            self.table.column(key, width=width, minwidth=width if key != "title" else 100,
                              stretch=key == "title", anchor="w")
        self.table.tag_configure("completed", foreground="#667085", background="#eaf4f0",
                                 font=("Microsoft YaHei UI", 9, "overstrike"))
        scroll = ttk.Scrollbar(container, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.table.bind("<<TreeviewSelect>>", lambda _: self._selection_changed())
        self.table.bind("<Button-1>", self._click_status)
        self.table.bind("<Double-1>", self._double_click)
        self.table.bind("<Return>", lambda _: self.edit_task())
        self.table.bind("<space>", lambda _: self.toggle_selected())
        self.table.bind("<Delete>", lambda _: self.delete_task())
        actions = ttk.Frame(parent)
        actions.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.edit_button = ttk.Button(actions, text="编辑", command=self.edit_task, state="disabled")
        self.edit_button.pack(side="left")
        self.delete_button = ttk.Button(actions, text="删除", command=self.delete_task, state="disabled")
        self.delete_button.pack(side="left", padx=8)
        self.arrange_button = ttk.Button(actions, text="安排今天", command=self.arrange_today, state="disabled")
        self.arrange_button.pack(side="right")

    def refresh(self, identifier=None):
        try:
            snapshot = self.service.snapshot(self.year, self.month, self.selected_date)
        except (sqlite3.Error, ValueError) as error:
            self.error.set(str(error))
            return
        self.snapshot = snapshot
        self.error.set("")
        self._display(identifier)
        if self.on_refresh:
            self.on_refresh()

    def _display(self, identifier=None):
        snapshot = self.snapshot
        rows = snapshot.unscheduled_tasks if self.show_unscheduled else snapshot.selected_tasks
        self.total_text.set(f"{snapshot.total} 项")
        self.month_text.set(f"{self.year}年 {self.month}月")
        self.unscheduled_text.set(f"待安排 {len(snapshot.unscheduled_tasks)}")
        label = "待安排" if self.show_unscheduled else f"{self.selected_date:%m月%d日}"
        self.selected_text.set(f"{label} · {len(rows)} 项")
        self.calendar.display(self.year, self.month, self.selected_date, snapshot.today, snapshot.calendar_tasks)
        today_ids = {task.id for task in snapshot.today_tasks}
        selected = self.table.selection()
        selected_id = identifier if identifier is not None else (
            self.displayed_tasks[selected[0]].id if selected and selected[0] in self.displayed_tasks else None)
        position = self.table.yview()[0]
        self.table.delete(*self.table.get_children())
        self.displayed_tasks.clear()
        for task in rows:
            item = f"task-{task.id}"
            self.displayed_tasks[item] = task
            self.table.insert("", "end", iid=item, image=self.dots.for_task(task),
                              values=("☑" if task.completed else "☐", task.title,
                              task.category, "已在今天" if task.id in today_ids else ""),
                              tags=("completed",) if task.completed else ())
            if task.id == selected_id:
                self.table.selection_set(item)
        self.table.yview_moveto(position)
        self._selection_changed()

    def _selected(self):
        selected = self.table.selection()
        return self.displayed_tasks.get(selected[0]) if selected else None

    def _selection_changed(self):
        task = self._selected()
        state = "normal" if task else "disabled"
        self.edit_button.configure(state=state)
        self.delete_button.configure(state=state)
        included = task and self.snapshot and any(item.id == task.id for item in self.snapshot.today_tasks)
        self.arrange_button.configure(state="normal" if task and not included else "disabled")

    def select_date(self, day):
        self.show_unscheduled = False
        self.selected_date = day
        self.year, self.month = day.year, day.month
        self.refresh()

    def move_month(self, amount):
        ordinal = self.year * 12 + self.month - 1 + amount
        year, month = divmod(ordinal, 12)
        if 1 <= year <= 9999:
            self.show_unscheduled = False
            self.year, self.month = year, month + 1
            self.selected_date = date(year, month + 1, 1)
            self.refresh()

    def go_today(self):
        self.select_date(self.service.today())

    def add_task(self):
        return self._open_editor(selected=None if self.show_unscheduled else self.selected_date)

    def _open_editor(self, **options):
        try:
            return TaskDialog(self.winfo_toplevel(), self.service, self._saved, **options)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))

    def select_unscheduled(self):
        self.show_unscheduled = True
        self.refresh()

    def edit_task(self, identifier=None):
        task = self._selected()
        identifier = identifier if identifier is not None else (task.id if task else None)
        if identifier is None:
            return
        try:
            task = self.service.get(identifier)
            in_today = self.service.is_in_today(identifier)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        return self._open_editor(selected=self.selected_date, task=task, in_today=in_today)

    def _saved(self, identifier):
        try:
            task = self.service.get(identifier)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.show_unscheduled = task.planned_on is None
        if task.planned_on:
            self.selected_date = task.planned_on
            self.year, self.month = task.planned_on.year, task.planned_on.month
        self.refresh(identifier)

    def _run(self, action, identifier):
        try:
            action()
        except (ValueError, sqlite3.Error) as error:
            if self.snapshot:
                self._display(identifier)
            self.error.set(str(error))
            return False
        self.refresh(identifier)
        return True

    def arrange_today(self):
        task = self._selected()
        if task:
            if self._run(lambda: self.service.arrange_today(task.id), task.id) and task.planned_on is None:
                self._saved(task.id)

    def complete_task(self, identifier, completed):
        self._run(lambda: self.service.complete(identifier, completed), identifier)

    def toggle_selected(self):
        task = self._selected()
        if task:
            self.complete_task(task.id, not task.completed)
        return "break"

    def _click_status(self, event):
        if self.table.identify_region(event.x, event.y) != "cell" or self.table.identify_column(event.x) != "#1":
            return
        item = self.table.identify_row(event.y)
        task = self.displayed_tasks.get(item)
        if task:
            self.table.selection_set(item)
            self.complete_task(task.id, not task.completed)
            return "break"

    def _double_click(self, event):
        if self.table.identify_region(event.x, event.y) == "cell" and self.table.identify_column(event.x) != "#1":
            item = self.table.identify_row(event.y)
            if item:
                self.table.selection_set(item)
                self.edit_task()
        return "break"

    def delete_task(self):
        task = self._selected()
        if task and messagebox.askyesno("删除事项", f"删除“{task.title}”？日历和今日待办中的该事项都会删除。",
                                       parent=self.winfo_toplevel()):
            self._run(lambda: self.service.delete(task.id), task.id)

    def _check_day(self):
        self.day_timer = None
        if self.snapshot is None or self.service.today() != self.snapshot.today:
            self.refresh()
        self.day_timer = self.after(30000, self._check_day)

    def cancel_refresh(self):
        if self.day_timer is not None:
            self.after_cancel(self.day_timer)
            self.day_timer = None
