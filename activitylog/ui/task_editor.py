"""Shared editor used by calendar items and project work items."""

import sqlite3
import tkinter as tk
from tkinter import ttk

from ..tasks import TASK_CATEGORIES, TASK_KINDS, TASK_PRIORITIES, TASK_STATUSES, TaskDraft


class TaskDialog(tk.Toplevel):
    def __init__(self, parent, service, on_saved, selected, task=None, in_today=False, project_id=None, milestone_id=None):
        projects = service.projects()
        selected_project = task.project_id if task else project_id
        milestones = service.milestones(selected_project)
        super().__init__(parent)
        self.title("编辑事项" if task else "新增事项")
        self.transient(parent)
        self.resizable(False, False)
        self.service, self.on_saved = service, on_saved
        self.identifier = task.id if task else None
        planned = task.planned_on if task else selected
        self.title_var = tk.StringVar(value=task.title if task else "")
        self.date_var = tk.StringVar(value=planned.isoformat() if planned else "")
        self.category_var = tk.StringVar(value=task.category if task else "其他")
        self.kind_var = tk.StringVar(value=task.kind if task else "任务")
        self.priority_var = tk.StringVar(value=task.priority if task else "普通")
        self.status_var = tk.StringVar(value=task.status if task else "待开始")
        self.today_var = tk.BooleanVar(value=in_today)
        self.error = tk.StringVar()
        self.projects = projects
        self.milestones = milestones
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        for index, (label, variable) in enumerate((("事项名称 *", self.title_var),
                                                  ("安排日期 (YYYY-MM-DD，可留空)", self.date_var))):
            ttk.Label(body, text=label).grid(row=index, column=0, sticky="w", padx=(0, 14), pady=5)
            entry = ttk.Entry(body, textvariable=variable, width=42)
            entry.grid(row=index, column=1, sticky="ew", pady=5)
            if index == 0:
                self.title_entry = entry
        ttk.Label(body, text="所属项目").grid(row=2, column=0, sticky="w", pady=5)
        self.project_combo = ttk.Combobox(body, values=("不属于项目",) + tuple(project.name for project in self.projects),
                                          state="readonly", width=40)
        self.project_combo.grid(row=2, column=1, sticky="ew", pady=5)
        self.project_combo.current(next((index + 1 for index, project in enumerate(self.projects)
                                         if project.id == selected_project), 0))
        ttk.Label(body, text="里程碑").grid(row=3, column=0, sticky="w", pady=5)
        self.milestone_combo = ttk.Combobox(body, state="readonly", width=40)
        self.milestone_combo.grid(row=3, column=1, sticky="ew", pady=5)
        self._show_milestones(task.milestone_id if task else milestone_id)
        self.project_combo.bind("<<ComboboxSelected>>", lambda _: self._project_changed())
        for row, label, variable, values in ((4, "类型", self.kind_var, TASK_KINDS),
                                             (5, "优先级", self.priority_var, TASK_PRIORITIES),
                                             (6, "状态", self.status_var, TASK_STATUSES),
                                             (7, "分类", self.category_var, TASK_CATEGORIES)):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Combobox(body, textvariable=variable, values=values, state="readonly", width=16).grid(
                row=row, column=1, sticky="w", pady=5)
        ttk.Checkbutton(body, text="加入今日待办", variable=self.today_var).grid(row=8, column=1, sticky="w", pady=5)
        for row, label, attribute in ((9, "验收条件", "acceptance"), (10, "成果说明", "outcome"), (11, "备注", "notes")):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="nw", pady=4)
            text = tk.Text(body, width=42, height=2, wrap="word", font=("Microsoft YaHei UI", 10))
            text.grid(row=row, column=1, sticky="ew", pady=4)
            setattr(self, attribute, text)
            if task:
                text.insert("1.0", getattr(task, attribute))
        ttk.Label(body, textvariable=self.error, foreground="#b42318", wraplength=500).grid(
            row=12, column=0, columnspan=2, sticky="w")
        actions = ttk.Frame(body)
        actions.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="保存", command=self.submit).pack(side="right")
        ttk.Button(actions, text="取消", command=self.destroy).pack(side="right", padx=8)
        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()
        self.title_entry.focus_set()

    def _project_id(self):
        index = self.project_combo.current()
        return self.projects[index - 1].id if index > 0 else None

    def _show_milestones(self, selected=None):
        self.milestone_combo.configure(values=("未来想法 / 未分阶段",) + tuple(item.name for item in self.milestones))
        self.milestone_combo.current(next((index + 1 for index, item in enumerate(self.milestones)
                                          if item.id == selected), 0))

    def _project_changed(self):
        try:
            self.milestones = self.service.milestones(self._project_id())
            self._show_milestones()
            self.error.set("")
        except (ValueError, sqlite3.Error) as error:
            self.milestones = ()
            self._show_milestones()
            self.error.set(str(error))

    def submit(self):
        project_id = self._project_id()
        # Resolve against the currently selected project, including programmatic changes.
        if any(item.project_id != project_id for item in self.milestones):
            self._project_changed()
        index = self.milestone_combo.current()
        milestone_id = self.milestones[index - 1].id if index > 0 else None
        draft = TaskDraft(self.title_var.get(), self.date_var.get(), self.category_var.get(),
                          self.notes.get("1.0", "end-1c"), self.priority_var.get(), self.kind_var.get(),
                          self.status_var.get(), project_id, milestone_id,
                          self.acceptance.get("1.0", "end-1c"), self.outcome.get("1.0", "end-1c"))
        try:
            identifier = self.service.save(draft, self.identifier, in_today=self.today_var.get())
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.destroy()
        self.on_saved(identifier)
