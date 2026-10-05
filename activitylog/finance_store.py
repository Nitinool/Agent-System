"""Financial entries share the Store connection; amounts are integer cents."""

from datetime import date
from .finance import FinanceEntry, MAX_AMOUNT_CENTS

FINANCE_SCHEMA = (
    f"""CREATE TABLE finance_entries (
        id INTEGER PRIMARY KEY,
        direction TEXT NOT NULL CHECK(direction IN ('收入', '支出')),
        amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents>0 AND amount_cents<={MAX_AMOUNT_CENTS}),
        occurred_on TEXT NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL,
        side_source TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
        settled_on TEXT, notes TEXT NOT NULL DEFAULT '',
        CHECK((direction='收入' AND status='待结算' AND side_source<>'' AND settled_on IS NULL)
           OR (direction='收入' AND status='已到账' AND settled_on IS NOT NULL)
           OR (direction='支出' AND status='已支付' AND settled_on IS NOT NULL)))""",
    "CREATE INDEX finance_dates ON finance_entries(settled_on, occurred_on)",
)


class FinanceRepository:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def _entry(row):
        return FinanceEntry(row["id"], row["direction"], row["amount_cents"], date.fromisoformat(row["occurred_on"]),
                            row["title"], row["category"], row["side_source"], row["status"],
                            date.fromisoformat(row["settled_on"]) if row["settled_on"] else None, row["notes"])

    def entries(self):
        rows = self.db.execute("SELECT * FROM finance_entries ORDER BY COALESCE(settled_on, occurred_on) DESC, id DESC")
        return tuple(self._entry(row) for row in rows)

    def get(self, identifier):
        row = self.db.execute("SELECT * FROM finance_entries WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("这条账目已不存在，请刷新后重试。")
        return self._entry(row)

    def save(self, values, identifier=None):
        with self.db:
            if identifier is None:
                cursor = self.db.execute(f"INSERT INTO finance_entries({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})", tuple(values.values()))
                return cursor.lastrowid
            cursor = self.db.execute(f"UPDATE finance_entries SET {', '.join(key + '=?' for key in values)} WHERE id=?", (*values.values(), identifier))
            if not cursor.rowcount:
                raise ValueError("这条账目已不存在，请刷新后重试。")
        return identifier

    def delete(self, identifier):
        with self.db:
            cursor = self.db.execute("DELETE FROM finance_entries WHERE id=?", (identifier,))
            if not cursor.rowcount:
                raise ValueError("这条账目已不存在，请刷新后重试。")
