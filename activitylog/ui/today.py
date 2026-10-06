"""Scrollable, compact today's checklist, with no database dependency."""

import tkinter as tk
from tkinter import ttk
from .priority import priority_color


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

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)
        for label in self.labels:
            label.configure(wraplength=max(150, event.width - 42))

    def _scroll(self, event):
        if self.body.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def display(self, tasks, today):
        position = self.canvas.yview()[0]
        for child in self.body.winfo_children():
            child.destroy()
        self.checks.clear()
        self.labels.clear()
        for task in tasks:
            background = "#eaf4f0" if task.completed else "white"
            row = tk.Frame(self.body, background=background, padx=6, pady=6)
            row.pack(fill="x", pady=(0, 1))
            row.columnconfigure(1, weight=1)
            dot = tk.Canvas(row, width=12, height=18, background=background, highlightthickness=0)
            dot.create_oval(2, 6, 10, 14, fill=priority_color(task.priority, task.completed), outline="")
            dot.grid(row=0, column=0, sticky="n", pady=(3, 0))
            variable = tk.BooleanVar(value=task.completed)
            title = f"[{task.project_code}] {task.title}" if task.project_code else task.title
            check = tk.Checkbutton(row, text=title, variable=variable, anchor="w", justify="left",
                                  wraplength=max(150, self.canvas.winfo_width() - 42),
                                  font=("Microsoft YaHei UI", 10, "overstrike" if task.completed else "normal"),
                                  background=background, activebackground=background,
                                  foreground="#667085" if task.completed else "#253246",
                                  command=lambda identifier=task.id, value=variable: self.on_complete(identifier, value.get()))
            check.grid(row=0, column=1, columnspan=3, sticky="ew")
            detail = f"{task.priority} · {task.status}"
            tk.Label(row, text=detail, background=background, foreground="#667085",
                     font=("Microsoft YaHei UI", 9), anchor="w").grid(row=1, column=1, sticky="w", padx=(23, 0))
            for column, label, callback in ((2, "编辑", self.on_edit), (3, "移出", self.on_remove)):
                tk.Button(row, text=label, relief="flat", borderwidth=0, background=background,
                          foreground="#667085", font=("Microsoft YaHei UI", 9), cursor="hand2",
                          command=lambda identifier=task.id, action=callback: action(identifier)).grid(row=1, column=column)
            self.checks[task.id] = (variable, check)
            self.labels.append(check)
            self._bind_wheel(row)
        if not tasks:
            ttk.Label(self.body, text="暂无今日待办", foreground="#667085", padding=(6, 14)).pack(anchor="w")
        self.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(position)

    def _bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self._scroll)
        for child in widget.winfo_children():
            self._bind_wheel(child)
