"""Small standard-library calendar picker for editable date fields."""
import calendar
from datetime import date
import tkinter as tk
from tkinter import ttk


class DatePicker(tk.Toplevel):
    def __init__(self, parent, variable, today, initial=None):
        super().__init__(parent)
        self.variable, self.today = variable, today
        self.previous_grab = parent.grab_current()
        try:
            selected = date.fromisoformat(variable.get().strip())
        except ValueError:
            selected = initial or today
        self.year, self.month = selected.year, selected.month
        self.title('选择日期')
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        body = ttk.Frame(self, padding=8)
        body.pack()
        header = ttk.Frame(body)
        header.pack(fill='x')
        ttk.Button(header, text='‹', width=3, command=lambda: self.move(-1)).pack(side='left')
        self.caption = tk.StringVar()
        ttk.Label(header, textvariable=self.caption, anchor='center', width=18).pack(side='left', expand=True)
        ttk.Button(header, text='›', width=3, command=lambda: self.move(1)).pack(side='right')
        self.days = ttk.Frame(body)
        self.days.pack(pady=6)
        footer = ttk.Frame(body)
        footer.pack(fill='x')
        ttk.Button(footer, text='今天', command=lambda: self.choose(today)).pack(side='left')
        ttk.Button(footer, text='清空', command=lambda: self.choose(None)).pack(side='right')
        self.bind('<Escape>', lambda _: self.destroy())
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        self.render()
        self.update_idletasks()
        x = min(parent.winfo_rootx(), max(0, self.winfo_screenwidth() - self.winfo_reqwidth()))
        y = min(parent.winfo_rooty() + parent.winfo_height(), max(0, self.winfo_screenheight() - self.winfo_reqheight()))
        self.geometry(f'+{max(0, x)}+{max(0, y)}')
        self.grab_set()

    def render(self):
        self.caption.set(f'{self.year}年 {self.month}月')
        for child in self.days.winfo_children():
            child.destroy()
        for column, text in enumerate('一二三四五六日'):
            ttk.Label(self.days, text=text, anchor='center', width=4).grid(row=0, column=column)
        for row, week in enumerate(calendar.monthcalendar(self.year, self.month), 1):
            for column, day in enumerate(week):
                if day:
                    value = date(self.year, self.month, day)
                    ttk.Button(self.days, text=str(day), width=4,
                               command=lambda chosen=value: self.choose(chosen)).grid(row=row, column=column, padx=1, pady=1)

    def move(self, amount):
        year, month = divmod(self.year * 12 + self.month - 1 + amount, 12)
        if 1 <= year <= 9999:
            self.year, self.month = year, month + 1
            self.render()

    def choose(self, value):
        self.variable.set(value.isoformat() if value else '')
        self.destroy()

    def destroy(self):
        previous = getattr(self, 'previous_grab', None)
        super().destroy()
        if previous is not None:
            try:
                if previous.winfo_exists():
                    previous.grab_set()
            except tk.TclError:
                pass


class DateField(ttk.Frame):
    def __init__(self, parent, variable, today, fallback_var=None):
        super().__init__(parent)
        self.variable, self.today = variable, today
        self.fallback_var = fallback_var
        self.entry = ttk.Entry(self, textvariable=variable, width=12)
        self.entry.pack(side='left', fill='x', expand=True)
        ttk.Button(self, text='▾', width=2, command=self.open_picker).pack(side='left', padx=(2, 0))
        ttk.Button(self, text='×', width=2, command=lambda: variable.set('')).pack(side='left')

    def open_picker(self):
        initial = None
        if self.fallback_var is not None:
            try:
                initial = date.fromisoformat(self.fallback_var.get().strip())
            except ValueError:
                pass
        return DatePicker(self, self.variable, self.today(), initial)
