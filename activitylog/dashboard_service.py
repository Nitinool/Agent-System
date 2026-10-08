"""Read-only home summaries composed from the existing business services."""

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from .finance import FinanceTotals
from .jobs import JobSummary
from .projects import LANE_STATUS, ProjectSummary
from .tasks import TASK_PRIORITIES, Task

if TYPE_CHECKING:
    from .service import DaySnapshot


@dataclass(frozen=True)
class DashboardProject:
    summary: ProjectSummary
    stage: str
    completion_count: int


@dataclass(frozen=True)
class DashboardSnapshot:
    day: date
    tasks: tuple[Task, ...]
    finance: FinanceTotals
    projects: tuple[DashboardProject, ...]
    jobs: JobSummary
    activity: "DaySnapshot"


class DashboardService:
    def __init__(self, activity_service):
        self.activity_service = activity_service

    def snapshot(self):
        service = self.activity_service
        day = service.tasks.today()
        active = [s for s in service.projects.summaries() if s.project.status == LANE_STATUS['Active']]
        active.sort(key=lambda s: (TASK_PRIORITIES.index(s.project.priority), -s.project.id))
        projects = []
        for summary in active:
            stages = service.projects.milestones(summary.project.id)
            current = next((s for s in stages if s.completed < s.total), stages[-1] if stages else None)
            stage = f'阶段 {stages.index(current) + 1} · {current.name}' if current else ''
            events = len(service.projects.completion_records(summary.project.id)) if summary.project.mode == '探索型' else 0
            projects.append(DashboardProject(summary, stage, events))
        return DashboardSnapshot(day, service.tasks.today_tasks(day=day),
                                 service.finance.snapshot(day.strftime('%Y-%m')).totals,
                                 tuple(projects), service.jobs.snapshot().summary,
                                 service.day_snapshot(day))
