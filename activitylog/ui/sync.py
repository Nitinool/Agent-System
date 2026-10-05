"""Manual sync UI. Only immutable snapshots and network calls leave the Tk thread."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from ..github_sync import GitHubSync
from ..sync import REPOSITORY, SyncError, encode, merge
from ..sync_credentials import TokenStore

TOKEN_URL = "https://github.com/settings/personal-access-tokens/new"


class SyncController:
    def __init__(self, app):
        self.app, self.root, self.repo = app, app.root, app.service.sync
        path = app.service.store.path
        self.tokens = TokenStore(path.parent if path else None)
        self.token = ""
        self.dialog = None
        self.busy = False
        self.closed = False
        self.timer = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="github-sync")
        self.future = None
        self.status_timer = None
        self.status = tk.StringVar(value="尚未同步")
        ttk.Button(app.sidebar, text="数据同步…", command=self.open).pack(side="bottom", fill="x", padx=12, pady=(0, 8))
        self.update_status()

    def update_status(self):
        pending, at = self.repo.status()
        label = f"待同步 {pending} 条"
        label += f" · 上次 {at[:19].replace('T', ' ')}" if at else " · 尚未同步"
        self.status.set(label)

    def open(self):
        if self.dialog is not None and self.dialog.winfo_exists():
            self.update_status()
            self.dialog.lift()
            return self.dialog
        dialog = self.dialog = tk.Toplevel(self.root)
        dialog.title("数据同步")
        dialog.geometry("660x360")
        dialog.transient(self.root)
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=REPOSITORY, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=8)
        ttk.Label(frame, text="同步：求职、事项、今日待办、项目、里程碑和完成记录。\n行为日志保留在本机。", justify="left").pack(anchor="w", pady=(0, 12))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text="GitHub Token：").pack(side="left")
        self.token_var = tk.StringVar()
        self.token_entry = ttk.Entry(row, textvariable=self.token_var, show="•")
        self.token_entry.pack(side="left", fill="x", expand=True)
        self.remember = tk.BooleanVar(value=True)
        self.remember_check = ttk.Checkbutton(frame, text="在本机记住（Windows 加密）", variable=self.remember)
        self.remember_check.pack(anchor="w", pady=7)
        ttk.Label(frame, text="创建 Fine-grained Token，仅选择本数据仓库，Contents 设为 Read and write。\n已保存 Token 时，输入框留空即可。Token 不会写入代码或同步文件。", wraplength=615).pack(anchor="w")
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=12)
        ttk.Button(bar, text="创建 Token ↗", command=lambda: webbrowser.open(TOKEN_URL)).pack(side="left")
        self.forget_button = ttk.Button(bar, text="清除本机 Token", command=self.forget)
        self.forget_button.pack(side="left", padx=8)
        self.sync_button = ttk.Button(bar, text="立即同步", command=self.start)
        self.sync_button.pack(side="right")
        self.notice = tk.StringVar()
        ttk.Label(frame, textvariable=self.notice, wraplength=610, foreground="#2457a7").pack(anchor="w")
        dialog.protocol("WM_DELETE_WINDOW", self._close_dialog)
        self.update_status()
        self._watch_status()
        return dialog

    def _watch_status(self):
        self.status_timer = None
        if not self.closed and self.dialog is not None and self.dialog.winfo_exists():
            if not self.busy:
                self.update_status()
            self.status_timer = self.root.after(3000, self._watch_status)

    def forget(self):
        try:
            self.tokens.clear()
            self.token = ""
            self.token_var.set("")
            self.notice.set("已清除本机 Token。")
        except OSError:
            self.notice.set("无法清除 Token 文件，请检查本机文件权限。")

    def start(self):
        if self.busy:
            return
        try:
            entered = self.token_var.get().strip()
            token = entered or self.token or self.tokens.load()
            transport = GitHubSync(token)
            if entered:
                if self.remember.get():
                    self.tokens.save(token)
                else:
                    self.tokens.clear()
            self.token = token
            self.token_var.set("")
            self.local, self.base = self.repo.snapshot(), self.repo.baseline()
            encode(self.local)
            self.transport = transport
            self._set_busy(True)
            self.notice.set("正在读取远端…")
            self._background(transport.fetch, self._fetched)
        except (SyncError, OSError, sqlite3.Error) as error:
            self.notice.set(str(error))

    def _set_busy(self, busy):
        self.busy = busy
        for widget in (self.sync_button, self.forget_button, self.token_entry, self.remember_check):
            widget.configure(state="disabled" if busy else "normal")

    def _background(self, action, finished):
        self.future = self.executor.submit(action)

        def poll():
            self.timer = None
            if self.closed:
                return
            if not self.future.done():
                self.timer = self.root.after(100, poll)
                return
            try:
                value = self.future.result()
                finished(value)
            except (SyncError, OSError, sqlite3.Error) as error:
                self._set_busy(False)
                self.notice.set(str(error))
            except Exception:
                # Do not echo transport internals, payloads or authentication.
                self._set_busy(False)
                self.notice.set("同步未完成，本地数据仍保留。请重新同步。")
        self.timer = self.root.after(100, poll)

    def _fetched(self, result):
        remote, sha = result
        combined, conflicts = merge(self.base, self.local, remote)
        choices = {}
        for conflict in conflicts:
            choice = resolve_conflict(self.dialog, conflict, {**remote, **self.local})
            if choice is None:
                self._set_busy(False)
                self.notice.set("已取消；本地和远端均未修改。")
                return
            choices[conflict.uid] = choice
        if conflicts:
            combined, _ = merge(self.base, self.local, remote, choices)
        self.combined = combined
        encode(combined)
        # A local edit while downloading must be reconsidered before upload.
        if self.repo.snapshot() != self.local:
            raise SyncError("读取远端期间本地有修改，请重新点击同步。")
        if combined == remote:
            self._published(None)
        else:
            self.notice.set("正在保存合并结果…")
            self._background(lambda: self.transport.publish(combined, sha), self._published)

    def _published(self, _result):
        self.repo.apply(self.local, self.combined)
        self.app.jobs_panel.refresh()
        self.app.tasks_panel.refresh()
        self.app.projects_panel.refresh()
        self.update_status()
        self.notice.set("同步完成。换电脑前同步一次，另一台电脑打开后再同步。")
        self._set_busy(False)

    def _close_dialog(self):
        if self.busy:
            messagebox.showinfo("正在同步", "请等待本次同步结束。", parent=self.dialog)
            return
        self.dialog.destroy()
        self.dialog = None
        if self.status_timer is not None:
            self.root.after_cancel(self.status_timer)
            self.status_timer = None

    def close(self):
        self.closed = True
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None
        if self.status_timer is not None:
            self.root.after_cancel(self.status_timer)
            self.status_timer = None
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.token = ""


def version_text(record, records):
    fields = record["fields"]
    if fields is None:
        return "已删除"
    labels = {"name": "名称", "title": "名称", "goal": "目标", "status": "状态", "company": "公司",
              "applied_on": "投递日期", "url": "链接", "notes": "备注", "planned_on": "安排日期",
              "category": "分类", "priority": "优先级", "kind": "类型", "project_id": "所属项目",
              "milestone_id": "阶段", "acceptance": "验收条件", "outcome": "成果说明",
              "completed_at": "完成时间", "resume_status": "完成前状态", "days": "待办日期",
              "completions": "完成记录", "position": "阶段顺序"}
    lines = []
    for key, value in fields.items():
        if key in ("project_id", "milestone_id"):
            linked = records.get(value, {}).get("fields")
            value = linked["name"] if linked else ("已删除" if value else "未设置")
        elif key == "days":
            value = "、".join(value)
        elif key == "completions":
            value = "\n".join(f"{e['completed_at'][:19].replace('T', ' ')} · {e['title']}"
                              + (f" · 重新打开于 {e['reopened_at'][:19].replace('T', ' ')}" if e['reopened_at'] else "") for e in value)
        lines.append(f"{labels[key]}：{value if value is not None and value != '' else '未设置'}")
    return "\n\n".join(lines)


def resolve_conflict(parent, conflict, records):
    """Explicit per-record choice, including modify/delete conflicts."""
    window = tk.Toplevel(parent)
    window.title("同步冲突")
    window.geometry("850x500")
    window.transient(parent)
    result = None
    frame = ttk.Frame(window, padding=14)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=conflict.title, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
    ttk.Label(frame, text="两台电脑修改了同一条记录，请选择要保留的版本。今日安排和完成记录随该事项一起选择。").pack(anchor="w", pady=8)
    previews = ttk.Frame(frame)
    previews.pack(fill="both", expand=True)
    for side, record in (("本机", conflict.local), ("远端", conflict.remote)):
        column = ttk.LabelFrame(previews, text=side, padding=8)
        column.pack(side="left", fill="both", expand=True, padx=3)
        text = tk.Text(column, wrap="word", width=40, height=15)
        scroll = ttk.Scrollbar(column, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.insert("1.0", version_text(record, records))
        text.configure(state="disabled")

    def choose(value):
        nonlocal result
        result = value
        window.destroy()
    bar = ttk.Frame(frame)
    bar.pack(fill="x", pady=(12, 0))
    ttk.Button(bar, text="取消同步", command=lambda: choose(None)).pack(side="left")
    ttk.Button(bar, text="保留远端", command=lambda: choose("remote")).pack(side="right")
    ttk.Button(bar, text="保留本机", command=lambda: choose("local")).pack(side="right", padx=8)
    window.grab_set()
    window.wait_window()
    return result
