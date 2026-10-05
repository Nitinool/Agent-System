"""Compact ledger, side-income summaries and an all-month pending list."""

from datetime import date
import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk
from .autocomplete import HistoryCombobox

from ..finance import (EXPENSE_CATEGORIES, INCOME_CATEGORIES, INCOME_STATUSES,
                       FinanceDraft, amount_text, filter_entries, money_text, validate_month)


class FinanceDialog(tk.Toplevel):
    def __init__(self, parent, service, on_saved, entry=None, *, direction="支出", pending=False, settling=False):
        super().__init__(parent)
        self.title("确认到账" if settling else "编辑账目" if entry else "新增账目")
        self.transient(parent)
        self.resizable(False, False)
        self.service, self.on_saved = service, on_saved
        self.identifier = entry.id if entry else None
        today = date.today().isoformat()
        sources, categories = service.history()
        direction = entry.direction if entry else direction
        status = "已到账" if settling else entry.status if entry else ("待结算" if pending else "已到账" if direction == "收入" else "已支付")
        self.direction_var = tk.StringVar(value=direction)
        self.amount_var = tk.StringVar(value=amount_text(entry.amount_cents) if entry else "")
        self.date_var = tk.StringVar(value=entry.occurred_on.isoformat() if entry else today)
        self.title_var = tk.StringVar(value=entry.title if entry else "")
        self.category_var = tk.StringVar(value=entry.category if entry else "副业收入" if pending else "其他")
        self.source_var = tk.StringVar(value=entry.side_source if entry else "")
        self.status_var = tk.StringVar(value=status)
        self.settled_var = tk.StringVar(value=today if settling else entry.settled_on.isoformat() if entry and entry.settled_on else today)
        self.error = tk.StringVar()
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        self.direction_combo = self._field(body, 0, "收支", self.direction_var, ("支出", "收入"), readonly=True)
        self.amount_entry = self._field(body, 1, "金额（人民币）*", self.amount_var)
        self._field(body, 2, "交易 / 卖出日期 *", self.date_var)
        self._field(body, 3, "说明", self.title_var)
        self.category_combo = self._field(body, 4, "分类 *", self.category_var,
                                          tuple(dict.fromkeys(EXPENSE_CATEGORIES + INCOME_CATEGORIES + categories)))
        self.source_combo = self._field(body, 5, "副业来源（普通收支可留空）", self.source_var, sources)
        self.status_combo = self._field(body, 6, "结算状态", self.status_var, INCOME_STATUSES, readonly=True)
        self.settled_entry = self._field(body, 7, "实际到账 / 支付日期", self.settled_var)
        ttk.Label(body, text="备注").grid(row=8, column=0, sticky="nw", pady=5)
        self.notes = tk.Text(body, height=4, width=43, wrap="word", font=("Microsoft YaHei UI", 10))
        self.notes.grid(row=8, column=1, sticky="ew", pady=5)
        if entry:
            self.notes.insert("1.0", entry.notes)
        ttk.Label(body, textvariable=self.error, foreground="#b42318", wraplength=530).grid(row=9, column=0, columnspan=2, sticky="w")
        actions = ttk.Frame(body)
        actions.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="确认到账" if settling else "保存", command=self.submit).pack(side="right")
        ttk.Button(actions, text="取消", command=self.destroy).pack(side="right", padx=8)
        self.direction_combo.bind("<<ComboboxSelected>>", lambda _: self._update_status())
        self.status_combo.bind("<<ComboboxSelected>>", lambda _: self._update_status())
        self._update_status()
        if settling:
            self.direction_combo.configure(state="disabled")
        self.bind("<Escape>", lambda _: self.destroy())
        self.bind("<Control-Return>", lambda _: self.submit())
        self.grab_set()
        self.amount_entry.focus_set()

    @staticmethod
    def _field(body, row, label, variable, values=None, readonly=False):
        ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=5)
        if values is None:
            field = ttk.Entry(body, textvariable=variable, width=43)
        else:
            if readonly:
                field = ttk.Combobox(body, textvariable=variable, values=values, state="readonly", width=41)
            else:
                field = HistoryCombobox(body, textvariable=variable, values=values, width=41)
        field.grid(row=row, column=1, sticky="ew", pady=5)
        return field

    def _update_status(self):
        choices = INCOME_STATUSES if self.direction_var.get() == "收入" else ("已支付",)
        self.status_combo.configure(values=choices)
        if self.status_var.get() not in choices:
            self.status_var.set(choices[0])
        pending = self.status_var.get() == "待结算"
        self.settled_entry.configure(state="disabled" if pending else "normal")
        if pending:
            self.settled_var.set("")
        elif not self.settled_var.get():
            self.settled_var.set(date.today().isoformat())

    def submit(self):
        draft = FinanceDraft(self.direction_var.get(), self.amount_var.get(), self.date_var.get(),
                             self.title_var.get(), self.category_var.get(), self.source_var.get(),
                             self.status_var.get(), self.settled_var.get(), self.notes.get("1.0", "end-1c"))
        try:
            identifier = self.service.save(draft, self.identifier)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.destroy()
        self.on_saved(identifier)


