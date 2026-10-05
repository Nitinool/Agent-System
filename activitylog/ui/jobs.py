"""Compact application table and a single editor with reusable name history."""

from datetime import date
import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from ..job_service import JobService
from ..jobs import APPLICATION_STATUSES, ApplicationDraft, ApplicationRow, application_rows


class ApplicationDialog(tk.Toplevel):
    def __init__(self, parent, service: JobService, on_saved, row: ApplicationRow | None = None):
        super().__init__(parent)
        self.title("编辑已投岗位" if row else "新增已投岗位")
        self.transient(parent)
        self.resizable(False, False)
        self.service = service
        self.on_saved = on_saved
        self.identifier = row.application.id if row else None
        application = row.application if row else None
        history = service.history()
        self.company_var = tk.StringVar(value=row.company.name if row else "")
        self.title_var = tk.StringVar(value=application.title if application else "")
        self.date_var = tk.StringVar(value=application.applied_on.isoformat() if application else date.today().isoformat())
        self.status_var = tk.StringVar(value=application.status if application else "已投递")
        self.url_var = tk.StringVar(value=application.url if application else "")
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        self.company_combo = self._history_field(body, 0, "公司 *", self.company_var, history.companies)
        self.title_combo = self._history_field(body, 1, "岗位名称 *", self.title_var, history.titles)
        fields = (("投递日期 (YYYY-MM-DD) *", self.date_var), ("岗位链接", self.url_var))
        for index, (label, variable) in enumerate(fields, start=2):
            ttk.Label(body, text=label).grid(row=index, column=0, sticky="w", padx=(0, 14), pady=5)
            ttk.Entry(body, textvariable=variable, width=48).grid(row=index, column=1, sticky="ew", pady=5)
        ttk.Label(body, text="进度").grid(row=4, column=0, sticky="w", pady=5)
        ttk.Combobox(body, textvariable=self.status_var, values=APPLICATION_STATUSES, state="readonly",
                     width=20).grid(row=4, column=1, sticky="w", pady=5)
        ttk.Label(body, text="备注").grid(row=5, column=0, sticky="nw", pady=5)
        self.notes = tk.Text(body, height=5, width=48, wrap="word", font=("Microsoft YaHei UI", 10),
                             relief="solid", borderwidth=1)
        self.notes.grid(row=5, column=1, sticky="ew", pady=5)
        if application:
            self.notes.insert("1.0", application.notes)
        self.error = tk.StringVar()
        ttk.Label(body, textvariable=self.error, foreground="#b42318", wraplength=510).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(5, 0))
        actions = ttk.Frame(body)
        actions.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="保存", command=self.submit).pack(side="right")
        ttk.Button(actions, text="取消", command=self.destroy).pack(side="right", padx=10)
        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()
        self.company_combo.focus_set()

    @staticmethod
    def _history_field(body, index, label, variable, values):
        ttk.Label(body, text=label).grid(row=index, column=0, sticky="w", padx=(0, 14), pady=5)
        combo = ttk.Combobox(body, textvariable=variable, values=values, state="normal", width=48)
        combo.grid(row=index, column=1, sticky="ew", pady=5)
        return combo

    def submit(self):
        draft = ApplicationDraft(self.title_var.get(), self.date_var.get(), self.status_var.get(),
                                 self.url_var.get(), self.notes.get("1.0", "end-1c"))
        try:
            identifier = self.service.save_application(self.company_var.get(), draft, self.identifier)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.destroy()
        self.on_saved(identifier)


