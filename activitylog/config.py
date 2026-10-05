"""Capture and presentation timing; defaults preserve the current behavior."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CapturePolicy:
    max_sample_gap: float = 5.0
    clock_tolerance: float = 2.0


@dataclass(frozen=True)
class ViewPolicy:
    poll_ms: int = 1000
    refresh_samples: int = 5
    filter_delay_ms: int = 180
    row_limit: int = 1000
    merge_gap_seconds: float = 120.0
