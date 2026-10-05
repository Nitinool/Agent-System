"""RMB entries and cash-based summaries, independent of the desktop UI."""

from dataclasses import dataclass
from datetime import date
import re

MAX_AMOUNT_CENTS = 100_000_000_000
INCOME_STATUSES = ("已到账", "待结算")
EXPENSE_CATEGORIES = ("餐饮", "交通", "购物", "住房", "娱乐", "医疗", "副业成本", "其他")
INCOME_CATEGORIES = ("工资", "副业收入", "其他")


def parse_amount(text):
    text = text.strip()
    if len(text) > 20 or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", text):
        raise ValueError("金额请填写正数，最多保留两位小数，例如 128.50。")
    whole, _, fraction = text.partition(".")
    cents = int(whole) * 100 + int(fraction.ljust(2, "0"))
    if not 0 < cents <= MAX_AMOUNT_CENTS:
        raise ValueError("金额必须大于 0，且不超过 1,000,000,000 元。")
    return cents


def amount_text(cents):
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole}.{fraction:02d}"


def money_text(cents):
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}¥{whole:,}.{fraction:02d}"


def validate_month(month):
    try:
        if month and (not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month)
                      or date.fromisoformat(month + "-01").isoformat()[:7] != month):
            raise ValueError()
    except ValueError:
        raise ValueError("月份请使用 YYYY-MM，例如 2026-10。") from None
    return month


@dataclass(frozen=True)
class FinanceDraft:
    direction: str
    amount: str
    occurred_on: str
    title: str = ""
    category: str = "其他"
    side_source: str = ""
    status: str = "已支付"
    settled_on: str = ""
    notes: str = ""


@dataclass(frozen=True)
class FinanceEntry:
    id: int
    direction: str
    amount_cents: int
    occurred_on: date
    title: str
    category: str
    side_source: str
    status: str
    settled_on: date | None
    notes: str

    @property
    def effective_day(self):
        return self.settled_on or self.occurred_on


@dataclass(frozen=True)
class FinanceTotals:
    income: int
    expense: int
    pending: int
    pending_count: int

    @property
    def net(self):
        return self.income - self.expense


@dataclass(frozen=True)
class SideSummary:
    source: str
    totals: FinanceTotals


@dataclass(frozen=True)
class FinanceSnapshot:
    entries: tuple[FinanceEntry, ...]
    pending_entries: tuple[FinanceEntry, ...]
    totals: FinanceTotals
    sources: tuple[SideSummary, ...]


def finance_snapshot(entries, month):
    validate_month(month)
    current = tuple(e for e in entries if not month or e.effective_day.isoformat()[:7] == month)
    pending = tuple(e for e in entries if e.status == "待结算")

    def totals(rows, unsettled):
        return FinanceTotals(sum(e.amount_cents for e in rows if e.status == "已到账"),
                             sum(e.amount_cents for e in rows if e.status == "已支付"),
                             sum(e.amount_cents for e in unsettled), len(unsettled))

    groups = {}
    for entry in entries:
        if entry.side_source:
            groups.setdefault(entry.side_source.casefold(), []).append(entry)
    sources = []
    for rows in groups.values():
        name = min(e.side_source for e in rows)
        paid = [e for e in rows if e.status != "待结算" and (not month or e.effective_day.isoformat()[:7] == month)]
        unsettled = [e for e in rows if e.status == "待结算"]
        if paid or unsettled:
            sources.append(SideSummary(name, totals(paid, unsettled)))
    sources.sort(key=lambda s: (-s.totals.income, -s.totals.pending, s.source.casefold()))
    return FinanceSnapshot(current, pending, totals(current, pending), tuple(sources))


def filter_entries(entries, keyword="", direction="全部收支", status="全部状态", source="全部来源"):
    keyword = keyword.strip().casefold()
    return tuple(e for e in entries
                 if (direction == "全部收支" or e.direction == direction)
                 and (status == "全部状态" or e.status == status)
                 and (source == "全部来源" or (not e.side_source if source == "日常收支" else e.side_source.casefold() == source.casefold()))
                 and (not keyword or keyword in f"{e.title}\n{e.category}\n{e.side_source}\n{e.notes}".casefold()))
