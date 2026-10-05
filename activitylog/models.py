"""Immutable observations and recorded time segments."""

from dataclasses import dataclass, replace
from datetime import datetime, time as day_time, timedelta

CATEGORIES = ("开发", "学习", "求职", "娱乐", "沟通", "其他", "未分类")


def now():
    return datetime.now().astimezone()



def stamp(value):
    return value.isoformat(timespec="milliseconds")



def duration_text(seconds):
    if seconds is None:
        return "未知"
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分 {seconds} 秒"
    if minutes:
        return f"{minutes} 分 {seconds} 秒"
    return f"{seconds} 秒"



@dataclass(frozen=True)
class Activity:
    process: str
    title: str
    pid: int = 0

    @property
    def app(self):
        return {
            "chrome.exe": "浏览器 · Chrome", "msedge.exe": "浏览器 · Edge",
            "firefox.exe": "浏览器 · Firefox", "brave.exe": "浏览器 · Brave",
            "vivaldi.exe": "浏览器 · Vivaldi", "wow.exe": "魔兽世界",
            "wowclassic.exe": "魔兽世界 · 怀旧服", "codex.exe": "Codex",
        }.get(self.process.lower(), self.process or "锁屏 / 会话断开")



@dataclass(frozen=True)
class Segment:
    start: datetime
    end: datetime
    app: str
    process: str
    title: str
    seconds: float | None
    kind: str
    status: str
    reason: str = ""
    resume_reason: str = ""
    parts: tuple = ()
    category: str = "未分类"
    references: tuple[int, ...] = ()

    @property
    def state(self):
        if self.kind == "locked":
            return "锁屏 / 会话断开"
        if self.kind == "gap":
            return "睡眠 / 采集间隔"
        state = {"running": "进行中", "closed": "已结束", "interrupted": "采集中断"}[self.status]
        return f"{state} · 合并 {len(self.parts)} 段" if self.parts else state

    def on_day(self, selected):
        """Clip at midnight in the timezone recorded with the original timestamp."""
        begin = datetime.combine(selected, day_time.min, tzinfo=self.start.tzinfo)
        finish = begin + timedelta(days=1)
        if self.start >= finish or self.end < begin:
            return None
        if self.end == begin and self.start < begin:
            return None
        left, right = max(self.start, begin), min(self.end, finish)
        whole = max(0, (self.end - self.start).total_seconds())
        fraction = max(0, (right - left).total_seconds()) / whole if whole else 1
        seconds = self.seconds * fraction if self.seconds is not None else None
        return replace(self, start=left, end=right, seconds=seconds)
