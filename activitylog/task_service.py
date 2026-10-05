"""Validated task editing and dated today-list operations."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date

from .task_store import TaskRepository
from .project_store import ProjectRepository
from .projects import Project
from .tasks import TASK_CATEGORIES, TASK_KINDS, TASK_PRIORITIES, TASK_STATUSES, Task, TaskDraft, TaskSnapshot, month_days


class TaskService:
    def __init__(self, repository: TaskRepository, *, today: Callable[[], date] = date.today):
        self.repository = repository
        self.today = today

    def snapshot(self, year: int, month: int, selected: date) -> TaskSnapshot:
        days = [day for day in month_days(year, month) if day is not None]
        today = self.today()
        return TaskSnapshot(self.repository.between(days[0], days[-1]),
                            self.repository.between(selected, selected),
                            self.repository.day_tasks(today), today, self.repository.count(), self.repository.unscheduled())

    def projects(self) -> tuple[Project, ...]:
        return ProjectRepository(self.repository.db).all_projects()

    def milestones(self, project_id: int | None):
        return ProjectRepository(self.repository.db).milestones(project_id) if project_id is not None else ()

    def today_tasks(self) -> tuple[Task, ...]:
        return self.repository.day_tasks(self.today())

    def get(self, identifier: int) -> Task:
        return self.repository.get(identifier)

    def is_in_today(self, identifier: int) -> bool:
        return self.repository.is_on_day(identifier, self.today())

    def save(self, draft: TaskDraft, identifier: int | None = None, *, in_today: bool = False) -> int:
        title = draft.title.strip()
        if not title:
            raise ValueError("请填写事项名称。")
        if len(title) > 120:
            raise ValueError("事项名称最多 120 个字符。")
        try:
            planned_on = date.fromisoformat(draft.planned_on.strip()).isoformat() if draft.planned_on.strip() else ""
        except ValueError as error:
            raise ValueError("安排日期请使用 YYYY-MM-DD，例如 2026-10-04。") from error
        if draft.category not in TASK_CATEGORIES:
            raise ValueError("请选择列表中的分类。")
        if draft.priority not in TASK_PRIORITIES or draft.kind not in TASK_KINDS:
            raise ValueError("请选择列表中的优先级和事项类型。")
        if draft.status is not None and draft.status not in TASK_STATUSES:
            raise ValueError("请选择列表中的事项状态。")
        if draft.project_id is not None and (type(draft.project_id) is not int or draft.project_id <= 0):
            raise ValueError("请选择有效的所属项目。")
        if len(draft.notes) > 10000:
            raise ValueError("备注最多 10000 个字符。")
        if draft.milestone_id is not None and (type(draft.milestone_id) is not int or draft.milestone_id <= 0):
            raise ValueError("请选择有效的里程碑。")
        if len(draft.acceptance) > 2000 or len(draft.outcome) > 10000:
            raise ValueError("验收条件最多 2000 个字符，成果说明最多 10000 个字符。")
        today = self.today()
        valid = replace(draft, title=title, planned_on=planned_on or (today.isoformat() if in_today else ""),
                        notes=draft.notes.strip(), acceptance=draft.acceptance.strip(), outcome=draft.outcome.strip())
        return self.repository.save(valid, identifier, today, in_today)

    def add_today(self, title: str) -> int:
        return self.save(TaskDraft(title, self.today().isoformat()), in_today=True)

    def arrange_today(self, identifier: int) -> None:
        self.repository.set_membership(identifier, self.today(), True)

    def remove_today(self, identifier: int) -> None:
        self.repository.set_membership(identifier, self.today(), False)

    def complete(self, identifier: int, completed: bool) -> None:
        self.repository.complete(identifier, completed)

    def set_status(self, identifier: int, status: str) -> None:
        if status not in TASK_STATUSES:
            raise ValueError("请选择列表中的事项状态。")
        self.repository.set_status(identifier, status)

    def delete(self, identifier: int) -> None:
        self.repository.delete(identifier)
