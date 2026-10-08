"""Tk widgets and user actions; domain work goes through the application service."""

from datetime import date, timedelta
import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from ..models import CATEGORIES, duration_text
from ..service import ActivityService
from .charts import DailyCharts
from .jobs import JobOverview
from .tasks import TaskOverview
from .projects import ProjectOverview
from .sync import SyncController
from .finance import FinanceOverview
from .home import HomeOverview


class LoggerApp:
    def __init__(self, root, service: ActivityService):
        self.root = root
        self.service = service
        self.policy = service.view_policy
        self.running = False
        self.timer = None
        self.filter_timer = None
        self.displayed_rows = {}
        self.last_refresh = 0
        frame = self._configure_window()
        self._build_controls(frame)
        self._build_dates(frame)
        self._build_tabs(frame)
        self._build_filters(frame)
        self._build_classification(frame)
        self._build_table(frame)
        self.jobs_panel = JobOverview(self.page_container, service.jobs)
        self.pages["jobs"] = self.jobs_panel
        self.jobs_panel.grid(row=0, column=0, sticky="nsew")
        self.tasks_panel = TaskOverview(self.page_container, service.tasks)
        self.pages["tasks"] = self.tasks_panel
        self.tasks_panel.grid(row=0, column=0, sticky="nsew")
        self.projects_panel = ProjectOverview(self.page_container, service.projects)
        self.pages["projects"] = self.projects_panel
        self.projects_panel.grid(row=0, column=0, sticky="nsew")
        self.finance_panel = FinanceOverview(self.page_container, service.finance)
        self.pages["finance"] = self.finance_panel
        self.finance_panel.grid(row=0, column=0, sticky="nsew")
        self.home_panel = HomeOverview(self.page_container, service, self.tasks_panel.refresh,
                                       self.select_page, self._open_home_project, self.toggle)
        self.pages['home'] = self.home_panel
        self.home_panel.grid(row=0, column=0, sticky='nsew')
        self.tasks_panel.on_refresh = self.home_panel.refresh
        tk.Label(self.sidebar, textvariable=self.status, background="#f3f5f9", foreground="#667085",
                 wraplength=120, justify="left", padx=14, pady=12).pack(side="bottom", fill="x")
        self.sync_controller = SyncController(self)
        self.select_page("home")
        self.refresh()
        for variable in (self.filter_keyword, self.filter_app, self.filter_category):
            variable.trace_add("write", lambda *_: self.schedule_filter())

    def _configure_window(self):
        root = self.root
        root.title("个人记录")
        root.geometry("1440x880")
        root.minsize(1100, 700)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=29)
        self.sidebar = tk.Frame(root, background="#f3f5f9", width=148)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Label(self.sidebar, text="我的记录", background="#f3f5f9", foreground="#253246",
                 font=("Microsoft YaHei UI", 13, "bold"), padx=14, pady=16, anchor="w").pack(fill="x")
        self.nav_buttons = {}
        for page, label in (("home", "主页"), ("records", "记录信息"), ("jobs", "求职一览"), ("tasks", "事项管理"), ("projects", "项目管理"), ("finance", "财务管理")):
            button = tk.Button(self.sidebar, text=label, command=lambda name=page: self.select_page(name),
                               font=("Microsoft YaHei UI", 10), anchor="w", relief="flat", borderwidth=0,
                               background="#f3f5f9", foreground="#344054", activebackground="#e8eef9",
                               padx=14, pady=9, cursor="hand2")
            button.pack(fill="x", padx=6, pady=2)
            self.nav_buttons[page] = button
        self.page_container = ttk.Frame(root)
        self.page_container.pack(side="left", fill="both", expand=True)
        self.page_container.rowconfigure(0, weight=1)
        self.page_container.columnconfigure(0, weight=1)
        frame = ttk.Frame(self.page_container, padding=18)
        frame.grid(row=0, column=0, sticky="nsew")
        self.pages = {"records": frame}
        return frame

    def select_page(self, page):
        if getattr(self, 'current_page', None) == 'projects' and not self.projects_panel.flush_edits():
            return
        self.pages[page].tkraise()
        self.current_page = page
        for name, button in self.nav_buttons.items():
            button.configure(background="#e8eef9" if name == page else "#f3f5f9",
                             foreground="#2457a7" if name == page else "#344054")
        if page == 'home':
            self.home_panel.refresh()
        elif page == "jobs":
            self.jobs_panel.refresh()
        elif page == "tasks":
            self.tasks_panel.refresh()
        elif page == "projects":
            self.projects_panel.refresh()
        elif page == "finance":
            self.finance_panel.refresh()

    def _open_home_project(self, identifier):
        self.select_page('projects')
        self.projects_panel.refresh(identifier)

    def _build_controls(self, frame):
        ttk.Label(frame, text="我的行为时间线", font=("Microsoft YaHei UI", 19, "bold")).pack(anchor="w")
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=8)
        self.toggle_button = ttk.Button(bar, text="开始记录", command=self.toggle)
        self.toggle_button.pack(side="left")
        ttk.Button(bar, text="导出全部 CSV", command=self.export).pack(side="left", padx=10)
        ttk.Button(bar, text="导出当天 CSV", command=lambda: self.export(day_only=True)).pack(side="left")
        self.status = tk.StringVar(value="已暂停 · 点击开始记录")
        ttk.Label(bar, textvariable=self.status).pack(side="left", padx=10)
        options = ttk.Frame(frame)
        options.pack(fill="x", pady=(0, 12))
        ttk.Label(options, text="排除进程（逗号分隔，例如 chrome.exe）：").pack(side="left")
        self.exclusions = tk.StringVar()
        ttk.Entry(options, textvariable=self.exclusions).pack(side="left", fill="x", expand=True)
        self.exclusions.trace_add("write", self.on_exclusions_change)

    def _build_dates(self, frame):
        dates = ttk.Frame(frame)
        dates.pack(fill="x", pady=(0, 10))
        ttk.Label(dates, text="查看日期：").pack(side="left")
        self.selected_date = date.today()
        self.date_text = tk.StringVar(value=self.selected_date.isoformat())
        ttk.Button(dates, text="前一天", command=lambda: self.move_day(-1)).pack(side="left", padx=5)
        date_entry = ttk.Entry(dates, textvariable=self.date_text, width=13)
        date_entry.pack(side="left")
        date_entry.bind("<Return>", lambda _: self.apply_date())
        ttk.Button(dates, text="查看", command=self.apply_date).pack(side="left", padx=5)
        ttk.Button(dates, text="后一天", command=lambda: self.move_day(1)).pack(side="left")
        ttk.Button(dates, text="今天", command=self.today).pack(side="left", padx=5)
        self.merge_view = tk.BooleanVar(value=True)
        ttk.Checkbutton(dates, text="合并相邻同一窗口（间隔 ≤ 2 分钟）", variable=self.merge_view,
                        command=self.refresh).pack(side="left", padx=12)
        self.summary = tk.StringVar()
        ttk.Label(frame, textvariable=self.summary, wraplength=1120).pack(fill="x", pady=(0, 10))

    def _build_tabs(self, frame):
        self.notebook = ttk.Notebook(frame)
        self.notebook.pack(fill="both", expand=True)
        self.timeline_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.timeline_tab, text="活动时间线")
        self.charts = DailyCharts(self.notebook, on_category=self.choose_chart_category)
        self.notebook.add(self.charts, text="分类分析")

    def _build_filters(self, frame):
        filters = ttk.Frame(self.timeline_tab)
        filters.pack(fill="x", pady=(0, 8))
        ttk.Label(filters, text="搜索：").pack(side="left")
        self.filter_keyword = tk.StringVar()
        ttk.Entry(filters, textvariable=self.filter_keyword, width=27).pack(side="left", padx=(0, 12))
        self.filter_app = tk.StringVar(value="全部应用")
        self.app_combo = ttk.Combobox(filters, textvariable=self.filter_app, values=("全部应用",), state="readonly", width=20)
        self.app_combo.pack(side="left", padx=(0, 12))
        self.filter_category = tk.StringVar(value="全部分类")
        ttk.Combobox(filters, textvariable=self.filter_category, values=("全部分类",) + CATEGORIES,
                     state="readonly", width=12).pack(side="left", padx=(0, 12))
        ttk.Button(filters, text="清除筛选", command=self.clear_filters).pack(side="left")

    def _build_classification(self, frame):
        assignment = ttk.Frame(self.timeline_tab)
        assignment.pack(fill="x", pady=(0, 8))
        ttk.Label(assignment, text="选中记录分类：").pack(side="left")
        self.assign_category = tk.StringVar(value="学习")
        ttk.Combobox(assignment, textvariable=self.assign_category, values=CATEGORIES,
                     state="readonly", width=12).pack(side="left", padx=(0, 8))
        ttk.Button(assignment, text="应用到选中记录", command=self.classify_selection).pack(side="left")
        self.assignment_info = tk.StringVar()
        ttk.Label(assignment, textvariable=self.assignment_info).pack(side="left", padx=12)

    def _build_table(self, frame):
        table_frame = ttk.Frame(self.timeline_tab)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=("start", "end", "duration", "app", "title", "state", "category"), show="headings")
        for key, label, width in (("start", "开始", 95), ("end", "结束 / 最近采样", 130),
                                  ("duration", "前台停留", 145), ("app", "应用", 155),
                                  ("title", "窗口 / 页面标题", 405), ("state", "状态", 160), ("category", "分类", 100)):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=80, stretch=key == "title")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table.bind("<Double-1>", self.show_detail)
        self.filter_info = tk.StringVar()
        ttk.Label(self.timeline_tab, textvariable=self.filter_info, padding=(0, 8)).pack(anchor="w")

    def refresh(self):
        try:
            self._refresh()
        except sqlite3.Error as error:
            self._capture_failed(error)

    def _refresh(self):
        snapshot = self.service.day_snapshot(self.selected_date)
        selected = self.table.selection()
        selected_refs = {reference for identifier in selected
                         for reference in self.displayed_rows[identifier].references}
        position = self.table.yview()[0]
        self.table.delete(*self.table.get_children())
        self.displayed_rows.clear()
        rows = snapshot.rows
        self.app_combo.configure(values=("全部应用",) + tuple(sorted({row.app for row in rows})))
        if self.filter_app.get() not in self.app_combo["values"]:
            self.filter_app.set("全部应用")
        totals = snapshot.summary.app_totals
        total, locked = snapshot.summary.total, snapshot.summary.locked
        apps = " · ".join(f"{app} {duration_text(seconds)}" for app, seconds in
                          sorted(totals.items(), key=lambda pair: pair[1], reverse=True)[:5])
        self.summary.set(f"{self.selected_date}  |  前台 {duration_text(total)}  |  锁屏 / 断开 {duration_text(locked)}"
                         + (f"\n{apps}" if apps else "\n暂无可统计的前台时间段。"))
        displayed = self.service.visible_rows(snapshot, merged=self.merge_view.get(),
                                              keyword=self.filter_keyword.get(), app=self.filter_app.get(),
                                              category=self.filter_category.get())
        self.filter_info.set(f"筛选匹配 {len(displayed)} 行，显示最新 {self.policy.row_limit} 行；顶部汇总和分类分析使用当天全部记录。")
        for row in displayed[:self.policy.row_limit]:
            duration = duration_text(row.seconds) if row.kind == "activity" else (
                duration_text(row.seconds) if row.kind == "locked" else "—")
            values = (row.start.strftime("%H:%M:%S"), row.end.strftime("%H:%M:%S"),
                      duration, row.app, row.title or "（无窗口标题）", row.state,
                      row.category if row.kind == "activity" else "—")
            identifier = self.table.insert("", "end", values=values)
            self.displayed_rows[identifier] = row
            if selected_refs.intersection(row.references):
                self.table.selection_add(identifier)
        self.table.yview_moveto(position)
        self.charts.update_snapshot(snapshot)
        self.home_panel.refresh_activity(snapshot)

    def schedule_filter(self):
        if self.filter_timer is not None:
            self.root.after_cancel(self.filter_timer)
        self.filter_timer = self.root.after(self.policy.filter_delay_ms, self.apply_filters)

    def apply_filters(self):
        self.filter_timer = None
        self.refresh()

    def clear_filters(self):
        self.filter_keyword.set("")
        self.filter_app.set("全部应用")
        self.filter_category.set("全部分类")
        self.refresh()

    def classify_selection(self):
        rows = [self.displayed_rows[identifier] for identifier in self.table.selection()]
        references = {reference for row in rows if row.kind == "activity" for reference in row.references}
        if not references:
            self.assignment_info.set("请先选择活动记录；锁屏和采集间隔不需要分类。")
            return
        try:
            category = self.assign_category.get()
            self.service.classify(references, category)
            self.assignment_info.set(f"已将 {len(references)} 个原始记录标为“{category}”。")
            self.refresh()
        except (sqlite3.Error, ValueError) as error:
            messagebox.showerror("分类失败", str(error), parent=self.root)

    def choose_chart_category(self, category):
        self.filter_keyword.set("")
        self.filter_app.set("全部应用")
        self.filter_category.set(category)
        self.notebook.select(self.timeline_tab)
        self.refresh()

    def apply_date(self):
        try:
            self.selected_date = date.fromisoformat(self.date_text.get().strip())
        except ValueError:
            messagebox.showerror("日期格式不正确", "请使用 YYYY-MM-DD，例如 2026-10-02。", parent=self.root)
            return
        self.date_text.set(self.selected_date.isoformat())
        self.refresh()

    def move_day(self, amount):
        self.selected_date += timedelta(days=amount)
        self.date_text.set(self.selected_date.isoformat())
        self.refresh()

    def today(self):
        self.selected_date = date.today()
        self.date_text.set(self.selected_date.isoformat())
        self.refresh()

    def toggle(self):
        was_running = self.running
        self._stop_scheduling()
        try:
            self.service.pause()
            if was_running:
                self.refresh()
            else:
                self.running = True
                self.last_refresh = 0
                self.toggle_button.configure(text="暂停记录")
                self.home_panel.record_button.configure(text='暂停记录')
                self.poll()
        except (OSError, sqlite3.Error) as error:
            self._capture_failed(error)

    def _stop_scheduling(self):
        self.running = False
        self.toggle_button.configure(text="开始记录")
        self.home_panel.record_button.configure(text='开始记录')
        self.status.set("已暂停")
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None

    def _capture_failed(self, error):
        # Stop callbacks first. A second write failure must not hide the original error.
        self._stop_scheduling()
        if self.filter_timer is not None:
            self.root.after_cancel(self.filter_timer)
            self.filter_timer = None
        try:
            self.service.pause("采集失败")
        except sqlite3.Error:
            pass
        messagebox.showerror("记录已暂停", str(error), parent=self.root)

    def on_exclusions_change(self, *_):
        try:
            self.service.pause("修改排除进程")
        except sqlite3.Error as error:
            self._capture_failed(error)

    def poll(self):
        self.timer = None
        if not self.running:
            return
        try:
            result = self.service.capture(self.exclusions.get())
            self.status.set(result.status)
            # Refresh duration every five samples, immediately on a window/state change.
            self.last_refresh += 1
            if result.changed or self.last_refresh >= self.policy.refresh_samples:
                self.refresh()
                self.last_refresh = 0
        except (OSError, sqlite3.Error) as error:
            self._capture_failed(error)
            return
        if self.running:
            self.timer = self.root.after(self.policy.poll_ms, self.poll)

    def export(self, day_only=False):
        selected = self.selected_date if day_only else None
        path = filedialog.asksaveasfilename(parent=self.root, title="导出当天行为日志" if day_only else "导出全部行为日志",
                                          defaultextension=".csv", filetypes=[("CSV 文件", "*.csv")],
                                          initialfile=f"行为日志-{selected.isoformat() if selected else '全部'}.csv")
        if not path:
            return
        try:
            count = self.service.export(path, selected, merged=self.merge_view.get())
            messagebox.showinfo("导出完成", f"已导出 {count} 条记录。", parent=self.root)
        except (OSError, sqlite3.Error, ValueError) as error:
            messagebox.showerror("导出失败", str(error), parent=self.root)

    def show_detail(self, _event):
        selection = self.table.selection()
        if selection:
            row = self.displayed_rows[selection[0]]
            detail = row.reason
            if row.parts:
                detail = "合并展示；各段停留时长相加，间隔未计时。"
                detail += "\n" + "\n".join(
                    f"{part.start:%H:%M:%S} — {part.end:%H:%M:%S}  {duration_text(part.seconds)}"
                    for part in row.parts)
            messagebox.showinfo("记录详情", f"{row.start:%Y-%m-%d %H:%M:%S} — {row.end:%Y-%m-%d %H:%M:%S}\n"
                                f"{row.app} · {row.process}\n{row.state} · {duration_text(row.seconds)}\n"
                                f"分类：{row.category if row.kind == 'activity' else '不适用'}\n"
                                f"{detail}\n\n{row.title}", parent=self.root)

    def close(self):
        if not self.projects_panel.flush_edits():
            return
        self.sync_controller.close()
        self._stop_scheduling()
        self.jobs_panel.cancel_refresh()
        self.tasks_panel.cancel_refresh()
        self.projects_panel.cancel_refresh()
        self.finance_panel.cancel_refresh()
        self.home_panel.cancel_refresh()
        if self.filter_timer is not None:
            self.root.after_cancel(self.filter_timer)
            self.filter_timer = None
        try:
            self.service.close()
        except sqlite3.Error as error:
            messagebox.showerror("最后一段未能结束", f"已保存的采样仍保留。\n{error}", parent=self.root)
        finally:
            self.root.update_idletasks()
            self.root.destroy()
