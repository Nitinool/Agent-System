"""Project editing and a filtered view of the shared task records."""

import sqlite3
from datetime import datetime

from .project_store import ProjectRepository
from .projects import PROJECT_STATUSES, MilestoneDraft, Project, ProjectDraft, ProjectSummary
from .task_service import TaskService
from .tasks import TASK_STATUSES, Task


class ProjectService:
    def __init__(self, repository: ProjectRepository, tasks: TaskService):
        self.repository = repository
        self.tasks = tasks

    def summaries(self) -> tuple[ProjectSummary, ...]:
        return self.repository.summaries()

    def get(self, identifier: int) -> Project:
        return self.repository.get(identifier)

    def items(self, identifier: int, keyword: str = "", status: str = "全部状态") -> tuple[Task, ...]:
        if status != "全部状态" and status not in TASK_STATUSES:
            raise ValueError("请选择列表中的事项状态。")
        return self.tasks.repository.project_tasks(identifier, keyword.strip(), status)

    def save(self, draft: ProjectDraft, identifier: int | None = None) -> int:
        name = draft.name.strip()
        if not name or len(name) > 120:
            raise ValueError("项目名称请填写 1 到 120 个字符。")
        if len(draft.goal) > 2000:
            raise ValueError("项目目标最多 2000 个字符。")
        if draft.status not in PROJECT_STATUSES:
            raise ValueError("请选择列表中的项目状态。")
        try:
            return self.repository.save(ProjectDraft(name, draft.goal.strip(), draft.status), identifier)
        except sqlite3.IntegrityError as error:
            raise ValueError("同名项目已经存在，请使用其他名称。") from error

    def delete(self, identifier: int) -> None:
        self.repository.delete(identifier)

    def milestones(self, project_id: int):
        return self.repository.milestones(project_id)

    def save_milestone(self, project_id: int, draft: MilestoneDraft, identifier: int | None = None) -> int:
        name = draft.name.strip()
        if not name or len(name) > 60:
            raise ValueError("里程碑名称请填写 1 到 60 个字符。")
        if len(draft.acceptance) > 2000:
            raise ValueError("里程碑验收条件最多 2000 个字符。")
        return self.repository.save_milestone(project_id, MilestoneDraft(name, draft.acceptance.strip()), identifier)

    def finish_milestone(self, identifier: int) -> None:
        self.repository.finish_milestone(identifier, datetime.now().astimezone().isoformat(timespec='seconds'))

    def delete_milestone(self, identifier: int) -> None:
        self.repository.delete_milestone(identifier)

    def completion_records(self, project_id: int):
        return self.repository.completion_records(project_id)
