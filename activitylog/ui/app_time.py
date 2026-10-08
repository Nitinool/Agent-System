"""Application time pie and a complete, scrollable legend using only Tk."""

import tkinter as tk
from tkinter import ttk
from zlib import crc32

from ..models import duration_text

APP_COLORS = ('#5088b8', '#74a591', '#c29b66', '#9e9baf', '#bc7d8d', '#5b9eaa',
              '#8074b7', '#a5a259', '#b98660', '#6790a5', '#89a47a', '#a37f9f')


def app_color(name):
    return APP_COLORS[crc32(name.casefold().encode('utf-8')) % len(APP_COLORS)]


class AppTimeChart(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.totals = {}
        self.total = 0
        self.info = tk.StringVar()
        self.detail = tk.StringVar(value='今日已记录的前台应用时间')
        self.heading = ttk.Frame(self)
        self.heading.pack(fill='x', pady=(0, 6))
        ttk.Label(self.heading, text='今日时间记录 · 按应用', font=('Microsoft YaHei UI', 11, 'bold')).pack(side='left')
        ttk.Label(self.heading, textvariable=self.info, foreground='#667085').pack(side='right')
        body = ttk.Frame(self)
        body.pack(fill='both', expand=True)
        self.pie = tk.Canvas(body, width=170, height=150, background='white', highlightthickness=0)
        self.pie.pack(side='left', padx=(0, 20))
        self.pie.bind('<Configure>', lambda _: self.draw())
        legend = ttk.Frame(body)
        legend.pack(side='left', fill='both', expand=True)
        self.table = ttk.Treeview(legend, columns=('app', 'duration', 'percent'), show=('tree', 'headings'),
                                  height=4, selectmode='browse')
        self.table.column('#0', width=24, minwidth=24, stretch=False)
        for key, label, width in (('app', '应用', 260), ('duration', '时长', 170), ('percent', '占比', 70)):
            self.table.heading(key, text=label, anchor='w')
            self.table.column(key, width=width, minwidth=60, stretch=key == 'app')
        scroll = ttk.Scrollbar(legend, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.table.bind('<<TreeviewSelect>>', self._selected)
        self.images = {}
        self.apps = {}
        ttk.Label(self, textvariable=self.detail, foreground='#667085').pack(anchor='w', pady=(6, 0))

    def display(self, snapshot):
        self.totals = dict(sorted(((app, seconds) for app, seconds in snapshot.summary.app_totals.items() if seconds > 0),
                                  key=lambda pair: (-pair[1], pair[0].casefold())))
        self.total = sum(self.totals.values())
        self.info.set(f'累计记录 {duration_text(self.total)}')
        selected = self.table.selection()
        selected_app = self.apps.get(selected[0]) if selected else None
        position = self.table.yview()[0]
        self.table.delete(*self.table.get_children())
        self.apps.clear()
        for index, (app, seconds) in enumerate(self.totals.items()):
            if app not in self.images:
                image = tk.PhotoImage(master=self, width=10, height=10)
                image.put(app_color(app), to=(0, 0, 10, 10))
                self.images[app] = image
            item = f'app-{index}'
            self.apps[item] = app
            self.table.insert('', 'end', iid=item, image=self.images[app],
                              values=(app, duration_text(seconds), f'{seconds / self.total:.1%}'))
            if app == selected_app:
                self.table.selection_set(item)
        self.table.yview_moveto(position)
        self._selected()
        self.draw()

    def draw(self):
        canvas = self.pie
        canvas.delete('all')
        width, height = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        size = max(1, min(width, height) - 12)
        x, y = (width - size) / 2, (height - size) / 2
        bounds = (x, y, x + size, y + size)
        if not self.total:
            canvas.create_oval(*bounds, fill='#edf0f4', outline='', tags='empty')
            canvas.create_text(width / 2, height / 2, text='暂无记录', fill='#667085')
            return
        start = 90
        for index, (app, seconds) in enumerate(self.totals.items()):
            angle = 360 * seconds / self.total
            tag = f'app-{index}'
            if len(self.totals) == 1:
                canvas.create_oval(*bounds, fill=app_color(app), outline='', tags=('slice', tag))
            else:
                canvas.create_arc(*bounds, start=start, extent=-angle, fill=app_color(app), outline='',
                                  tags=('slice', tag))
            canvas.tag_bind(tag, '<Button-1>', lambda _, item=tag: self.choose(item))
            start -= angle

    def choose(self, item):
        self.table.selection_set(item)
        self.table.see(item)
        self._selected()

    def _selected(self, _event=None):
        selected = self.table.selection()
        app = self.apps.get(selected[0]) if selected else None
        self.detail.set(f'{app} · {duration_text(self.totals[app])} · {self.totals[app] / self.total:.1%}'
                        if app else ('今日已记录的前台应用时间' if self.total else '今天暂无已记录的前台应用时间'))