class FinanceOverview(ttk.Frame):
    def __init__(self, parent, service):
        super().__init__(parent, padding=16)
        self.service = service
        self.filter_timer = None
        self.rows = {}
        self.sources = {}
        self.month_var = tk.StringVar(value=date.today().strftime("%Y-%m"))
        self.keyword = tk.StringVar()
        self.direction_filter = tk.StringVar(value="全部收支")
        self.status_filter = tk.StringVar(value="全部状态")
        self.source_filter = tk.StringVar(value="全部来源")
        self.summary = tk.StringVar()
        self.count = tk.StringVar()
        self.error = tk.StringVar()
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, text="财务管理", font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        ttk.Button(header, text="＋ 待结算收入", command=self.add_pending).pack(side="right")
        ttk.Button(header, text="＋ 收入", command=lambda: self.add_entry("收入")).pack(side="right", padx=8)
        ttk.Button(header, text="＋ 支出", command=lambda: self.add_entry("支出")).pack(side="right")
        ttk.Label(self, textvariable=self.summary, foreground="#475467").pack(anchor="w", pady=(0, 10))
        period = ttk.Frame(self)
        period.pack(fill="x", pady=(0, 8))
        ttk.Label(period, text="月份").pack(side="left")
        self.month_entry = ttk.Entry(period, textvariable=self.month_var, width=9)
        self.month_entry.pack(side="left", padx=8)
        self.month_entry.bind("<Return>", lambda _: self.refresh())
        for text, action in (("查看", self.refresh), ("‹", lambda: self.move_month(-1)),
                             ("›", lambda: self.move_month(1)), ("本月", self.this_month), ("全部", self.all_months)):
            ttk.Button(period, text=text, command=action, width=6).pack(side="left", padx=(0, 4))
        self.delete_button = ttk.Button(period, text="删除", command=self.delete_entry)
        self.delete_button.pack(side="right")
        self.edit_button = ttk.Button(period, text="编辑", command=self.edit_entry)
        self.edit_button.pack(side="right", padx=8)
        self.settle_button = ttk.Button(period, text="确认到账", command=self.settle_entry)
        self.settle_button.pack(side="right")
        filters = ttk.Frame(self)
        filters.pack(fill="x", pady=(0, 8))
        ttk.Entry(filters, textvariable=self.keyword, width=22).pack(side="left", padx=(0, 8))
        ttk.Combobox(filters, textvariable=self.direction_filter, values=("全部收支", "收入", "支出"), state="readonly", width=9).pack(side="left", padx=(0, 8))
        ttk.Combobox(filters, textvariable=self.status_filter, values=("全部状态", "已到账", "待结算", "已支付"), state="readonly", width=9).pack(side="left", padx=(0, 8))
        self.source_combo = ttk.Combobox(filters, textvariable=self.source_filter, state="readonly", width=19)
        self.source_combo.pack(side="left", padx=(0, 8))
        ttk.Button(filters, text="清除筛选", command=self.clear_filters).pack(side="left")
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        self.ledger_tab, self.side_tab, self.pending_tab = (ttk.Frame(self.notebook) for _ in range(3))
        for tab, label in ((self.ledger_tab, "记账流水"), (self.side_tab, "副业统计"), (self.pending_tab, "待结算（全部月份）")):
            self.notebook.add(tab, text=label)
        columns = (("date", "交易日期", 105), ("settled", "到账 / 支付日期", 125), ("direction", "收支", 65),
                   ("amount", "金额（元）", 110), ("status", "状态", 85), ("category", "分类", 100),
                   ("source", "副业来源", 140), ("title", "说明", 190), ("notes", "备注", 220))
        self.table = self._table(self.ledger_tab, columns)
        self.pending_table = self._table(self.pending_tab, columns)
        self.side_table = self._table(self.side_tab, (("source", "副业来源", 180), ("income", "所选月份到账", 150),
                                                     ("expense", "所选月份支出", 150), ("net", "所选月份净额", 150),
                                                     ("pending", "待结算（全部）", 150), ("count", "待结算笔数", 100)))
        ttk.Label(self.side_tab, text="净额 = 已到账收入 − 已支付支出；待结算包含所有月份，尚未计入收入。", foreground="#667085").pack(anchor="w", pady=6)
        for table in (self.table, self.pending_table):
            table.tag_configure("income", foreground="#216e39")
            table.tag_configure("pending", foreground="#946200")
            table.bind("<<TreeviewSelect>>", lambda _: self._selection_changed())
            table.bind("<Double-1>", self._edit_from_event)
            table.bind("<Return>", lambda _: self.edit_entry())
            table.bind("<Delete>", lambda _: self.delete_entry())
        self.side_table.bind("<Double-1>", self._source_from_event)
        self.notebook.bind("<<NotebookTabChanged>>", lambda _: self._selection_changed())
        ttk.Label(self, textvariable=self.count, foreground="#667085").pack(anchor="e", pady=(5, 0))
        ttk.Label(self, textvariable=self.error, foreground="#b42318").pack(anchor="w")
        self.refresh()
        for variable in (self.keyword, self.direction_filter, self.status_filter, self.source_filter):
            variable.trace_add("write", lambda *_: self.schedule_refresh())

    @staticmethod
    def _table(parent, columns):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        table = ttk.Treeview(frame, columns=tuple(c[0] for c in columns), show="headings", selectmode="browse", height=15)
        for key, label, width in columns:
            table.heading(key, text=label, anchor="w")
            table.column(key, width=width, minwidth=min(65, width), anchor="e" if key in ("amount", "income", "expense", "net", "pending", "count") else "w")
        scroll = ttk.Scrollbar(frame, command=table.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=table.xview)
        table.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        table.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        return table

    def refresh(self):
        try:
            snapshot = self.service.snapshot(self.month_var.get().strip())
            sources, _ = self.service.history()
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.error.set("")
        totals = snapshot.totals
        period = self.month_var.get().strip() or "全部月份"
        self.summary.set(f"{period} · 到账收入 {money_text(totals.income)} · 已支付支出 {money_text(totals.expense)}"
                         f" · 收支结余 {money_text(totals.net)} · 待结算（全部）{money_text(totals.pending)} / {totals.pending_count} 笔")
        self.source_combo.configure(values=("全部来源", "日常收支") + sources)
        self.rows.clear()
        counts = []
        for table, entries in ((self.table, snapshot.entries), (self.pending_table, snapshot.pending_entries)):
            selected, position = table.selection(), table.yview()[0]
            table.delete(*table.get_children())
            entries = filter_entries(entries, self.keyword.get(), self.direction_filter.get(), self.status_filter.get(), self.source_filter.get())
            counts.append(len(entries))
            for entry in entries:
                item = f"finance-{entry.id}"
                table.insert("", "end", iid=item, values=(entry.occurred_on.isoformat(), entry.settled_on.isoformat() if entry.settled_on else "",
                    entry.direction, amount_text(entry.amount_cents), entry.status, entry.category, entry.side_source,
                    entry.title, entry.notes.replace("\n", " ")), tags=("pending" if entry.status == "待结算" else "income" if entry.direction == "收入" else "expense",))
                self.rows[item] = entry
                if item in selected:
                    table.selection_set(item)
            table.yview_moveto(position)
        self.side_table.delete(*self.side_table.get_children())
        self.sources.clear()
        for key, label in (("income", "累计到账"), ("expense", "累计支出"), ("net", "累计净额")):
            self.side_table.heading(key, text=label if not self.month_var.get().strip() else label.replace("累计", "所选月份"))
        for index, row in enumerate(snapshot.sources):
            t = row.totals
            item = f"source-{index}"
            self.side_table.insert("", "end", iid=item, values=(row.source, money_text(t.income), money_text(t.expense), money_text(t.net), money_text(t.pending), t.pending_count))
            self.sources[item] = row.source
        self.count.set(f"流水 {counts[0]} 条 · 待结算列表 {counts[1]} 笔 · 金额均为人民币；汇总按完整月份计算")
        self._selection_changed()

    def schedule_refresh(self):
        self.cancel_refresh()
        self.filter_timer = self.after(180, self._apply_filters)

    def _apply_filters(self):
        self.filter_timer = None
        self.refresh()

    def cancel_refresh(self):
        if self.filter_timer is not None:
            self.after_cancel(self.filter_timer)
            self.filter_timer = None

    def clear_filters(self):
        self.keyword.set("")
        self.direction_filter.set("全部收支")
        self.status_filter.set("全部状态")
        self.source_filter.set("全部来源")
        self.cancel_refresh()
        self.refresh()

    def this_month(self):
        self.month_var.set(date.today().strftime("%Y-%m"))
        self.refresh()

    def all_months(self):
        self.month_var.set("")
        self.refresh()

    def move_month(self, amount):
        try:
            month = validate_month(self.month_var.get().strip()) or date.today().strftime("%Y-%m")
            year, number = map(int, month.split("-"))
            year, number = divmod(year * 12 + number - 1 + amount, 12)
            target = f"{year:04d}-{number + 1:02d}"
            validate_month(target)
        except ValueError as error:
            self.error.set(str(error))
            return
        self.month_var.set(target)
        self.refresh()

    def _selected(self):
        tab = self.notebook.select()
        table = self.table if tab == str(self.ledger_tab) else self.pending_table if tab == str(self.pending_tab) else None
        selected = table.selection() if table else ()
        return self.rows.get(selected[0]) if selected else None

    def _selection_changed(self):
        row = self._selected()
        self.edit_button.configure(state="normal" if row else "disabled")
        self.delete_button.configure(state="normal" if row else "disabled")
        self.settle_button.configure(state="normal" if row and row.status == "待结算" else "disabled")

    def _edit_from_event(self, event):
        item = event.widget.identify_row(event.y)
        if item:
            event.widget.selection_set(item)
            self.edit_entry()

    def _source_from_event(self, event):
        item = self.side_table.identify_row(event.y)
        if item in self.sources:
            self.clear_filters()
            self.source_filter.set(self.sources[item])
            self.notebook.select(self.ledger_tab)
            self.refresh()

    def _saved(self, identifier):
        self.clear_filters()
        entry = self.service.get(identifier)
        self.month_var.set(entry.effective_day.strftime("%Y-%m"))
        self.notebook.select(self.ledger_tab)
        self.refresh()
        item = f"finance-{identifier}"
        self.table.selection_set(item)
        self.table.focus(item)
        self.table.see(item)
        self._selection_changed()

    def add_entry(self, direction):
        return FinanceDialog(self.winfo_toplevel(), self.service, self._saved, direction=direction)

    def add_pending(self):
        return FinanceDialog(self.winfo_toplevel(), self.service, self._saved, direction="收入", pending=True)

    def edit_entry(self):
        row = self._selected()
        if row:
            return FinanceDialog(self.winfo_toplevel(), self.service, self._saved, self.service.get(row.id))

    def settle_entry(self):
        row = self._selected()
        if row and row.status == "待结算":
            return FinanceDialog(self.winfo_toplevel(), self.service, self._saved, self.service.get(row.id), settling=True)

    def delete_entry(self):
        row = self._selected()
        if row and messagebox.askyesno("删除账目", f"删除“{row.title} · {money_text(row.amount_cents)}”？", parent=self.winfo_toplevel()):
            try:
                self.service.delete(row.id)
            except (ValueError, sqlite3.Error) as error:
                self.error.set(str(error))
                return
            self.refresh()
