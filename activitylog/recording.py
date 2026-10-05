"""Turn foreground samples into bounded, durable time segments."""

import os
import time
from datetime import datetime
from typing import Callable
from .models import Activity, now
from .contracts import RecordingStore
from .config import CapturePolicy


class Recorder:
    def __init__(self, store: RecordingStore, *, policy: CapturePolicy = CapturePolicy(),
                 wall_clock: Callable[[], datetime] = now,
                 monotonic: Callable[[], float] = time.monotonic, process_id: int | None = None):
        self.store = store
        self.policy = policy
        self.wall_clock = wall_clock
        self.monotonic = monotonic
        self.process_id = os.getpid() if process_id is None else process_id
        self.current = None
        self.key = None
        self.last_at = None
        self.last_tick = None
        self.seconds = 0
        self.returning_from_logger = False

    def stop(self, reason="暂停记录"):
        # Bound unobserved time by ending at the last sample, including on close.
        try:
            if self.current is not None:
                self.store.finish(self.current, self.last_at, self.seconds, reason)
        finally:
            self._clear_segment()
            self.last_at = self.last_tick = None

    def _clear_segment(self):
        self.current = self.key = None
        self.seconds = 0
        self.returning_from_logger = False

    def sample(self, activity: Activity | None, excluded=(), *, at=None, tick=None, locked=False) -> bool:
        at = at or self.wall_clock()
        tick = self.monotonic() if tick is None else tick
        delta = tick - self.last_tick if self.last_tick is not None else 0
        wall_delta = (at - self.last_at).total_seconds() if self.last_at is not None else 0
        changed = False
        # A late callback can be sleep, process suspension, or a blocked UI. Be conservative.
        late = delta > self.policy.max_sample_gap or delta < 0
        clock_changed = abs(wall_delta - delta) > self.policy.clock_tolerance
        if self.last_at is not None and (late or clock_changed):
            self._break_sampling(at, wall_delta)
            changed = True
            delta = 0

        if locked:
            self.returning_from_logger = False
            # Don't attribute the interval leading up to lock detection to the application.
            if self.current is not None and self.key != ("locked",):
                self.store.finish(self.current, self.last_at, self.seconds, "检测到锁屏或会话断开")
                self.current = self.key = None
                self.seconds = 0
                changed = True
            key = ("locked",)
            activity = Activity("", "锁屏或会话断开")
        elif activity is None or activity.pid == self.process_id or activity.process.lower() in excluded:
            changed = self._skip_activity(activity, at, delta) or changed
            self.last_at, self.last_tick = at, tick
            return changed
        else:
            key = (activity.pid, activity.process.lower(), activity.title)

        if self.current is not None and self.key == key:
            next_seconds = self.seconds + delta
            self.store.checkpoint(self.current, at, next_seconds)
            self.seconds = next_seconds
        else:
            if self.current is not None:
                self.store.finish(self.current, at, self.seconds + delta, "窗口切换")
                # If beginning the next segment fails, don't finish the previous one twice.
                self.current = self.key = None
                self.seconds = 0
            resume_reason = "查看日志" if self.returning_from_logger else "其他 / 未知"
            self.current = self.store.begin(activity, at, "locked" if locked else "activity", resume_reason)
            self.returning_from_logger = False
            self.key = key
            self.seconds = 0
            changed = True
        self.last_at, self.last_tick = at, tick
        return changed

    def _break_sampling(self, at: datetime, wall_delta: float) -> None:
        if self.current is not None:
            self.store.finish(self.current, self.last_at, self.seconds, "采样中断", interrupted=True)
        if wall_delta > 0:
            self.store.gap(self.last_at, at)
        self._clear_segment()

    def _skip_activity(self, activity: Activity | None, at: datetime, delta: float) -> bool:
        own_window = activity is not None and activity.pid == self.process_id
        if own_window and self.current is not None and self.key != ("locked",):
            self.returning_from_logger = True
        elif not own_window:
            self.returning_from_logger = False
        changed = self.current is not None
        if changed:
            # Unavailable samples stop at the last confirmed observation.
            confirmed = activity is not None
            reason = "查看日志" if own_window else "窗口不可读取" if activity is None else "排除进程"
            self.store.finish(self.current, at if confirmed else self.last_at,
                              self.seconds + delta if confirmed else self.seconds, reason)
        self.current = self.key = None
        self.seconds = 0
        return changed
