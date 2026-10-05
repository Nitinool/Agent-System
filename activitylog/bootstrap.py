"""Compose the Windows desktop application and own its lifetime."""

from pathlib import Path
import sqlite3
import sys
import tkinter as tk
from tkinter import messagebox
from .windows import SingleInstance, WindowsReader
from .storage import Store
from .service import ActivityService
from .ui.app import LoggerApp


def main():
    if sys.platform != "win32":
        raise SystemExit("此原型只支持 Windows。")
    directory = Path(__file__).resolve().parent.parent / "data"
    directory.mkdir(exist_ok=True)
    root = tk.Tk()
    instance = None
    service = None
    try:
        db_path = directory / "activity.sqlite3"
        instance = SingleInstance(db_path)
        if instance.already_running:
            messagebox.showinfo("软件已经运行", "请使用已打开的行为日志窗口。", parent=root)
            root.destroy()
            return
        reader = WindowsReader()
        service = ActivityService(Store(db_path, recover=True), reader)
        LoggerApp(root, service)
        root.mainloop()
    except (OSError, sqlite3.Error) as error:
        if root.winfo_exists():
            messagebox.showerror("启动失败", str(error), parent=root)
            root.destroy()
    finally:
        try:
            if service is not None:
                service.close()
        finally:
            if instance is not None:
                instance.close()
