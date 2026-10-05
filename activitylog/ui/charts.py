"""Daily category charts rendered with Tk; no extra dependencies."""

import tkinter as tk
from tkinter import ttk

from ..models import CATEGORIES, duration_text
from ..analysis import category_totals


COLORS = {
    "开发": "#3975db", "学习": "#1c947d", "求职": "#ad6bd2",
    "娱乐": "#e39432", "沟通": "#db6b8a", "其他": "#64788c", "未分类": "#a2a9b3",
    "锁屏 / 断开": "#687380", "采集间隔": "#c8cdd3",
}


class DailyCharts(ttk.Frame):
    def __init__(self, parent, on_category=None):
        super().__init__(parent, padding=14)
        self.rows = []
        self.totals = category_totals([])
        self.on_category = on_category
        self.info = tk.StringVar()
        self.hover = tk.StringVar(value="移到色块上查看详情；点击分类条可筛选时间线。")
        ttk.Label(self, text="一天的时间分配", font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        ttk.Label(self, textvariable=self.info, wraplength=1200).pack(anchor="w", pady=(8, 14))
        panel = ttk.Frame(self)
        panel.pack(fill="both", expand=True)
        panel.columnconfigure(0, weight=2)
        panel.columnconfigure(1, weight=3)
        panel.rowconfigure(1, weight=1)
        ttk.Label(panel, text="各分类累计前台时间（点击可筛选）").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(panel, text="24 小时活动分布（保留原始间隔）").grid(row=0, column=1, sticky="w", padx=(18, 0), pady=(0, 8))
        self.bars = tk.Canvas(panel, background="white", highlightthickness=0, width=420, height=340)
        self.timeline = tk.Canvas(panel, background="white", highlightthickness=0, width=700, height=340)
        self.bars.grid(row=1, column=0, sticky="nsew")
        self.timeline.grid(row=1, column=1, sticky="nsew", padx=(18, 0))
        self.bars.bind("<Configure>", lambda _: self.draw_bars())
        self.timeline.bind("<Configure>", lambda _: self.draw_timeline())
        self.timeline.bind("<Leave>", lambda _: self.hover.set("移到色块上查看详情；点击分类条可筛选时间线。"))
        ttk.Label(self, textvariable=self.hover, wraplength=1200).pack(fill="x", pady=(12, 4))
        ttk.Label(self, text="统计所选日期全部记录，不受列表筛选影响。空白表示未记录；前台停留不等于实际工作或视频播放时长。",
                  wraplength=1200).pack(fill="x")

    def update_snapshot(self, snapshot):
        self.rows = snapshot.rows
        self.totals = snapshot.summary.category_totals
        total = snapshot.summary.total
        coverage = snapshot.summary.classified_percent
        locked = snapshot.summary.locked
        self.info.set(f"{snapshot.day}  |  前台 {duration_text(total)}  |  已分类 {coverage:.1f}%"
                      f"  |  锁屏 / 断开 {duration_text(locked)}")
        self.hover.set("移到色块上查看详情；点击分类条可筛选时间线。")
        self.draw_bars()
        self.draw_timeline()

    def draw_bars(self):
        canvas = self.bars
        canvas.delete("all")
        width, height = max(320, canvas.winfo_width()), max(230, canvas.winfo_height())
        total = sum(self.totals.values())
        largest = max(self.totals.values(), default=0)
        spacing = (height - 28) / len(CATEGORIES)
        for index, category in enumerate(CATEGORIES):
            y = 10 + index * spacing
            seconds = self.totals[category]
            percentage = seconds / total * 100 if total else 0
            tag = f"category-{index}"
            canvas.create_text(14, y, anchor="nw", text=category, fill="#253246", tags=tag)
            canvas.create_text(width - 14, y, anchor="ne", text=f"{duration_text(seconds)} · {percentage:.1f}%", tags=tag)
            canvas.create_rectangle(14, y + 19, width - 14, y + 25, fill="#edf0f4", outline="", tags=tag)
            if seconds > 0:
                canvas.create_rectangle(14, y + 19, 14 + (width - 28) * seconds / largest,
                                        y + 25, fill=COLORS[category], outline="", tags=tag)
            canvas.tag_bind(tag, "<Button-1>", lambda _, name=category: self.choose(name))
        if not total:
            canvas.create_text(width / 2, height - 5, anchor="s", text="暂无可统计时长", fill="#687380")

    def choose(self, category):
        if self.on_category:
            self.on_category(category)

    def draw_timeline(self):
        canvas = self.timeline
        canvas.delete("all")
        width, height = max(430, canvas.winfo_width()), max(230, canvas.winfo_height())
        lanes = CATEGORIES + ("锁屏 / 断开", "采集间隔")
        left, right = 92, width - 18
        spacing = (height - 65) / len(lanes)
        for hour in range(0, 25, 3):
            x = left + (right - left) * hour / 24
            canvas.create_line(x, 28, x, height - 28, fill="#edf0f4")
            canvas.create_text(x, 13, text=f"{hour:02d}", fill="#687380")
        for index, category in enumerate(lanes):
            y = 31 + index * spacing
            canvas.create_text(left - 10, y + spacing / 2, text=category, anchor="e", fill="#253246")
            canvas.create_rectangle(left, y + 3, right, y + spacing - 3, fill="#f7f8fa", outline="")
        for row in self.rows:
            if row.kind == "activity" and not row.seconds:
                continue
            category = row.category if row.kind == "activity" else "锁屏 / 断开" if row.kind == "locked" else "采集间隔"
            index = lanes.index(category)
            midnight = row.start.replace(hour=0, minute=0, second=0, microsecond=0)
            start = max(0, min(86400, (row.start - midnight).total_seconds()))
            end = max(0, min(86400, (row.end - midnight).total_seconds()))
            if end <= start:
                continue
            x1 = left + (right - left) * start / 86400
            x2 = left + (right - left) * end / 86400
            y = 31 + index * spacing
            item = canvas.create_rectangle(x1, y + 4, max(x1 + 1, x2), y + spacing - 4,
                                           fill=COLORS[category], outline="", tags="activity-block")
            text = (f"{row.start:%H:%M:%S}–{row.end:%H:%M:%S}  {category}  "
                    f"{row.app}  {duration_text(row.seconds) if row.seconds is not None else '未计时'}  {row.title}")
            canvas.tag_bind(item, "<Enter>", lambda _, value=text: self.hover.set(value))
        canvas.create_text(left, height - 10, anchor="w", text="00:00 → 24:00；色块按原始时间段绘制", fill="#687380")
