"""Project values; project items are the existing shared tasks."""

from dataclasses import dataclass

PROJECT_STATUSES = ("进行中", "暂停", "已完成")
PROJECT_LANES = ("Active", "Planning", "Archive")
PROJECT_MODES = ("目标型", "探索型")
LANE_STATUS = dict(zip(PROJECT_LANES, PROJECT_STATUSES))


def project_code(key):
    return "P" + key[:8].upper() if key else ""


@dataclass(frozen=True)
class Project:
    id: int
    name: str
    goal: str
    status: str
    priority: str = "普通"
    mode: str = "目标型"
    key: str = ""

    @property
    def lane(self):
        return PROJECT_LANES[PROJECT_STATUSES.index(self.status)]

    @property
    def code(self):
        return project_code(self.key)


@dataclass(frozen=True)
class ProjectDraft:
    name: str
    goal: str = ""
    status: str = "进行中"
    priority: str = "普通"
    mode: str = "目标型"


@dataclass(frozen=True)
class ProjectSummary:
    project: Project
    total: int
    completed: int


@dataclass(frozen=True)
class Milestone:
    id: int
    project_id: int
    name: str
    acceptance: str
    position: int
    completed_at: str | None
    total: int
    completed: int


@dataclass(frozen=True)
class MilestoneDraft:
    name: str
    acceptance: str = ""


@dataclass(frozen=True)
class CompletionRecord:
    id: int
    task_id: int
    title: str
    completed_at: str
    reopened_at: str | None
    outcome: str
