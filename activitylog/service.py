"""Application operations shared by the UI and headless tests."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from .analysis import DailySummary, filter_rows, merge_for_display, summarize
from .config import ViewPolicy
from .contracts import ActivityReader
from .export import export_csv
from .models import Segment
from .recording import Recorder
from .storage import Store
from .job_service import JobService
from .job_store import JobRepository
from .task_service import TaskService
from .task_store import TaskRepository
from .project_service import ProjectService
from .project_store import ProjectRepository


@dataclass(frozen=True)
class CaptureResult:
    changed: bool
    locked: bool | None

    @property
    def status(self) -> str:
        if self.locked is True:
            return "正在记录 · 已锁屏 / 会话断开"
        if self.locked is None:
            return "会话状态不可读取，等待恢复"
        return "正在记录 · 可以最小化窗口"


@dataclass(frozen=True)
class DaySnapshot:
    day: date
    rows: tuple[Segment, ...]
    summary: DailySummary


class ActivityService:
    def __init__(self, store: Store, reader: ActivityReader, *, recorder: Recorder | None = None,
                 view_policy: ViewPolicy = ViewPolicy()):
        self.store = store
        self.reader = reader
        self.recorder = recorder if recorder is not None else Recorder(store)
        self.view_policy = view_policy
        self.jobs = JobService(JobRepository(store.db))
        self.tasks = TaskService(TaskRepository(store.db))
        self.projects = ProjectService(ProjectRepository(store.db), self.tasks)

    def capture(self, exclusions: str = "") -> CaptureResult:
        excluded = {name.strip().lower() for name in exclusions.replace("，", ",").split(",") if name.strip()}
        locked = self.reader.is_locked()
        activity = self.reader.read() if locked is False else None
        changed = self.recorder.sample(activity, excluded, locked=locked is True)
        return CaptureResult(changed, locked)

    def pause(self, reason: str = "暂停记录") -> None:
        self.recorder.stop(reason)

    def day_snapshot(self, day: date) -> DaySnapshot:
        rows = tuple(self.store.rows(day))
        return DaySnapshot(day, rows, summarize(rows))

    def visible_rows(self, snapshot: DaySnapshot, *, merged: bool = True, keyword: str = "",
                     app: str = "全部应用", category: str = "全部分类") -> list[Segment]:
        rows = merge_for_display(snapshot.rows, self.view_policy.merge_gap_seconds) if merged else snapshot.rows
        return filter_rows(rows, keyword, app, category)

    def classify(self, references, category: str) -> None:
        self.store.set_category(references, category)

    def export(self, path: str | Path, selected: date | None = None, *, merged: bool = False) -> int:
        rows = self.store.rows(selected)
        if merged:
            rows = merge_for_display(rows, self.view_policy.merge_gap_seconds)
        return export_csv(path, rows, database_path=self.store.path)

    def close(self) -> None:
        try:
            self.pause("关闭软件")
        finally:
            self.store.close()