class JobOverview(ttk.Frame):
    def __init__(self, parent, service: JobService):
        super().__init__(parent, padding=16)
        self.service = service
        self.filter_timer = None
        self.displayed_rows = {}
        self.keyword = tk.StringVar()
        self.status_filter = tk.StringVar(value="全部进度")
        self.summary = tk.StringVar()
        self.count = tk.StringVar()
        self.error = tk.StringVar()
        self._build_toolbar()
        self._build_table()
        self.refresh()
        for variable in (self.keyword, self.status_filter):
            variable.trace_add("write", lambda *_: self.schedule_refresh())

    def _build_toolbar(self):
        heading = ttk.Frame(self)
        heading.pack(fill="x", pady=(0, 12))
        ttk.Label(heading, text="求职一览", font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        ttk.Label(heading, textvariable=self.summary, foreground="#475467").pack(side="left", padx=18)
        self.add_button = ttk.Button(heading, text="＋ 新增已投岗位", command=self.add_application)
        self.add_button.pack(side="right")
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Label(toolbar, text="搜索").pack(side="left", padx=(0, 8))
        ttk.Entry(toolbar, textvariable=self.keyword, width=28).pack(side="left", padx=(0, 12))
        ttk.Combobox(toolbar, textvariable=self.status_filter, values=("全部进度",) + APPLICATION_STATUSES,
                     state="readonly", width=13).pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="清除", command=self.clear_filters).pack(side="left")
        self.delete_button = ttk.Button(toolbar, text="删除", state="disabled", command=self.delete_application)
        self.delete_button.pack(side="right")
        self.link_button = ttk.Button(toolbar, text="打开链接", state="disabled", command=self.open_link)
        self.link_button.pack(side="right", padx=8)
        self.edit_button = ttk.Button(toolbar, text="编辑", state="disabled", command=self.edit_application)
        self.edit_button.pack(side="right")

    def _build_table(self):
        style = ttk.Style(self)
        style.configure("Jobs.Treeview", rowheight=26)
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        self.table = ttk.Treeview(container, columns=("company", "title", "date", "status", "url", "notes"),
                                 show="headings", selectmode="browse", style="Jobs.Treeview", height=20)
        for key, label, width in (("company", "公司", 190), ("title", "已投岗位", 220), ("date", "投递日期", 110),
                                  ("status", "进度", 110), ("url", "岗位链接", 230), ("notes", "备注", 260)):
            self.table.heading(key, text=label, anchor="w")
            self.table.column(key, width=width, minwidth=85, stretch=key not in ("date", "status"), anchor="w")
        vertical = ttk.Scrollbar(container, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(container, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.bind("<<TreeviewSelect>>", lambda _: self._selection_changed())
        self.table.bind("<Double-1>", self._edit_from_event)
        self.table.bind("<Return>", lambda _: self.edit_application())
        self.table.bind("<Delete>", lambda _: self.delete_application())
        ttk.Label(self, textvariable=self.count, foreground="#667085").pack(anchor="e", pady=(6, 0))
        self.error_label = ttk.Label(self, textvariable=self.error, foreground="#b42318")

    def schedule_refresh(self):
        self.cancel_refresh()
        self.filter_timer = self.after(180, self._apply_filters)

    def cancel_refresh(self):
        if self.filter_timer is not None:
            self.after_cancel(self.filter_timer)
            self.filter_timer = None

    def _apply_filters(self):
        self.filter_timer = None
        self.refresh()

    def clear_filters(self):
        self.keyword.set("")
        self.status_filter.set("全部进度")
        self.cancel_refresh()
        self.refresh()

    def refresh(self):
        try:
            snapshot = self.service.snapshot()
        except sqlite3.Error as error:
            self.error.set(str(error))
            self.error_label.pack(anchor="w", pady=(4, 0))
            return
        self.error_label.pack_forget()
        summary = snapshot.summary
        self.summary.set(f"{summary.applied_companies} 家公司 · {summary.applications} 个岗位"
                         f" · 面试 {summary.interviews} · Offer {summary.offers}")
        rows = application_rows(snapshot, self.keyword.get(), self.status_filter.get())
        selected = self.table.selection()
        position = self.table.yview()[0]
        self.table.delete(*self.table.get_children())
        self.displayed_rows.clear()
        for row in rows:
            application = row.application
            item = f"job-{application.id}"
            self.table.insert("", "end", iid=item, values=(row.company.name, application.title,
                application.applied_on.isoformat(), application.status, application.url,
                application.notes.replace("\n", " ")))
            self.displayed_rows[item] = row
            if item in selected:
                self.table.selection_set(item)
        self.table.yview_moveto(position)
        self.count.set(f"{len(rows)} / {summary.applications} 条")
        self._selection_changed()

    def _selected(self):
        selected = self.table.selection()
        return self.displayed_rows.get(selected[0]) if selected else None

    def _selection_changed(self):
        row = self._selected()
        self.edit_button.configure(state="normal" if row else "disabled")
        self.delete_button.configure(state="normal" if row else "disabled")
        self.link_button.configure(state="normal" if row and row.application.url else "disabled")

    def _edit_from_event(self, event):
        item = self.table.identify_row(event.y)
        if item:
            self.table.selection_set(item)
            self.edit_application()

    def _saved(self, identifier):
        self.clear_filters()
        item = f"job-{identifier}"
        if item in self.displayed_rows:
            self.table.selection_set(item)
            self.table.focus(item)
            self.table.see(item)
            self._selection_changed()

    def add_application(self):
        return ApplicationDialog(self.winfo_toplevel(), self.service, self._saved)

    def edit_application(self):
        row = self._selected()
        if row:
            return ApplicationDialog(self.winfo_toplevel(), self.service, self._saved, row)

    def delete_application(self):
        row = self._selected()
        if not row:
            return
        if messagebox.askyesno("删除岗位", f"删除“{row.company.name} · {row.application.title}”？",
                              parent=self.winfo_toplevel()):
            try:
                self.service.delete_application(row.application.id)
            except sqlite3.Error as error:
                messagebox.showerror("删除失败", str(error), parent=self.winfo_toplevel())
                return
            self.refresh()

    def open_link(self):
        row = self._selected()
        if row and row.application.url:
            webbrowser.open(row.application.url)
