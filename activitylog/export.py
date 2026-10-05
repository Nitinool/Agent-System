"""CSV formatting and file output, independent of SQLite and Tk."""

import csv
from pathlib import Path
from collections.abc import Sequence
from .models import Segment, stamp

HEADERS = ("开始时间", "应用", "进程", "窗口标题", "结束时间", "停留秒数", "状态", "说明", "原始段数", "分类")


def safe_cell(value) -> str:
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def export_csv(path: str | Path, rows: Sequence[Segment], *, database_path: Path | None = None) -> int:
    if database_path is not None and Path(path).resolve() == database_path.resolve():
        raise ValueError("不能覆盖日志数据库。")
    with open(path, "w", newline="", encoding="utf-8-sig") as output:
        writer = csv.writer(output)
        writer.writerow(HEADERS)
        for row in reversed(rows):
            writer.writerow(map(safe_cell, (
                stamp(row.start), row.app, row.process, row.title, stamp(row.end),
                round(row.seconds, 3) if row.seconds is not None else "", row.state,
                "合并展示，间隔未计入停留时长；原始记录保留" if row.parts else row.reason,
                len(row.parts) if row.parts else 1, row.category if row.kind == "activity" else "",
            )))
    return len(rows)
