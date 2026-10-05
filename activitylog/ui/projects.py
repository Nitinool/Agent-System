"""Compact project navigation and a table of shared project work items."""

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk

from ..projects import PROJECT_STATUSES, ProjectDraft
from ..tasks import TASK_STATUSES
from .priority import PriorityDots
from .task_editor import TaskDialog
from .milestone_editor import MilestoneDialog


class ProjectDialog(tk.Toplevel):
    def __init__(self, parent, service, on_saved, project=None):
        super().__init__(parent)
        self.title("编辑项目" if project else "新增项目")
        self.transient(parent)
        self.resizable(False, False)
        self.service, self.on_saved = service, on_saved
        self.identifier = project.id if project else None
        self.name_var = tk.StringVar(value=project.name if project else "")
        self.status_var = tk.StringVar(value=project.status if project else "进行中")
        self.error = tk.StringVar()
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="项目名称 *").grid(row=0, column=0, sticky="w", padx=(0, 14), pady=6)
        entry = ttk.Entry(body, textvariable=self.name_var, width=44)
        entry.grid(row=0, column=1, pady=6)
        ttk.Label(body, text="状态").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Combobox(body, textvariable=self.status_var, values=PROJECT_STATUSES, state="readonly",
                     width=16).grid(row=1, column=1, sticky="w", pady=6)
        ttk.Label(body, text="项目目标").grid(row=2, column=0, sticky="nw", pady=6)
        self.goal = tk.Text(body, width=44, height=4, wrap="word", font=("Microsoft YaHei UI", 10))
        self.goal.grid(row=2, column=1, pady=6)
        if project:
            self.goal.insert("1.0", project.goal)
        ttk.Label(body, textvariable=self.error, foreground="#b42318", wraplength=440).grid(
            row=3, column=0, columnspan=2, sticky="w")
        actions = ttk.Frame(body)
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="保存", command=self.submit).pack(side="right")
        ttk.Button(actions, text="取消", command=self.destroy).pack(side="right", padx=8)
        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()
        entry.focus_set()

    def submit(self):
        try:
            identifier = self.service.save(ProjectDraft(self.name_var.get(), self.goal.get("1.0", "end-1c"),
                                                        self.status_var.get()), self.identifier)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.destroy()
        self.on_saved(identifier)


