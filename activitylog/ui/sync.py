"""Sync UI and scheduling. Only snapshots and network calls leave the Tk thread."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import tkinter as tk
import time
from tkinter import ttk
import webbrowser

from ..github_sync import GitHubSync
from ..sync import LocalChanged, REPOSITORY, SyncError, encode, merge
from ..sync_credentials import TokenStore
from ..sync_settings import SyncSettings, SyncSettingsStore
from ..finance import money_text

TOKEN_URL = "https://github.com/settings/personal-access-tokens/new"
STATUS_INTERVAL_MS = 3000
AUTO_IDLE_SECONDS = 5
REMOTE_INTERVAL_SECONDS = 300


class SyncController:
    def __init__(self, app):
        self.app, self.root, self.repo = app, app.root, app.service.sync
        path = app.service.store.path
        self.tokens = TokenStore(path.parent if path else None)
        self.settings_store = SyncSettingsStore(path.parent if path else None)
        settings_error = ""
        try:
            self.settings = self.settings_store.load()
        except SyncError as error:
            self.settings = SyncSettings(check_on_start=False)
            settings_error = str(error)
        self.token = ""
        self.dialog = None
        self.busy = False
        self.closed = False
        self.timer = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="github-sync")
        self.future = None
        self.status_timer = None
        self.startup_timer = None
        self.status = tk.StringVar(master=self.root, value="尚未同步")
        self.sidebar_status = tk.StringVar(master=self.root)
        self.notice = tk.StringVar(master=self.root, value=settings_error)
        self.token_var = tk.StringVar(master=self.root)
        self.remember = tk.BooleanVar(master=self.root, value=True)
        self.auto_sync = tk.BooleanVar(master=self.root, value=self.settings.auto_sync)
        self.check_on_start = tk.BooleanVar(master=self.root, value=self.settings.check_on_start)
        self.remote_state = "同步设置需重新配置" if settings_error else "尚未检查远端"
        self.automatic_paused = False
        self.retry_at = 0
        self.failures = 0
        self.next_remote_check = time.monotonic() + REMOTE_INTERVAL_SECONDS
        self.observed = self.repo.snapshot()
        self.changed_at = time.monotonic()
        self.operation_automatic = False
        self.operation_check_only = False
        self.sidebar_label = tk.Label(app.sidebar, textvariable=self.sidebar_status,
                                      background="#f3f5f9", foreground="#667085",
                                      wraplength=120, justify="left", anchor="w", font=("Microsoft YaHei UI", 9))
        self.sidebar_label.pack(side="bottom", fill="x", padx=12, pady=(0, 8))
        ttk.Button(app.sidebar, text="数据同步…", command=self.open).pack(side="bottom", fill="x", padx=12, pady=(0, 8))
        self.update_status()
        self._watch_status()
        if self.settings.check_on_start or self.settings.auto_sync:
            self.startup_timer = self.root.after(500, self._startup)

    def update_status(self, snapshot=None):
        pending, at = self.repo.status(snapshot)
        if pending and self.remote_state == "已同步":
            self.remote_state = "本机有修改"
        label = f"待同步 {pending} 条"
        label += f" · 上次 {at[:19].replace('T', ' ')}" if at else " · 尚未同步"
        self.status.set(label)
        mode = "自动" if self.settings.auto_sync else "手动"
        last = at[5:16].replace("T", " ") if at else "未同步"
        self.sidebar_status.set(f"待同步 {pending} 条\n{self.remote_state}\n{last} · {mode}")
        return pending

    def open(self):
        if self.dialog is not None and self.dialog.winfo_exists():
            self.update_status()
            self.dialog.lift()
            return self.dialog
        dialog = self.dialog = tk.Toplevel(self.root)
        dialog.title("数据同步")
        dialog.geometry("660x430")
        dialog.transient(self.root)
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=REPOSITORY, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=8)
        ttk.Label(frame, text="同步：求职、事项、今日待办、项目、里程碑、完成记录和财务账目。\n行为日志保留在本机。", justify="left").pack(anchor="w", pady=(0, 12))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text="GitHub Token：").pack(side="left")
        self.token_entry = ttk.Entry(row, textvariable=self.token_var, show="•")
        self.token_entry.pack(side="left", fill="x", expand=True)
        self.remember_check = ttk.Checkbutton(frame, text="在本机记住（Windows 加密）", variable=self.remember)
        self.remember_check.pack(anchor="w", pady=7)
        ttk.Label(frame, text="创建 Fine-grained Token，仅选择本数据仓库，Contents 设为 Read and write。\n已保存 Token 时，输入框留空即可。Token 不会写入代码或同步文件。", wraplength=615).pack(anchor="w")
        self.startup_check = ttk.Checkbutton(frame, text="启动时检查远端更新", variable=self.check_on_start, command=self._save_settings)
        self.startup_check.pack(anchor="w", pady=(8, 0))
        self.auto_check = ttk.Checkbutton(frame, text="自动同步（停止修改后同步；每 5 分钟检查远端）", variable=self.auto_sync, command=self._save_settings)
        self.auto_check.pack(anchor="w", pady=4)
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=12)
        ttk.Button(bar, text="创建 Token ↗", command=lambda: webbrowser.open(TOKEN_URL)).pack(side="left")
        self.forget_button = ttk.Button(bar, text="清除本机 Token", command=self.forget)
        self.forget_button.pack(side="left", padx=8)
        self.sync_button = ttk.Button(bar, text="立即同步", command=self.start)
        self.sync_button.pack(side="right")
        self.notice_label = ttk.Label(frame, textvariable=self.notice, wraplength=610, foreground="#2457a7")
        self.notice_label.pack(anchor="w", fill="x")
        dialog.protocol("WM_DELETE_WINDOW", self._close_dialog)
        self.update_status()
        self._set_busy(self.busy)
        dialog.update_idletasks()
        height = max(430, frame.winfo_reqheight() + 40)
        dialog.geometry(f"660x{height}")
        dialog.minsize(660, height)
        return dialog

    def _save_settings(self):
        settings = SyncSettings(self.check_on_start.get(), self.auto_sync.get())
        try:
            self.settings_store.save(settings)
        except OSError:
            self.check_on_start.set(self.settings.check_on_start)
            self.auto_sync.set(self.settings.auto_sync)
            self.notice.set("同步设置未保存，请检查本机文件权限。")
            return
        newly_enabled = settings.auto_sync and not self.settings.auto_sync
        self.settings = settings
        if newly_enabled:
            self.automatic_paused = False
            self.retry_at = 0
            self.next_remote_check = time.monotonic()
        self.notice.set("自动同步已开启；冲突时暂停并提示处理。" if settings.auto_sync else "已保存设置，使用手动同步。")
        self.update_status()

    def _startup(self):
        self.startup_timer = None
        if not self.closed and not self.busy and (self.settings.check_on_start or self.settings.auto_sync):
            self.start(automatic=True, check_only=not self.settings.auto_sync)

    def _editing(self):
        return self.root.grab_current() is not None or self.app.projects_panel.inline_editing()

    def _watch_status(self):
        self.status_timer = None
        if self.closed:
            return
        try:
            snapshot = self.repo.snapshot()
            now = time.monotonic()
            if snapshot != self.observed:
                self.observed = snapshot
                self.changed_at = now
            pending = self.update_status(snapshot)
            if (self.settings.auto_sync and not self.busy and not self.automatic_paused
                    and not self._editing()
                    and now >= self.retry_at and now - self.changed_at >= AUTO_IDLE_SECONDS
                    and (pending or now >= self.next_remote_check)):
                self.start(automatic=True)
        except (SyncError, sqlite3.Error):
            self.sidebar_status.set("同步状态读取失败\n点击数据同步重试")
        finally:
            self.status_timer = self.root.after(STATUS_INTERVAL_MS, self._watch_status)

    def forget(self):
        try:
            self.tokens.clear()
            self.token = ""
            self.token_var.set("")
            self.notice.set("已清除本机 Token。")
            self.remote_state = "未配置 Token"
            self.automatic_paused = True
            self.update_status()
        except OSError:
            self.notice.set("无法清除 Token 文件，请检查本机文件权限。")

    def start(self, *, automatic=False, check_only=False):
        if self.closed or self.busy:
            return
        if automatic and self._editing():
            return
        if not automatic and not self.app.projects_panel.flush_edits():
            self.notice.set('项目编辑尚未保存，请先修正输入后再同步。')
            return
        if self.startup_timer is not None:
            self.root.after_cancel(self.startup_timer)
            self.startup_timer = None
        self.operation_automatic = automatic
        self.operation_check_only = check_only
        try:
            entered = "" if automatic else self.token_var.get().strip()
            token = entered or self.token or self.tokens.load()
            if automatic and not token:
                self.remote_state = "未配置 Token"
                self.automatic_paused = True
                self.update_status()
                return
            transport = GitHubSync(token)
            if entered:
                if self.remember.get():
                    self.tokens.save(token)
                else:
                    self.tokens.clear()
            self.token = token
            if not automatic:
                self.token_var.set("")
            if not automatic:
                self.automatic_paused = False
            self.local, self.base = self.repo.snapshot(), self.repo.baseline()
            encode(self.local)
            self.transport = transport
            self._set_busy(True)
            self.remote_state = "正在检查远端…" if check_only else "正在同步…"
            self.notice.set("正在检查远端…" if check_only else "正在读取远端…")
            self.update_status(self.local)
            self._background(transport.fetch, self._fetched)
        except (SyncError, OSError, sqlite3.Error) as error:
            self._failed(str(error))

    def _failed(self, message):
        self._set_busy(False)
        self.notice.set(message)
        self.remote_state = "同步失败 · 可重试"
        self.failures += 1
        self.retry_at = time.monotonic() + min(30 * 2 ** min(self.failures - 1, 4), REMOTE_INTERVAL_SECONDS)
        self.next_remote_check = self.retry_at
        try:
            self.update_status()
        except (SyncError, sqlite3.Error):
            self.sidebar_status.set("同步失败 · 可重试")

    def _set_busy(self, busy):
        self.busy = busy
        if self.dialog is not None and self.dialog.winfo_exists():
            for widget in (self.sync_button, self.forget_button, self.token_entry,
                           self.remember_check, self.startup_check, self.auto_check):
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
                self._failed(str(error))
            except Exception:
                # Do not echo transport internals, payloads or authentication.
                self._failed("同步未完成，本地数据仍保留。请重新同步。")
        self.timer = self.root.after(100, poll)

    def _fetched(self, result):
        remote, sha = result
        if self.operation_check_only:
            changed = remote != self.base
            self.remote_state = "远端有更新 · 请同步" if changed else "远端已核对"
            self.notice.set("远端有新内容，点击立即同步即可合并。" if changed else "远端与上次同步一致。")
            self.failures = 0
            self.retry_at = 0
            self.next_remote_check = time.monotonic() + REMOTE_INTERVAL_SECONDS
            self._set_busy(False)
            self.update_status()
            return
        if self.app.projects_panel.has_drafts() or (self.operation_automatic and self._editing()):
            raise LocalChanged("正在编辑，本次自动同步已延后；关闭编辑窗口后会重试。")
        combined, conflicts = merge(self.base, self.local, remote)
        if conflicts and self.operation_automatic:
            self.automatic_paused = True
            self.remote_state = f"有 {len(conflicts)} 条冲突"
            self.notice.set("自动同步已暂停：两台电脑修改了同一条记录，请点击立即同步，逐条选择保留的版本。")
            self._set_busy(False)
            self.update_status()
            return
        choices = {}
        for conflict in conflicts:
            choice = resolve_conflict(self.dialog or self.root, conflict, {**remote, **self.local})
            if choice is None:
                self._set_busy(False)
                self.notice.set("已取消；本地和远端均未修改。")
                self.automatic_paused = True
                self.remote_state = "冲突待处理"
                self.update_status()
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
        if self.app.projects_panel.has_drafts() or (self.operation_automatic and self._editing()):
            raise LocalChanged("正在编辑，本地未覆盖；关闭编辑窗口后会重新同步。")
        self.repo.apply(self.local, self.combined)
        self.app.jobs_panel.refresh()
        self.app.tasks_panel.refresh()
        self.app.projects_panel.refresh()
        self.app.finance_panel.refresh()
        self.observed = self.repo.snapshot()
        self.remote_state = "已同步"
        self.failures = 0
        self.retry_at = 0
        self.automatic_paused = False
        self.next_remote_check = time.monotonic() + REMOTE_INTERVAL_SECONDS
        self.update_status(self.observed)
        self.notice.set("同步完成。换电脑前同步一次，另一台电脑打开后再同步。")
        self._set_busy(False)

    def _close_dialog(self):
        self.dialog.destroy()
        self.dialog = None
        self.token_var.set("")

    def close(self):
        self.closed = True
        if self.startup_timer is not None:
            self.root.after_cancel(self.startup_timer)
            self.startup_timer = None
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None
        if self.status_timer is not None:
            self.root.after_cancel(self.status_timer)
            self.status_timer = None
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.token = ""
        self.token_var.set("")


def version_text(record, records):
    fields = record["fields"]
    if fields is None:
        return "已删除"
    labels = {"name": "名称", "title": "名称", "created_at": "记录时间", "goal": "目标", "status": "状态", "company": "公司",
              "applied_on": "投递日期", "url": "链接", "notes": "备注", "planned_on": "安排日期",
              "category": "分类", "priority": "优先级", "kind": "类型", "project_id": "所属项目",
              "milestone_id": "阶段", "acceptance": "验收条件", "outcome": "成果说明",
              "completed_at": "完成时间", "resume_status": "完成前状态", "days": "待办日期",
              "completions": "完成记录", "position": "阶段顺序", "direction": "收支", "amount_cents": "金额",
              "occurred_on": "交易日期", "side_source": "副业来源", "settled_on": "到账 / 支付日期",
              "mode": "项目类型", "range_start": "安排开始", "range_end": "安排结束", "excluded_days": "跳过日期"}
    lines = []
    for key, value in fields.items():
        if key in ("project_id", "milestone_id"):
            linked = records.get(value, {}).get("fields")
            value = linked["name"] if linked else ("已删除" if value else "未设置")
        elif key in ("days", "excluded_days"):
            value = "、".join(value)
        elif key == "amount_cents":
            value = money_text(value)
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
