"""Validation and financial operations; pending income is not received cash."""

from datetime import date
from .finance import FinanceDraft, INCOME_STATUSES, finance_snapshot, parse_amount


def canonical_day(text, label):
    text = text.strip()
    try:
        parsed = date.fromisoformat(text)
        if parsed.isoformat() != text:
            raise ValueError()
    except ValueError:
        raise ValueError(f"{label}请使用 YYYY-MM-DD，例如 2026-10-05。") from None
    return text


class FinanceService:
    def __init__(self, repository):
        self.repository = repository

    def snapshot(self, month):
        return finance_snapshot(self.repository.entries(), month)

    def get(self, identifier):
        return self.repository.get(identifier)

    def history(self):
        rows = self.repository.entries()
        sources = {}
        for row in rows:
            if row.side_source:
                key = row.side_source.casefold()
                sources[key] = min(row.side_source, sources.get(key, row.side_source))
        return tuple(sorted(sources.values(), key=str.casefold)), tuple(sorted({r.category for r in rows}))

    def save(self, draft: FinanceDraft, identifier=None):
        if draft.direction not in ("收入", "支出"):
            raise ValueError("请选择收入或支出。")
        if draft.status not in (INCOME_STATUSES if draft.direction == "收入" else ("已支付",)):
            raise ValueError("待结算仅适用于副业收入；支出请记录实际支付的金额。")
        amount = parse_amount(draft.amount)
        occurred = canonical_day(draft.occurred_on, "交易日期")
        category, source, notes = draft.category.strip(), draft.side_source.strip(), draft.notes.strip()
        title = draft.title.strip() or category
        if not category or len(category) > 100 or not title or len(title) > 500 or len(source) > 100 or len(notes) > 10000:
            raise ValueError("请填写分类；说明最多 500 字，分类和副业来源最多 100 字，备注最多 10000 字。")
        if source in ("全部来源", "日常收支"):
            raise ValueError("副业来源请使用具体名称，例如接单或二手交易。")
        if draft.status == "待结算":
            if not source:
                raise ValueError("待结算收入请填写副业来源，例如二手交易。")
            settled = None
        else:
            settled = canonical_day(draft.settled_on or occurred, "到账 / 支付日期")
            if settled < occurred:
                raise ValueError("到账 / 支付日期不能早于交易日期。")
        return self.repository.save(dict(direction=draft.direction, amount_cents=amount, occurred_on=occurred,
                                         title=title, category=category, side_source=source, status=draft.status,
                                         settled_on=settled, notes=notes), identifier)

    def delete(self, identifier):
        self.repository.delete(identifier)
