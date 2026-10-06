"""Task values and calendar dates, independent of Tk and persistence."""

import calendar
from dataclasses import dataclass
from datetime import date

TASK_CATEGORIES = ("其他", "开发", "学习", "求职", "生活", "娱乐", "沟通")
TASK_PRIORITIES = ("紧急", "高", "普通", "低")
TASK_STATUSES = ("待开始", "进行中", "受阻", "已完成")
TASK_KINDS = ("任务", "功能", "问题")


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    planned_on: date | None
    category: str
    notes: str
    status: str
    priority: str = "普通"
    kind: str = "任务"
    project_id: int | None = None
    resume_status: str = "待开始"
    milestone_id: int | None = None
    acceptance: str = ""
    outcome: str = ""
    completed_at: str | None = None
    range_start: date | None = None
    range_end: date | None = None
    project_code: str = ""

    @property
    def completed(self) -> bool:
        return self.status == "已完成"


@dataclass(frozen=True)
class TaskDraft:
    title: str
    planned_on: str
    category: str = "其他"
    notes: str = ""
    priority: str = "普通"
    kind: str = "任务"
    status: str | None = None
    project_id: int | None = None
    milestone_id: int | None = None
    acceptance: str = ""
    outcome: str = ""
    range_start: str = ""
    range_end: str = ""


@dataclass(frozen=True)
class TaskSnapshot:
    calendar_tasks: tuple[Task, ...]
    selected_tasks: tuple[Task, ...]
    today_tasks: tuple[Task, ...]
    today: date
    total: int
    unscheduled_tasks: tuple[Task, ...] = ()


def month_days(year: int, month: int) -> tuple[date | None, ...]:
    """Monday-first complete weeks, including the adjacent-month edge dates."""
    first = date(year, month, 1)
    offset, count = calendar.monthrange(year, month)
    start = first.toordinal() - offset
    cells = ((offset + count + 6) // 7) * 7
    return tuple(date.fromordinal(ordinal) if 1 <= ordinal <= date.max.toordinal() else None
                 for ordinal in range(start, start + cells))
