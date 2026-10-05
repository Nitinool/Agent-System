"""Compact month calendar; all task operations stay in the parent page."""

from datetime import date, timedelta
import tkinter as tk
from tkinter import font

from ..tasks import month_days
from .priority import priority_color


class MonthCalendar(tk.Canvas):
    def __init__(self, parent, on_select, on_add):
        super().__init__(parent, background="white", highlightthickness=0, height=330, takefocus=True)
        self.on_select = on_select
        self.on_add = on_add
        self.title_font = font.Font(self, family="Microsoft YaHei UI", size=9)
        self.done_font = font.Font(self, family="Microsoft YaHei UI", size=9, overstrike=True)
        self.date_font = font.Font(self, family="Microsoft YaHei UI", size=10)
        self.selected = date.today()
        self.today = self.selected
        self.year, self.month = self.selected.year, self.selected.month
        self.days = month_days(self.year, self.month)
        self.by_day = {}
        self.bind("<Configure>", lambda _: self.redraw())
        self.bind("<Button-1>", self._click)
        self.bind("<Double-1>", self._double_click)
        for key, amount in (("Left", -1), ("Right", 1), ("Up", -7), ("Down", 7)):
            self.bind(f"<{key}>", lambda _, delta=amount: self._move_selection(delta))
        self.bind("<Return>", lambda _: self.on_add())

    def display(self, year, month, selected, today, tasks):
        self.year, self.month, self.selected, self.today = year, month, selected, today
        self.days = month_days(year, month)
        self.by_day = {}
        for task in tasks:
            self.by_day.setdefault(task.planned_on, []).append(task)
        self.redraw()

    def _geometry(self):
        return max(7, self.winfo_width()) / 7, max(120, self.winfo_height() - 28) / (len(self.days) // 7)

    def redraw(self):
        self.delete("all")
        cell_width, cell_height = self._geometry()
        for column, label in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            x = column * cell_width
            self.create_rectangle(x, 0, x + cell_width, 28, fill="#f3f5f9", outline="#e0e5ec")
            self.create_text(x + cell_width / 2, 14, text=label, font=self.date_font, fill="#667085")
        for index, day in enumerate(self.days):
            row, column = divmod(index, 7)
            x, y = column * cell_width, 28 + row * cell_height
            fill = "#e8eef9" if day == self.selected else (
                "white" if day and day.month == self.month else "#f3f5f9")
            self.create_rectangle(x, y, x + cell_width, y + cell_height, fill=fill, outline="#e0e5ec")
            if day is None:
                continue
            self.create_text(x + 6, y + 5, text=str(day.day), anchor="nw", font=self.date_font,
                             fill="#253246" if day.month == self.month else "#667085")
            tasks = self.by_day.get(day, [])
            line_height = self.title_font.metrics("linespace") + 2
            # A smaller window still keeps a count for tasks that do not fit.
            capacity = max(0, min(2, int((cell_height - 25) / line_height)))
            shown = min(len(tasks), 2, capacity)
            for position, task in enumerate(tasks[:shown]):
                top = y + 25 + position * line_height
                color = priority_color(task.priority, task.completed)
                self.create_oval(x + 5, top + 5, x + 12, top + 12, fill=color, outline="")
                self.create_text(x + 17, top, anchor="nw",
                                 text=self._fit(task.title, cell_width - 22),
                                 font=self.done_font if task.completed else self.title_font,
                                 fill="#667085" if task.completed else "#2457a7")
            if len(tasks) > shown:
                self.create_text(x + cell_width - 5, y + 6, anchor="ne",
                                 text=f"＋{len(tasks) - shown}项", font=self.title_font, fill="#667085")
            elif day == self.today and cell_width > 65:
                self.create_text(x + cell_width - 6, y + 6, text="今天", anchor="ne",
                                 font=self.title_font, fill="#2457a7")
            if day == self.selected:
                self.create_rectangle(x + 1, y + 1, x + cell_width - 1, y + cell_height - 1,
                                      outline="#2457a7")

    def _fit(self, text, width):
        if self.title_font.measure(text) <= width:
            return text
        while text and self.title_font.measure(text + "…") > width:
            text = text[:-1]
        return text + "…" if text else ""

    def _day_at(self, event):
        cell_width, cell_height = self._geometry()
        row, column = int((event.y - 28) // cell_height), int(event.x // cell_width)
        return self.days[row * 7 + column] if event.y >= 28 and 0 <= row < len(self.days) // 7 and 0 <= column < 7 else None

    def _click(self, event):
        day = self._day_at(event)
        if day:
            self.focus_set()
            self.on_select(day)

    def _double_click(self, event):
        day = self._day_at(event)
        if day:
            self.on_select(day)
            self.on_add()

    def _move_selection(self, amount):
        try:
            self.on_select(self.selected + timedelta(days=amount))
        except OverflowError:
            pass
        return "break"
