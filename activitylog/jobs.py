"""Job application models and overview calculations."""

from dataclasses import dataclass
from datetime import date

APPLICATION_STATUSES = ("已投递", "笔试中", "面试中", "已获 Offer", "已拒绝", "已撤回")


@dataclass(frozen=True)
class Company:
    id: int
    name: str


@dataclass(frozen=True)
class Application:
    id: int
    company_id: int
    title: str
    applied_on: date
    status: str
    url: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ApplicationDraft:
    title: str
    applied_on: str
    status: str = "已投递"
    url: str = ""
    notes: str = ""


@dataclass(frozen=True)
class EntryHistory:
    companies: tuple[str, ...]
    titles: tuple[str, ...]


@dataclass(frozen=True)
class ApplicationRow:
    company: Company
    application: Application


@dataclass(frozen=True)
class CompanyGroup:
    company: Company
    applications: tuple[Application, ...]


@dataclass(frozen=True)
class JobSummary:
    applied_companies: int
    applications: int
    interviews: int
    offers: int
    pending_companies: int


@dataclass(frozen=True)
class JobSnapshot:
    groups: tuple[CompanyGroup, ...]
    summary: JobSummary


def job_snapshot(groups: tuple[CompanyGroup, ...]) -> JobSnapshot:
    applications = [application for group in groups for application in group.applications]
    applied = sum(bool(group.applications) for group in groups)
    return JobSnapshot(groups, JobSummary(
        applied_companies=applied, applications=len(applications),
        interviews=sum(application.status == "面试中" for application in applications),
        offers=sum(application.status == "已获 Offer" for application in applications),
        pending_companies=len(groups) - applied,
    ))


def filter_companies(snapshot: JobSnapshot, keyword: str = "", status: str = "全部进度") -> list[CompanyGroup]:
    keyword = keyword.strip().casefold()
    result = []
    for group in snapshot.groups:
        company_matches = not keyword or keyword in group.company.name.casefold()
        applications = tuple(application for application in group.applications
                             if (status == "全部进度" or application.status == status)
                             and (company_matches or keyword in f"{application.title}\n{application.notes}".casefold()))
        if applications or (not group.applications and company_matches and status == "全部进度"):
            result.append(CompanyGroup(group.company, applications))
    return result


def application_rows(snapshot: JobSnapshot, keyword: str = "", status: str = "全部进度") -> list[ApplicationRow]:
    rows = [ApplicationRow(group.company, application)
            for group in filter_companies(snapshot, keyword, status) for application in group.applications]
    return sorted(rows, key=lambda row: (row.application.applied_on, row.application.id), reverse=True)
