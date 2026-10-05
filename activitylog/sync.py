"""Transport-independent snapshots and conservative, record-level three-way merge."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
import json
import re

from .jobs import APPLICATION_STATUSES
from .projects import PROJECT_STATUSES
from .tasks import TASK_CATEGORIES, TASK_KINDS, TASK_PRIORITIES, TASK_STATUSES

REPOSITORY = "Nitinool/Agent-System-data"
REMOTE_PATH = "sync/records.json"
MAX_BYTES = 900_000
FIELDS = {
    "projects": ("name", "goal", "status"),
    "milestones": ("project_id", "name", "acceptance", "position", "completed_at"),
    "tasks": ("title", "planned_on", "category", "notes", "status", "priority", "kind",
              "project_id", "resume_status", "milestone_id", "acceptance", "outcome", "completed_at",
              "days", "completions"),
    "job_applications": ("company", "title", "applied_on", "status", "url", "notes"),
}
EVENT_FIELDS = {"title", "project_id", "completed_at", "reopened_at"}


class SyncError(Exception):
    """A safe, user-facing failure; never includes credentials or HTTP response bodies."""


class RemoteChanged(SyncError):
    pass


class LocalChanged(SyncError):
    pass


def _day(value):
    if not isinstance(value, str):
        raise ValueError()
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError()


def _timestamp(value):
    if not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None:
        raise ValueError()


def validate(records):
    """Reject malformed data before any local or remote mutation."""
    try:
        if not isinstance(records, dict):
            raise ValueError()
        names = set()
        for uid, record in records.items():
            if not isinstance(uid, str) or not re.fullmatch(r"[0-9a-f]{32}", uid):
                raise ValueError()
            if not isinstance(record, dict) or set(record) != {"kind", "fields"}:
                raise ValueError()
            kind, fields = record["kind"], record["fields"]
            if kind not in FIELDS:
                raise ValueError()
            if fields is None:
                continue
            if not isinstance(fields, dict) or set(fields) != set(FIELDS[kind]):
                raise ValueError()
            for key, value in fields.items():
                if key in ("days", "completions", "position"):
                    continue
                if key in ("project_id", "milestone_id", "planned_on", "completed_at") and value is None:
                    continue
                if not isinstance(value, str) or len(value) > 10000:
                    raise ValueError()
            title = fields.get("name", fields.get("title", ""))
            if not title.strip() or len(title) > 500:
                raise ValueError()
            for key in ("planned_on", "applied_on"):
                if fields.get(key) is not None:
                    _day(fields[key])
            if fields.get("completed_at") is not None:
                _timestamp(fields["completed_at"])
            if kind == "projects":
                if fields["status"] not in PROJECT_STATUSES:
                    raise ValueError()
                name = fields["name"].casefold()
                if name in names:
                    raise SyncError("两台电脑存在不同编号的同名项目，请先将其中一个项目改名再同步。")
                names.add(name)
            if kind == "job_applications":
                if not fields["company"].strip() or fields["status"] not in APPLICATION_STATUSES:
                    raise ValueError()
                if fields["url"]:
                    from urllib.parse import urlsplit
                    url = urlsplit(fields["url"])
                    if url.scheme not in ("http", "https") or not url.hostname or any(c.isspace() for c in fields["url"]):
                        raise ValueError()
            if kind == "milestones" and (type(fields["position"]) is not int or fields["position"] < 0):
                raise ValueError()
            if kind == "tasks":
                for key, choices in (("status", TASK_STATUSES), ("resume_status", TASK_STATUSES[:-1]),
                                     ("kind", TASK_KINDS), ("category", TASK_CATEGORIES), ("priority", TASK_PRIORITIES)):
                    if fields[key] not in choices:
                        raise ValueError()
                if fields["status"] != "已完成" and fields["completed_at"] is not None:
                    raise ValueError()
                if not isinstance(fields["days"], list) or fields["days"] != sorted(set(fields["days"])):
                    raise ValueError()
                for day in fields["days"]:
                    _day(day)
                if not isinstance(fields["completions"], list):
                    raise ValueError()
                for event in fields["completions"]:
                    if not isinstance(event, dict) or set(event) != EVENT_FIELDS or not isinstance(event["title"], str):
                        raise ValueError()
                    _timestamp(event["completed_at"])
                    if event["reopened_at"] is not None:
                        _timestamp(event["reopened_at"])
                    _reference(records, event["project_id"], "projects", optional=True)
            _reference(records, fields.get("project_id"), "projects", optional=kind != "milestones")
            _reference(records, fields.get("milestone_id"), "milestones", optional=True)
            if kind == "tasks" and fields["milestone_id"]:
                stage = records[fields["milestone_id"]]["fields"]
                if stage["project_id"] != fields["project_id"]:
                    raise ValueError()
        for uid, record in records.items():
            fields = record["fields"]
            if record["kind"] == "milestones" and fields and fields["completed_at"]:
                items = [r["fields"] for r in records.values() if r["kind"] == "tasks" and r["fields"] and r["fields"]["milestone_id"] == uid]
                if not items or any(t["status"] != "已完成" for t in items):
                    raise ValueError()
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise SyncError("同步数据格式或关联关系无效，未覆盖本地数据。") from error


def _reference(records, uid, kind, optional):
    if uid is None and optional:
        return
    record = records.get(uid)
    if not record or record["kind"] != kind or record["fields"] is None:
        raise ValueError()


def encode(records):
    validate(records)
    content = json.dumps({"format": "agent-system-data", "version": 1, "records": records},
                         ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise SyncError("同步数据超过本版 900 KB 上限，需要分批同步；本地数据仍保留。")
    return content


def decode(content):
    try:
        if len(content.encode("utf-8")) > MAX_BYTES:
            raise ValueError()
        def unique_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        payload = json.loads(content, object_pairs_hook=unique_keys)
        if set(payload) != {"format", "version", "records"} or payload["format"] != "agent-system-data" or type(payload["version"]) is not int or payload["version"] != 1:
            raise ValueError()
        validate(payload["records"])
        return payload["records"]
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise SyncError("远端同步文件损坏或版本不受支持，未覆盖本地数据。") from error


@dataclass(frozen=True)
class Conflict:
    uid: str
    base: dict | None
    local: dict
    remote: dict

    @property
    def title(self):
        for record in (self.local, self.remote):
            fields = record["fields"]
            if fields:
                return fields.get("name", fields.get("title", "记录"))
        return "删除记录"


def merge(base, local, remote, choices=None):
    """A whole task includes its calendar membership and completion history."""
    validate(base)
    validate(local)
    validate(remote)
    # Missing previously shared records indicate replacement/loss, not a deletion.
    if set(base) - set(remote) or set(base) - set(local):
        raise SyncError("同步文件缺少已共享的记录，请恢复文件；删除应通过软件操作。")
    merged, conflicts = {}, []
    for uid in sorted(set(local) | set(remote)):
        before, ours, theirs = base.get(uid), local.get(uid), remote.get(uid)
        if ours is not None and theirs is not None and ours["kind"] != theirs["kind"]:
            raise SyncError("同一记录的类型发生变化，请检查同步文件。")
        if ours == theirs or theirs == before:
            result = ours
        elif ours == before:
            result = theirs
        elif choices and uid in choices:
            if choices[uid] not in ("local", "remote"):
                raise SyncError("请选择本地或远端版本。")
            result = ours if choices[uid] == "local" else theirs
        else:
            conflicts.append(Conflict(uid, before, ours, theirs))
            continue
        merged[uid] = deepcopy(result)
    if not conflicts:
        _normalize_deletions(merged)
        validate(merged)
    return merged, conflicts


def _normalize_deletions(records):
    """Match SQLite FK semantics when a parent is deleted on another device."""
    def deleted(uid):
        return uid is not None and uid in records and records[uid]["fields"] is None

    # Company is an application parameter, matching the compact job page.
    # One local company row must represent all case-insensitive equivalents.
    companies = {}
    for record in records.values():
        if record["kind"] == "job_applications" and record["fields"]:
            name = record["fields"]["company"]
            key = name.casefold()
            companies[key] = min(name, companies.get(key, name))
    for record in records.values():
        if record["kind"] == "job_applications" and record["fields"]:
            name = record["fields"]["company"]
            record["fields"]["company"] = companies[name.casefold()]

    for record in records.values():
        fields = record["fields"]
        if fields is None:
            continue
        if record["kind"] == "milestones" and deleted(fields["project_id"]):
            record["fields"] = None
    for record in records.values():
        fields = record["fields"]
        if fields is None:
            continue
        if record["kind"] == "tasks":
            for key in ("project_id", "milestone_id"):
                if deleted(fields[key]):
                    fields[key] = None
            for event in fields["completions"]:
                if deleted(event["project_id"]):
                    event["project_id"] = None
    for uid, record in records.items():
        fields = record["fields"]
        if record["kind"] == "milestones" and fields and fields["completed_at"]:
            tasks = [r["fields"] for r in records.values() if r["kind"] == "tasks" and r["fields"] and r["fields"]["milestone_id"] == uid]
            if not tasks or any(t["status"] != "已完成" for t in tasks):
                fields["completed_at"] = None
