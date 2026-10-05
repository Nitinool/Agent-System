"""Small editor for a project's delivery stages."""

import sqlite3
import tkinter as tk
from tkinter import ttk

from ..projects import MilestoneDraft


class MilestoneDialog(tk.Toplevel):
    def __init__(self, parent, service, project_id, on_saved, milestone=None):
        super().__init__(parent)
        self.title("编辑里程碑" if milestone else "新增里程碑")
        self.transient(parent)
        self.resizable(False, False)
        self.service, self.project_id, self.on_saved = service, project_id, on_saved
        self.identifier = milestone.id if milestone else None
        self.name_var = tk.StringVar(value=milestone.name if milestone else "")
        self.error = tk.StringVar()
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="里程碑名称 *").grid(row=0, column=0, sticky="w", padx=(0, 12))
        entry = ttk.Entry(body, textvariable=self.name_var, width=42)
        entry.grid(row=0, column=1, pady=6)
        ttk.Label(body, text="阶段验收条件").grid(row=1, column=0, sticky="nw", pady=6)
        self.acceptance = tk.Text(body, width=42, height=4, wrap="word", font=("Microsoft YaHei UI", 10))
        self.acceptance.grid(row=1, column=1, pady=6)
        if milestone:
            self.acceptance.insert("1.0", milestone.acceptance)
        ttk.Label(body, textvariable=self.error, foreground="#b42318", wraplength=440).grid(
            row=2, column=0, columnspan=2, sticky="w")
        actions = ttk.Frame(body)
        actions.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="取消", command=self.destroy).pack(side="left", padx=8)
        ttk.Button(actions, text="保存", command=self.submit).pack(side="left")
        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()
        entry.focus_set()

    def submit(self):
        try:
            identifier = self.service.save_milestone(self.project_id,
                MilestoneDraft(self.name_var.get(), self.acceptance.get("1.0", "end-1c")), self.identifier)
        except (ValueError, sqlite3.Error) as error:
            self.error.set(str(error))
            return
        self.destroy()
        self.on_saved(identifier)
