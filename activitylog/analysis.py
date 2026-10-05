"""Pure display transformations; never modify recorded observations."""

from dataclasses import dataclass, replace
from .models import CATEGORIES, Segment


def merge_for_display(rows, max_gap=120):
    """Group logger visits without altering observations or adding unobserved seconds."""
    grouped = []
    for row in reversed(rows):
        previous = grouped[-1] if grouped else None
        same_window = (previous is not None and previous.kind == row.kind == "activity"
                       and previous.process.lower() == row.process.lower()
                       and previous.app == row.app and previous.title == row.title and bool(row.title)
                       and previous.category == row.category
                       and previous.start.date() == row.start.date())
        known_logger_visit = (previous is not None and previous.reason == "查看日志"
                              and row.resume_reason == "查看日志")
        if (same_window and previous.status == "closed" and row.status != "interrupted"
                and 0 <= (row.start - previous.end).total_seconds() <= max_gap
                and known_logger_visit):
            grouped[-1] = replace(previous, end=row.end, seconds=previous.seconds + row.seconds,
                                  status=row.status, reason=row.reason,
                                  parts=(previous.parts or (previous,)) + (row,),
                                  references=previous.references + row.references)
        else:
            grouped.append(row)
    return list(reversed(grouped))



def filter_rows(rows, keyword="", app="全部应用", category="全部分类"):
    keyword = keyword.strip().casefold()
    return [row for row in rows
            if (not keyword or keyword in f"{row.app}\n{row.process}\n{row.title}".casefold())
            and (app == "全部应用" or row.app == app)
            and (category == "全部分类" or row.category == category and row.kind == "activity")]



def category_totals(rows):
    totals = {category: 0.0 for category in CATEGORIES}
    for row in rows:
        if row.kind == "activity" and row.seconds is not None:
            totals[row.category] += row.seconds
    return totals


@dataclass(frozen=True)
class DailySummary:
    app_totals: dict[str, float]
    category_totals: dict[str, float]
    total: float
    locked: float

    @property
    def classified_percent(self) -> float:
        known = self.total - self.category_totals["未分类"]
        return known / self.total * 100 if self.total else 0.0


def summarize(rows) -> DailySummary:
    """Use raw clipped segments for both the table header and category charts."""
    apps = {}
    locked = 0.0
    for row in rows:
        if row.kind == "activity":
            apps[row.app] = apps.get(row.app, 0.0) + (row.seconds or 0)
        elif row.kind == "locked":
            locked += row.seconds or 0
    return DailySummary(apps, category_totals(rows), sum(apps.values()), locked)
