"""Project values; project items are the existing shared tasks."""

from dataclasses import dataclass

PROJECT_STATUSES = ("进行中", "暂停", "已完成")


@dataclass(frozen=True)
class Project:
    id: int
    name: str
    goal: str
    status: str


@dataclass(frozen=True)
class ProjectDraft:
    name: str
    goal: str = ""
    status: str = "进行中"


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
