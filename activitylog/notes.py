"""Timestamped manual notes, independent of tasks and foreground recording."""

from dataclasses import dataclass
from datetime import datetime

from .models import now


@dataclass(frozen=True)
class Note:
    id: int
    title: str
    created_at: datetime


class NoteService:
    def __init__(self, repository, clock=now):
        self.repository, self.clock = repository, clock

    def add(self, title: str) -> int:
        title = title.strip()
        if not title:
            raise ValueError('请输入随笔内容。')
        if len(title) > 500:
            raise ValueError('随笔内容最多 500 个字符。')
        at = self.clock()
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError('记录时间需要包含时区。')
        return self.repository.add(title, at)

    def latest(self) -> tuple[Note, ...]:
        return self.repository.latest()
