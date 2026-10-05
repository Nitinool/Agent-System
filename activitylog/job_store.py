"""Job application persistence; the activity Store owns the shared connection."""

from datetime import date
import sqlite3
from .jobs import Application, ApplicationDraft, Company, CompanyGroup, EntryHistory

JOB_SCHEMA = (
    """CREATE TABLE job_companies (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE)""",
    """CREATE TABLE job_applications (
        id INTEGER PRIMARY KEY,
        company_id INTEGER NOT NULL REFERENCES job_companies(id) ON DELETE CASCADE,
        title TEXT NOT NULL, applied_on TEXT NOT NULL, status TEXT NOT NULL,
        url TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '')""",
    "CREATE INDEX application_company ON job_applications(company_id)",
)


class JobRepository:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def groups(self) -> tuple[CompanyGroup, ...]:
        companies = self.db.execute("SELECT id, name FROM job_companies ORDER BY id DESC").fetchall()
        applications = self.db.execute("SELECT * FROM job_applications ORDER BY applied_on DESC, id DESC").fetchall()
        by_company = {company["id"]: [] for company in companies}
        for record in applications:
            by_company[record["company_id"]].append(Application(
                id=record["id"], company_id=record["company_id"], title=record["title"],
                applied_on=date.fromisoformat(record["applied_on"]), status=record["status"],
                url=record["url"], notes=record["notes"],
            ))
        return tuple(CompanyGroup(Company(company["id"], company["name"]),
                                  tuple(by_company[company["id"]])) for company in companies)

    def has_company(self, identifier: int) -> bool:
        return self.db.execute("SELECT 1 FROM job_companies WHERE id=?", (identifier,)).fetchone() is not None

    def add_company(self, name: str) -> int:
        with self.db:
            cursor = self.db.execute("INSERT INTO job_companies(name, name_key) VALUES (?, ?)", (name, name.casefold()))
        return cursor.lastrowid

    def rename_company(self, identifier: int, name: str) -> None:
        with self.db:
            cursor = self.db.execute("UPDATE job_companies SET name=?, name_key=? WHERE id=?",
                                     (name, name.casefold(), identifier))
            if not cursor.rowcount:
                raise ValueError("公司记录已不存在，请刷新后重试。")

    def delete_company(self, identifier: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM job_companies WHERE id=?", (identifier,))

    def add_application(self, company_id: int, draft: ApplicationDraft) -> int:
        with self.db:
            cursor = self.db.execute("""INSERT INTO job_applications
                (company_id, title, applied_on, status, url, notes) VALUES (?, ?, ?, ?, ?, ?)""",
                (company_id, draft.title, draft.applied_on, draft.status, draft.url, draft.notes))
        return cursor.lastrowid

    def update_application(self, identifier: int, draft: ApplicationDraft) -> None:
        with self.db:
            cursor = self.db.execute("""UPDATE job_applications SET title=?, applied_on=?, status=?, url=?, notes=?
                WHERE id=?""", (draft.title, draft.applied_on, draft.status, draft.url, draft.notes, identifier))
            if not cursor.rowcount:
                raise ValueError("岗位记录已不存在，请刷新后重试。")

    def delete_application(self, identifier: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM job_applications WHERE id=?", (identifier,))

    def history(self) -> EntryHistory:
        companies = tuple(row[0] for row in self.db.execute("SELECT name FROM job_companies ORDER BY id DESC"))
        titles = []
        seen = set()
        for row in self.db.execute("SELECT title FROM job_applications ORDER BY id DESC"):
            key = row[0].casefold()
            if key not in seen:
                titles.append(row[0])
                seen.add(key)
        return EntryHistory(companies, tuple(titles))

    def save_application(self, company_name: str, draft: ApplicationDraft, identifier: int | None = None) -> int:
        """Resolve the company and write the application in one transaction."""
        with self.db:
            if identifier is not None and self.db.execute(
                    "SELECT 1 FROM job_applications WHERE id=?", (identifier,)).fetchone() is None:
                raise ValueError("岗位记录已不存在，请刷新后重试。")
            company = self.db.execute("SELECT id FROM job_companies WHERE name_key=?",
                                      (company_name.casefold(),)).fetchone()
            if company is None:
                cursor = self.db.execute("INSERT INTO job_companies(name, name_key) VALUES (?, ?)",
                                         (company_name, company_name.casefold()))
                company_id = cursor.lastrowid
            else:
                company_id = company[0]
            values = (company_id, draft.title, draft.applied_on, draft.status, draft.url, draft.notes)
            if identifier is None:
                cursor = self.db.execute("""INSERT INTO job_applications
                    (company_id, title, applied_on, status, url, notes) VALUES (?, ?, ?, ?, ?, ?)""", values)
                identifier = cursor.lastrowid
            else:
                self.db.execute("""UPDATE job_applications SET company_id=?, title=?, applied_on=?, status=?, url=?, notes=?
                    WHERE id=?""", values + (identifier,))
        return identifier