class ProjectOverview(ttk.Frame):
    def __init__(self, parent, service):
        super().__init__(parent, padding=16)
        self.service = service
        self.selected_project_id = None
        self.summaries = {}
        self.displayed_tasks = {}
        self.milestones = ()
        self.scope = "stage"
        self.selected_milestone_id = None
        self.undo_state = None
        self.feedback = tk.StringVar()
        self.stage_choice = tk.StringVar()
        self.stage_acceptance = tk.StringVar()
        self.detail = tk.StringVar(value="选中事项查看验收条件和成果说明")
        self.show_history = tk.BooleanVar()
        self.show_backlog = tk.BooleanVar()
        self.filter_timer = None
        self.dots = PriorityDots(self)
        self.project_name = tk.StringVar(value="暂无项目")
        self.progress = tk.StringVar()
        self.goal = tk.StringVar()
        self.keyword = tk.StringVar()
        self.status_filter = tk.StringVar(value="全部状态")
        self.selected_status = tk.StringVar(value="待开始")
        self.error = tk.StringVar()
        ttk.Label(self, text="项目管理", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", pady=(0, 14))
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        left = ttk.Frame(body, width=210)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_projects(left)
        self._build_items(right)
        ttk.Label(self, textvariable=self.error, foreground="#b42318").pack(fill="x", pady=(6, 0))
        for variable in (self.keyword, self.status_filter):
            variable.trace_add("write", lambda *_: self.schedule_refresh())
        self.refresh()

    def _build_projects(self, parent):
        heading = ttk.Frame(parent)
        heading.pack(fill="x", pady=(0, 10))
        ttk.Label(heading, text="项目", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        self.add_project_button = ttk.Button(heading, text="＋ 新增", command=self.add_project)
        self.add_project_button.pack(side="right")
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)
        self.project_table = ttk.Treeview(container, columns=("name", "progress"), show="headings",
                                          selectmode="browse", height=12)
        self.project_table.heading("name", text="项目名称", anchor="w")
        self.project_table.heading("progress", text="完成", anchor="e")
        self.project_table.column("name", width=145, minwidth=100)
        self.project_table.column("progress", width=55, minwidth=45, stretch=False, anchor="e")
        scroll = ttk.Scrollbar(container, orient="vertical", command=self.project_table.yview)
        self.project_table.configure(yscrollcommand=scroll.set)
        self.project_table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.project_table.bind("<<TreeviewSelect>>", self._project_selected)
        self.project_table.bind("<Double-1>", lambda _: self.edit_project())
        self.project_table.bind("<Return>", lambda _: self.edit_project())
        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(8, 0))
        self.edit_project_button = ttk.Button(actions, text="编辑项目", command=self.edit_project, state="disabled")
        self.edit_project_button.pack(side="left")
        self.delete_project_button = ttk.Button(actions, text="删除项目", command=self.delete_project, state="disabled")
        self.delete_project_button.pack(side="right")

    def _build_items(self, parent):
        heading = ttk.Frame(parent)
        heading.pack(fill="x", pady=(0, 6))
        ttk.Label(heading, textvariable=self.project_name, font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        self.add_item_button = ttk.Button(heading, text="＋ 新增事项", command=self.add_item, state="disabled")
        self.add_item_button.pack(side="right")
        ttk.Label(heading, textvariable=self.progress, foreground="#667085").pack(side="right", padx=12)
        self.goal_label = ttk.Label(parent, textvariable=self.goal, foreground="#667085")
        self.goal_label.pack(fill="x", pady=(0, 10))
        self._build_stages(parent)
        filters = ttk.Frame(parent)
        filters.pack(fill="x", pady=(0, 10))
        ttk.Label(filters, text="搜索").pack(side="left", padx=(0, 8))
        ttk.Entry(filters, textvariable=self.keyword, width=24).pack(side="left", padx=(0, 10))
        ttk.Combobox(filters, textvariable=self.status_filter, values=("全部状态",) + TASK_STATUSES,
                     state="readonly", width=10).pack(side="left")
        ttk.Button(filters, text="清除", command=self.clear_filters).pack(side="left", padx=8)
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        self.table = ttk.Treeview(container, columns=("done", "title", "kind", "priority", "status", "date"),
                                  show=("tree", "headings"), selectmode="browse", style="Priority.Treeview")
        self.table.column("#0", width=24, minwidth=24, stretch=False)
        for key, label, width in (("done", "完成", 44), ("title", "事项", 280), ("kind", "类型", 65),
                                  ("priority", "优先级", 65), ("status", "状态", 80), ("date", "安排日期", 105)):
            self.table.heading(key, text=label, anchor="w")
            self.table.column(key, width=width, minwidth=120 if key == "title" else width,
                              stretch=key == "title", anchor="w")
        self.table.tag_configure("completed", foreground="#667085", background="#eaf4f0",
                                 font=("Microsoft YaHei UI", 9, "overstrike"))
        vertical = ttk.Scrollbar(container, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(container, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.bind("<<TreeviewSelect>>", lambda _: self._selection_changed())
        self.table.bind("<Button-1>", self._click_status)
        self.table.bind("<Double-1>", self._double_click)
        self.table.bind("<Return>", lambda _: self.edit_item())
        self.table.bind("<space>", lambda _: self.toggle_selected())
        self.table.bind("<Delete>", lambda _: self.delete_item())
        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(8, 0))
        self.edit_item_button = ttk.Button(actions, text="编辑", command=self.edit_item, state="disabled")
        self.edit_item_button.pack(side="left")
        self.delete_item_button = ttk.Button(actions, text="删除", command=self.delete_item, state="disabled")
        self.delete_item_button.pack(side="left", padx=8)
        self.arrange_button = ttk.Button(actions, text="安排今天", command=self.arrange_today, state="disabled")
        self.arrange_button.pack(side="left")
        self.status_combo = ttk.Combobox(actions, textvariable=self.selected_status, values=TASK_STATUSES,
                                         state="disabled", width=9)
        self.status_combo.pack(side="right")
        self.status_combo.bind("<<ComboboxSelected>>", lambda _: self.change_status())
        ttk.Label(actions, text="状态").pack(side="right", padx=8)
        self._build_details(parent)

    def _build_stages(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 6))
        self.stage_combo = ttk.Combobox(row, textvariable=self.stage_choice, state="readonly", width=22)
        self.stage_combo.pack(side="left")
        self.stage_combo.bind("<<ComboboxSelected>>", lambda _: self._stage_selected())
        self.add_stage_button = ttk.Button(row, text="＋阶段", command=self.add_milestone)
        self.add_stage_button.pack(side="left", padx=(8, 4))
        self.edit_stage_button = ttk.Button(row, text="编辑", command=self.edit_milestone)
        self.edit_stage_button.pack(side="left")
        self.delete_stage_button = ttk.Button(row, text="删除", command=self.delete_milestone)
        self.delete_stage_button.pack(side="left", padx=4)
        self.finish_stage_button = ttk.Button(row, text="确认验收", command=self.finish_milestone)
        self.finish_stage_button.pack(side="right")
        self.stage_progress = tk.StringVar()
        ttk.Label(parent, textvariable=self.stage_progress, foreground="#276943").pack(anchor="w")
        self.progress_bar = ttk.Progressbar(parent, maximum=100)
        self.progress_bar.pack(fill="x", pady=(3, 5))
        ttk.Label(parent, textvariable=self.stage_acceptance, foreground="#667085", wraplength=640).pack(
            fill="x", pady=(0, 8))

    def _build_details(self, parent):
        feedback = ttk.Frame(parent)
        feedback.pack(fill="x", pady=(5, 0))
        ttk.Label(feedback, textvariable=self.feedback, foreground="#276943", wraplength=580).pack(side="left")
        self.undo_button = ttk.Button(feedback, text="撤销", command=self.undo_completion, state="disabled")
        self.undo_button.pack(side="right")
        ttk.Label(parent, textvariable=self.detail, wraplength=660, justify="left").pack(fill="x", pady=(6, 4))
        folds = ttk.Frame(parent)
        folds.pack(fill="x")
        self.history_toggle = ttk.Checkbutton(folds, text="完成记录", variable=self.show_history, command=self._toggle_history)
        self.history_toggle.pack(side="left")
        self.backlog_toggle = ttk.Checkbutton(folds, text="未来想法", variable=self.show_backlog, command=self._toggle_backlog)
        self.backlog_toggle.pack(side="left", padx=12)
        self.history_frame = ttk.Frame(parent)
        self.history_table = ttk.Treeview(self.history_frame, columns=("time", "title", "state", "outcome"), show="headings", height=3)
        for key, label, width in (("time", "完成时间", 150), ("title", "事项", 200), ("state", "记录状态", 75), ("outcome", "成果说明", 180)):
            self.history_table.heading(key, text=label, anchor="w")
            self.history_table.column(key, width=width, minwidth=50, stretch=key in ("title", "outcome"))
        self.history_table.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(self.history_frame, command=self.history_table.yview)
        self.history_table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.history_table.bind("<Double-1>", lambda _: self._open_history_item())
        self.backlog_frame = ttk.Frame(parent)
        self.backlog_table = ttk.Treeview(self.backlog_frame, columns=("title", "status"), show="headings", height=3)
        self.backlog_table.heading("title", text="未来想法 / 未分阶段事项", anchor="w")
        self.backlog_table.heading("status", text="状态", anchor="w")
        self.backlog_table.column("title", width=400)
        self.backlog_table.column("status", width=90, stretch=False)
        self.backlog_table.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(self.backlog_frame, command=self.backlog_table.yview)
        self.backlog_table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.backlog_table.bind("<Double-1>", lambda _: self._open_backlog_item())

    def _toggle_history(self):
        if self.show_history.get():
            self.history_frame.pack(fill="x", pady=4)
        else:
            self.history_frame.pack_forget()

    def _toggle_backlog(self):
        if self.show_backlog.get():
            self.backlog_frame.pack(fill="x", pady=4)
        else:
            self.backlog_frame.pack_forget()

    def refresh(self, project_id=None, item_id=None):
        try:
            summaries = self.service.summaries()
        except sqlite3.Error as error:
            self.error.set(str(error))
            return
        self.summaries = {summary.project.id: summary for summary in summaries}
        selected = project_id if project_id is not None else self.selected_project_id
        previous_project = self.selected_project_id
        self.selected_project_id = selected if selected in self.summaries else next(iter(self.summaries), None)
        if previous_project != self.selected_project_id:
            self._reset_project_view()
        self.project_table.delete(*self.project_table.get_children())
        for summary in summaries:
            item = f"project-{summary.project.id}"
            self.project_table.insert("", "end", iid=item,
                                      values=(summary.project.name, f"{summary.completed}/{summary.total}"))
            if summary.project.id == self.selected_project_id:
                self.project_table.selection_set(item)
        self._load_items(item_id)

    def _project_selected(self, _event):
        selection = self.project_table.selection()
        if selection:
            identifier = int(selection[0].removeprefix("project-"))
            if identifier != self.selected_project_id:
                self.selected_project_id = identifier
                self._reset_project_view()
                self._load_items()

    def _reset_project_view(self):
        self.selected_milestone_id = None
        self.scope = "stage"
        self.undo_state = None
        self.feedback.set("")
        self.keyword.set("")
        self.status_filter.set("全部状态")
        self.cancel_refresh()

    def _load_items(self, identifier=None):
        summary = self.summaries.get(self.selected_project_id)
        try:
            self.milestones = self.service.milestones(summary.project.id) if summary else ()
            if self.selected_milestone_id not in {item.id for item in self.milestones}:
                self.selected_milestone_id = next((item.id for item in self.milestones if not item.completed_at),
                                                  self.milestones[-1].id if self.milestones else None)
            all_items = self.service.items(summary.project.id) if summary else ()
            items = self.service.items(summary.project.id, self.keyword.get(), self.status_filter.get()) if summary else ()
            if self.scope != "all":
                scope_id = self.selected_milestone_id if self.scope == "stage" else None
                items = tuple(task for task in items if task.milestone_id == scope_id)
            records = self.service.completion_records(summary.project.id) if summary else ()
            today_ids = {task.id for task in self.service.tasks.today_tasks()}
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.error.set("")
        self.project_name.set(summary.project.name[:24] if summary else "暂无项目")
        self.progress.set(f"{summary.project.status} · 已完成 {summary.completed}/{summary.total}" if summary else "")
        self.goal.set(summary.project.goal.splitlines()[0][:65] if summary and summary.project.goal else "")
        self._update_stages(all_items, summary)
        self.history_toggle.configure(text=f"完成记录 · {len(records)}")
        self.history_table.delete(*self.history_table.get_children())
        self.history_tasks = {}
        for record in records:
            key = f"completion-{record.id}"
            self.history_tasks[key] = record.task_id
            self.history_table.insert("", "end", iid=key, values=(record.completed_at[:19].replace('T', ' '),
                record.title, "已重新打开" if record.reopened_at else "已完成", record.outcome or ""))
        backlog = tuple(task for task in all_items if task.milestone_id is None)
        self.backlog_toggle.configure(text=f"未来想法 · {len(backlog)}")
        self.backlog_tasks = {f"backlog-{task.id}": task for task in backlog}
        self.backlog_table.delete(*self.backlog_table.get_children())
        for key, task in self.backlog_tasks.items():
            self.backlog_table.insert("", "end", iid=key, values=(task.title, task.status))
        enabled = "normal" if summary else "disabled"
        for button in (self.add_item_button, self.edit_project_button, self.delete_project_button):
            button.configure(state=enabled)
        selected = self._selected()
        selected_id = identifier if identifier is not None else (selected.id if selected else None)
        self.table.delete(*self.table.get_children())
        self.displayed_tasks.clear()
        self.today_ids = today_ids
        for task in items:
            item = f"task-{task.id}"
            self.displayed_tasks[item] = task
            self.table.insert("", "end", iid=item, image=self.dots.for_task(task),
                              values=("☑" if task.completed else "☐", task.title, task.kind, task.priority, task.status,
                                      task.planned_on.isoformat() if task.planned_on else "待安排"),
                              tags=("completed",) if task.completed else ())
            if task.id == selected_id:
                self.table.selection_set(item)
                self.table.see(item)
        self._selection_changed()

    def _milestone(self):
        return next((item for item in self.milestones if item.id == self.selected_milestone_id), None)

    def _update_stages(self, all_items, summary):
        labels = tuple(f"{'✓ ' if item.completed_at else ''}{item.name} ({item.completed}/{item.total})" for item in self.milestones)
        self.stage_combo.configure(values=labels + ("未来想法 / 未分阶段", "全部事项"), state="readonly" if summary else "disabled")
        index = next((i for i, item in enumerate(self.milestones) if item.id == self.selected_milestone_id), len(labels))
        if self.scope != "stage" or not self.milestones:
            index = len(labels) + (1 if self.scope == "all" else 0)
        self.stage_combo.current(index)
        milestone = self._milestone() if self.scope == "stage" else None
        scoped = tuple(task for task in all_items if self.scope == "all" or task.milestone_id == (milestone.id if milestone else None))
        done, total = sum(task.completed for task in scoped), len(scoped)
        active = sum(task.status == '进行中' for task in scoped)
        name = milestone.name if milestone else ("全部事项" if self.scope == "all" else "未来想法 / 未分阶段")
        self.stage_progress.set(f"{name} · 已完成 {done}/{total} · 进行中 {active} 项" +
                                (" · 建议同时不超过 2 项" if active > 2 else ""))
        self.progress_bar.configure(value=100 * done / total if total else 0)
        self.stage_acceptance.set((f"验收：{self._preview(milestone.acceptance, 110) or '未填写'}" +
                                  (f" · 已达成 {milestone.completed_at[:10]}" if milestone.completed_at else "")) if milestone else "")
        self.add_stage_button.configure(state="normal" if summary else "disabled")
        for button in (self.edit_stage_button, self.delete_stage_button):
            button.configure(state="normal" if milestone else "disabled")
        self.finish_stage_button.configure(state="normal" if milestone and total and done == total and not milestone.completed_at else "disabled")
        self.undo_button.configure(state="normal" if self.undo_state else "disabled")

    def _stage_selected(self):
        index = self.stage_combo.current()
        self.scope = "stage" if index < len(self.milestones) else ("backlog" if index == len(self.milestones) else "all")
        if self.scope == "stage":
            self.selected_milestone_id = self.milestones[index].id
        self._load_items()

    def _selected(self):
        selection = self.table.selection()
        return self.displayed_tasks.get(selection[0]) if selection else None

    def _selection_changed(self):
        task = self._selected()
        for button in (self.edit_item_button, self.delete_item_button):
            button.configure(state="normal" if task else "disabled")
        self.arrange_button.configure(state="normal" if task and task.id not in self.today_ids else "disabled")
        self.status_combo.configure(state="readonly" if task else "disabled")
        if task:
            self.selected_status.set(task.status)
            completed = f"\n完成：{task.completed_at[:19].replace('T', ' ')}" if task.completed_at else ""
            notes = f"\n备注：{self._preview(task.notes, 80)}" if task.notes else ""
            self.detail.set(f"{task.title}\n验收：{self._preview(task.acceptance, 100) or '未填写'}\n成果：{self._preview(task.outcome, 100) or '未填写'}{notes}{completed}")
        else:
            self.detail.set("选中事项查看验收条件和成果说明")

    @staticmethod
    def _preview(text, limit):
        text = ' '.join(text.split())
        return text if len(text) <= limit else text[:limit] + '…（编辑查看全文）'

    def add_project(self):
        return ProjectDialog(self.winfo_toplevel(), self.service, lambda identifier: self.refresh(identifier))

    def edit_project(self):
        summary = self.summaries.get(self.selected_project_id)
        if summary:
            return ProjectDialog(self.winfo_toplevel(), self.service, lambda identifier: self.refresh(identifier), summary.project)

    def delete_project(self):
        summary = self.summaries.get(self.selected_project_id)
        if summary and messagebox.askyesno("删除项目", f"删除“{summary.project.name}”？事项会保留，并解除所属项目。",
                                          parent=self.winfo_toplevel()):
            self._run(lambda: self.service.delete(summary.project.id))

    def add_item(self):
        if self.selected_project_id is not None:
            return self._open_editor(project_id=self.selected_project_id,
                milestone_id=self.selected_milestone_id if self.scope == "stage" else None)

    def _open_editor(self, **options):
        try:
            return TaskDialog(self.winfo_toplevel(), self.service.tasks, self._saved_item, None, **options)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))

    def edit_item(self):
        task = self._selected()
        if task:
            return self._open_editor(task=task, in_today=task.id in self.today_ids)

    def _saved_item(self, identifier):
        try:
            task = self.service.tasks.get(identifier)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.clear_filters(refresh=False)
        self.refresh(task.project_id, identifier)
        self.scope = "stage" if task.milestone_id else "backlog"
        self.selected_milestone_id = task.milestone_id
        self._load_items(identifier)

    def add_milestone(self):
        if self.selected_project_id is not None:
            return MilestoneDialog(self.winfo_toplevel(), self.service, self.selected_project_id, self._saved_milestone)

    def edit_milestone(self):
        milestone = self._milestone()
        if milestone and self.scope == "stage":
            return MilestoneDialog(self.winfo_toplevel(), self.service, self.selected_project_id, self._saved_milestone, milestone)

    def _saved_milestone(self, identifier):
        self.selected_milestone_id, self.scope = identifier, "stage"
        self.refresh()

    def delete_milestone(self):
        milestone = self._milestone()
        if milestone and messagebox.askyesno("删除里程碑", f"删除“{milestone.name}”？事项会移到未来想法中。", parent=self.winfo_toplevel()):
            self._run(lambda: self.service.delete_milestone(milestone.id))

    def finish_milestone(self):
        milestone = self._milestone()
        if milestone and messagebox.askyesno("确认阶段验收", f"确认“{milestone.name}”已实现以下成果？\n\n{milestone.acceptance or '本阶段事项全部完成'}", parent=self.winfo_toplevel()):
            self._run(lambda: self.service.finish_milestone(milestone.id))
            if not self.error.get():
                self.feedback.set(f"✓ 里程碑已达成：{milestone.name}")

    def _open_history_item(self):
        selected = self.history_table.selection()
        if selected:
            self._open_task_id(self.history_tasks[selected[0]])

    def _open_backlog_item(self):
        selected = self.backlog_table.selection()
        if selected:
            self._open_task_id(self.backlog_tasks[selected[0]].id)

    def _open_task_id(self, identifier):
        try:
            task = self.service.tasks.get(identifier)
            self._open_editor(task=task, in_today=self.service.tasks.is_in_today(identifier))
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))

    def _run(self, action, identifier=None):
        try:
            action()
        except (ValueError, sqlite3.Error) as error:
            self._selection_changed()
            self.error.set(str(error))
            return
        self.refresh(item_id=identifier)

    def arrange_today(self):
        task = self._selected()
        if task:
            self._run(lambda: self.service.tasks.arrange_today(task.id), task.id)

    def change_status(self):
        task = self._selected()
        if task:
            self._change_task_status(task, self.selected_status.get())

    def toggle_selected(self):
        task = self._selected()
        if task:
            self._change_task_status(task, task.resume_status if task.completed else "已完成")
        return "break"

    def _change_task_status(self, task, status):
        self._run(lambda: self.service.tasks.set_status(task.id, status), task.id)
        if not self.error.get() and status == "已完成" and not task.completed:
            self.undo_state = (task.id, task.status)
            self.feedback.set(f"✓ 已完成：{task.title}")
            self.undo_button.configure(state="normal")
        elif status != task.status:
            self.undo_state = None
            self.feedback.set("")
            self.undo_button.configure(state="disabled")

    def undo_completion(self):
        if self.undo_state:
            identifier, previous = self.undo_state
            try:
                task = self.service.tasks.get(identifier)
                if not task.completed:
                    raise ValueError("事项状态已改变，请刷新查看。")
                self.service.tasks.set_status(identifier, previous)
            except (ValueError, sqlite3.Error) as error:
                self.error.set(str(error))
                return
            self.undo_state = None
            self.feedback.set("已撤销完成，恢复原来的状态")
            self.refresh(item_id=identifier)

    def _click_status(self, event):
        if self.table.identify_region(event.x, event.y) == "cell" and self.table.identify_column(event.x) == "#1":
            item = self.table.identify_row(event.y)
            if item in self.displayed_tasks:
                self.table.selection_set(item)
                return self.toggle_selected()

    def _double_click(self, event):
        if self.table.identify_region(event.x, event.y) == "cell" and self.table.identify_column(event.x) != "#1":
            item = self.table.identify_row(event.y)
            if item in self.displayed_tasks:
                self.table.selection_set(item)
                self.edit_item()
        return "break"

    def delete_item(self):
        task = self._selected()
        if task and messagebox.askyesno("删除事项", f"删除“{task.title}”？项目、日历和今日待办中的该事项都会删除。",
                                       parent=self.winfo_toplevel()):
            self._run(lambda: self.service.tasks.delete(task.id), task.id)

    def schedule_refresh(self):
        self.cancel_refresh()
        self.filter_timer = self.after(180, self._apply_filters)

    def _apply_filters(self):
        self.filter_timer = None
        self._load_items()

    def cancel_refresh(self):
        if self.filter_timer is not None:
            self.after_cancel(self.filter_timer)
            self.filter_timer = None

    def clear_filters(self, refresh=True):
        self.keyword.set("")
        self.status_filter.set("全部状态")
        self.cancel_refresh()
        if refresh:
            self._load_items()
