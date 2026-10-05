"""Validated company/application operations, independent of the desktop UI."""

from datetime import date
import sqlite3
from urllib.parse import urlsplit
from .job_store import JobRepository
from .jobs import ApplicationDraft, APPLICATION_STATUSES, EntryHistory, JobSnapshot, job_snapshot


class JobService:
    def __init__(self, repository: JobRepository):
        self.repository = repository

    def snapshot(self) -> JobSnapshot:
        return job_snapshot(self.repository.groups())

    def history(self) -> EntryHistory:
        return self.repository.history()

    def save_application(self, company_name: str, draft: ApplicationDraft, identifier: int | None = None) -> int:
        company_name = self._company_name(company_name)
        draft = self._validate(draft)
        return self.repository.save_application(company_name, draft, identifier)

    def add_company(self, name: str) -> int:
        name = self._company_name(name)
        try:
            return self.repository.add_company(name)
        except sqlite3.IntegrityError as error:
            raise ValueError("这家公司已经存在，请在该公司下新增岗位。") from error

    def rename_company(self, identifier: int, name: str) -> None:
        name = self._company_name(name)
        try:
            self.repository.rename_company(identifier, name)
        except sqlite3.IntegrityError as error:
            raise ValueError("这家公司已经存在，请使用其他名称。") from error

    def delete_company(self, identifier: int) -> None:
        self.repository.delete_company(identifier)

    def add_application(self, company_id: int, draft: ApplicationDraft) -> int:
        draft = self._validate(draft)
        if not self.repository.has_company(company_id):
            raise ValueError("公司记录已不存在，请刷新后重试。")
        return self.repository.add_application(company_id, draft)

    def update_application(self, identifier: int, draft: ApplicationDraft) -> None:
        self.repository.update_application(identifier, self._validate(draft))

    def delete_application(self, identifier: int) -> None:
        self.repository.delete_application(identifier)

    @staticmethod
    def _company_name(name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("请填写公司名称。")
        return name

    @staticmethod
    def _validate(draft: ApplicationDraft) -> ApplicationDraft:
        title = draft.title.strip()
        if not title:
            raise ValueError("请填写已投岗位名称。")
        try:
            applied_on = date.fromisoformat(draft.applied_on.strip()).isoformat()
        except ValueError as error:
            raise ValueError("投递日期请使用 YYYY-MM-DD，例如 2026-10-04。") from error
        if draft.status not in APPLICATION_STATUSES:
            raise ValueError("请选择列表中的投递进度。")
        url = draft.url.strip()
        if url:
            try:
                parsed = urlsplit(url)
                valid_url = parsed.scheme in ("http", "https") and bool(parsed.hostname)
            except ValueError:
                valid_url = False
            if not valid_url or any(character.isspace() for character in url):
                raise ValueError("岗位链接请填写完整的 http:// 或 https:// 地址。")
        return ApplicationDraft(title, applied_on, draft.status, url, draft.notes.strip())
