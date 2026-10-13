"""Scrollable, compact today's checklist, with no database dependency."""

import tkinter as tk
from tkinter import ttk
from .task_colors import task_color


class TodayList(ttk.Frame):
    def __init__(self, parent, on_complete, on_edit, on_remove):
        super().__init__(parent)
        self.on_complete, self.on_edit, self.on_remove = on_complete, on_edit, on_remove
        self.canvas = tk.Canvas(self, background="white", highlightthickness=0, width=300)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.body = tk.Frame(self.canvas, background="white")
        self.window = self.canvas.create_window(0, 0, anchor="nw", window=self.body)
        self.body.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<MouseWheel>", self._scroll)
        self.checks = {}
        self.labels = []
        self.rows = {}
        self.empty = None
        self.layout_timer = None
        self.wrap_width = None
        self.bind('<Destroy>', self._destroyed, add='+')

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)
        if self.wrap_width == event.width:
            return
        self.wrap_width = event.width
        for label in self.labels:
            label.configure(wraplength=max(150, event.width - 144))

    def _scroll(self, event):
        if self.body.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def display(self, tasks, today):
        tasks = tuple(tasks)
        previous = tuple(value[0] for value in self.rows.values())
        # Restore optimistic checkbox state even when a failed write leaves data unchanged.
        for task in tasks:
            if task.id in self.checks:
                self.checks[task.id][0].set(task.completed)
        if tasks == previous and (tasks or self.empty is not None):
            return
        position = self.canvas.yview()[0]
        wanted = {task.id for task in tasks}
        for identifier in set(self.rows) - wanted:
            self.rows.pop(identifier)[1].destroy()
            self.checks.pop(identifier)
        if self.empty is not None:
            self.empty.destroy()
            self.empty = None
        ordered = {}
        for task in tasks:
            cached = self.rows.get(task.id)
            if cached is not None and cached[0] == task:
                ordered[task.id] = cached
                continue
            if cached is not None:
                cached[1].destroy()
            background = "#eaf4f0" if task.completed else "white"
            row = tk.Frame(self.body, background=background, padx=6, pady=4)
            row.pack(fill="x", pady=(0, 1))
            row.columnconfigure(1, weight=1)
            dot = tk.Canvas(row, width=12, height=18, background=background, highlightthickness=0)
            dot.create_oval(2, 6, 10, 14, fill=task_color(task), outline="")
            dot.grid(row=0, column=0, sticky="n", pady=(3, 0))
            variable = tk.BooleanVar(value=task.completed)
            title = f"[{task.project_code}] {task.title}" if task.project_code else task.title
            check = tk.Checkbutton(row, text=title, variable=variable, anchor="w", justify="left",
                                  wraplength=max(150, self.canvas.winfo_width() - 144),
                                  font=("Microsoft YaHei UI", 10, "overstrike" if task.completed else "normal"),
                                  background=background, activebackground=background,
                                  foreground="#667085" if task.completed else "#253246",
                                  command=lambda identifier=task.id, value=variable: self.on_complete(identifier, value.get()))
            check.grid(row=0, column=1, sticky="ew")
            if task.category != '其他':
                tk.Label(row, text=task.category, background=background, foreground="#667085",
                         font=("Microsoft YaHei UI", 9), anchor="w").grid(row=1, column=1, sticky="w", padx=(23, 0))
            for column, label, callback in ((2, "编辑", self.on_edit), (3, "移出", self.on_remove)):
                tk.Button(row, text=label, relief="flat", borderwidth=0, background=background,
                          foreground="#667085", font=("Microsoft YaHei UI", 9), cursor="hand2",
                          command=lambda identifier=task.id, action=callback: action(identifier)).grid(row=0, column=column)
            self.checks[task.id] = (variable, check)
            ordered[task.id] = (task, row)
            self._bind_wheel(row)
        self.rows = ordered
        # Reorder without unmapping retained frames (and all their native children).
        anchor = None
        for task, row in reversed(tuple(self.rows.values())):
            row.pack(fill='x', pady=(0, 1), **({'before': anchor} if anchor is not None else {}))
            anchor = row
        self.labels = [self.checks[task.id][1] for task in tasks]
        if not tasks:
            self.empty = ttk.Label(self.body, text="暂无今日待办", foreground="#667085", padding=(6, 14))
            self.empty.pack(anchor="w")
        if self.layout_timer is not None:
            self.after_cancel(self.layout_timer)
        self.layout_timer = self.after_idle(lambda: self._restore_scroll(position))

    def _restore_scroll(self, position):
        self.layout_timer = None
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(position)

    def _destroyed(self, event):
        if event.widget is self and self.layout_timer is not None:
            self.after_cancel(self.layout_timer)
            self.layout_timer = None

    def _bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self._scroll)
        for child in widget.winfo_children():
            self._bind_wheel(child)
