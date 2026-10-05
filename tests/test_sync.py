"""Two-device integration tests with isolated SQLite stores and a fake transport."""

import base64
from copy import deepcopy
from datetime import date
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from activitylog.github_sync import GitHubSync
from activitylog.jobs import ApplicationDraft
from activitylog.models import Activity
from activitylog.projects import MilestoneDraft, ProjectDraft
from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.sync import LocalChanged, RemoteChanged, SyncError, decode, encode, merge
from activitylog.sync_credentials import TokenStore
from tests.ui_smoke import FixtureReader
from activitylog.tasks import TaskDraft


class Devices(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.a = self.device("a")
        self.b = self.device("b")
        self.remote = {}

    def device(self, name):
        path = Path(self.directory.name) / f"{name}.sqlite3"
        service = ActivityService(Store(path), FixtureReader())
        self.addCleanup(service.close)
        return service

    def sync(self, device, choices=None):
        local, base = device.sync.snapshot(), device.sync.baseline()
        merged, conflicts = merge(base, local, self.remote, choices)
        self.assertFalse(conflicts)
        # Serialization is part of the real desktop wire protocol.
        self.remote = decode(encode(merged))
        device.sync.apply(local, self.remote)

    def shared_task(self):
        identifier = self.a.tasks.save(TaskDraft("开发任务", "", notes="初始备注"))
        self.sync(self.a)
        self.sync(self.b)
        return identifier, self.b.tasks.repository.unscheduled()[0].id

    def test_two_devices_preserve_links_progress_days_and_real_history(self):
        project = self.a.projects.save(ProjectDraft("开发 Demo", "可核对的成果"))
        stage = self.a.projects.save_milestone(project, MilestoneDraft("首版", "功能可用"))
        task = self.a.tasks.save(TaskDraft("实现功能", "2026-10-05", project_id=project, milestone_id=stage), in_today=True)
        self.a.tasks.complete(task, True)
        self.a.projects.finish_milestone(stage)
        self.a.jobs.save_application("测试公司", ApplicationDraft("开发", "2026-10-05"))
        self.sync(self.a)
        self.sync(self.b)
        self.assertEqual(self.a.sync.snapshot(), self.b.sync.snapshot())
        self.assertTrue(self.b.projects.milestones(self.b.projects.summaries()[0].project.id)[0].completed_at)
        other = self.b.tasks.get(self.b.store.db.execute("SELECT id FROM tasks").fetchone()[0])
        self.assertTrue(self.b.tasks.is_in_today(other.id))
        self.assertEqual(other.completed_at, self.a.tasks.get(task).completed_at)
        self.b.tasks.complete(other.id, False)
        self.sync(self.b)
        self.sync(self.a)
        self.assertEqual(self.a.tasks.get(task).status, "待开始")
        self.assertIsNone(self.a.projects.milestones(project)[0].completed_at)
        self.assertTrue(self.a.projects.completion_records(project)[0].reopened_at)
        events = self.a.store.db.execute("SELECT COUNT(*) FROM task_completions").fetchone()[0]
        self.sync(self.a)
        self.assertEqual(events, self.a.store.db.execute("SELECT COUNT(*) FROM task_completions").fetchone()[0])
        self.assertEqual(self.a.sync.status()[0], 0)

    def test_colliding_local_ids_remain_distinct_and_repeated_sync_is_idempotent(self):
        self.a.tasks.save(TaskDraft("A", ""))
        self.b.tasks.save(TaskDraft("B", ""))
        self.sync(self.a)
        self.sync(self.b)
        self.sync(self.a)
        self.assertEqual({t.title for t in self.a.tasks.repository.unscheduled()}, {"A", "B"})
        before = self.a.sync.snapshot()
        self.sync(self.a)
        self.assertEqual(before, self.a.sync.snapshot())

    def test_delete_and_reused_sqlite_id_do_not_resurrect_old_record(self):
        old_a, old_b = self.shared_task()
        uid = next(iter(self.remote))
        self.a.tasks.delete(old_a)
        new = self.a.tasks.save(TaskDraft("新任务", ""))
        self.assertEqual(old_a, new)
        self.sync(self.a)
        self.sync(self.b)
        self.assertIsNone(self.remote[uid]["fields"])
        self.assertEqual([t.title for t in self.b.tasks.repository.unscheduled()], ["新任务"])
        self.b.tasks.delete(self.b.tasks.repository.unscheduled()[0].id)
        self.sync(self.b)
        self.sync(self.a)
        self.assertFalse(self.a.tasks.repository.unscheduled())

    def test_same_record_edits_require_explicit_choice(self):
        a, b = self.shared_task()
        self.a.tasks.save(TaskDraft("开发任务", "", notes="A 修改"), a)
        self.b.tasks.save(TaskDraft("开发任务", "", notes="B 修改"), b)
        self.sync(self.a)
        local = self.b.sync.snapshot()
        _, conflicts = merge(self.b.sync.baseline(), local, self.remote)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(self.b.sync.snapshot(), local)
        self.sync(self.b, {conflicts[0].uid: "local"})
        self.sync(self.a)
        self.assertEqual(self.a.tasks.get(a).notes, "B 修改")

    def test_modify_delete_conflict_can_restore_or_keep_deletion(self):
        a, b = self.shared_task()
        self.a.tasks.delete(a)
        self.b.tasks.save(TaskDraft("保留的修改", ""), b)
        self.sync(self.a)
        _, conflicts = merge(self.b.sync.baseline(), self.b.sync.snapshot(), self.remote)
        self.assertIsNone(conflicts[0].remote["fields"])
        self.sync(self.b, {conflicts[0].uid: "local"})
        self.sync(self.a)
        self.assertEqual([t.title for t in self.a.tasks.repository.unscheduled()], ["保留的修改"])
        self.a.tasks.delete(self.a.tasks.repository.unscheduled()[0].id)
        self.b.tasks.save(TaskDraft("再次修改", ""), b)
        self.sync(self.a)
        _, conflicts = merge(self.b.sync.baseline(), self.b.sync.snapshot(), self.remote)
        self.sync(self.b, {conflicts[0].uid: "remote"})
        self.assertFalse(self.b.tasks.repository.unscheduled())

    def test_parent_deletion_keeps_concurrent_new_task_without_dangling_links(self):
        p = self.a.projects.save(ProjectDraft("项目"))
        m = self.a.projects.save_milestone(p, MilestoneDraft("阶段"))
        self.sync(self.a)
        self.sync(self.b)
        bp = self.b.projects.summaries()[0].project.id
        bm = self.b.projects.milestones(bp)[0].id
        self.a.projects.delete(p)
        self.b.tasks.save(TaskDraft("另一台新增", "", project_id=bp, milestone_id=bm))
        self.sync(self.a)
        self.sync(self.b)
        task = self.b.tasks.repository.unscheduled()[0]
        self.assertIsNone(task.project_id)
        self.assertIsNone(task.milestone_id)
        self.sync(self.a)
        self.assertEqual([t.title for t in self.a.tasks.repository.unscheduled()], ["另一台新增"])

    def test_independent_additions_invalidate_previously_accepted_stage(self):
        p = self.a.projects.save(ProjectDraft("项目"))
        m = self.a.projects.save_milestone(p, MilestoneDraft("阶段"))
        t = self.a.tasks.save(TaskDraft("第一项", "", project_id=p, milestone_id=m))
        self.a.tasks.complete(t, True)
        self.sync(self.a)
        self.sync(self.b)
        self.a.projects.finish_milestone(m)
        bp = self.b.projects.summaries()[0].project.id
        bm = self.b.projects.milestones(bp)[0].id
        self.b.tasks.save(TaskDraft("补充项", "", project_id=bp, milestone_id=bm))
        self.sync(self.a)
        self.sync(self.b)
        self.assertIsNone(self.b.projects.milestones(bp)[0].completed_at)

    def test_company_name_is_parameter_and_same_name_is_reused(self):
        self.a.jobs.save_application("ACME", ApplicationDraft("后端", "2026-10-05"))
        self.b.jobs.save_application("acme", ApplicationDraft("前端", "2026-10-05"))
        self.sync(self.a)
        self.sync(self.b)
        self.sync(self.a)
        for device in (self.a, self.b):
            self.assertEqual(device.store.db.execute("SELECT COUNT(*) FROM job_companies").fetchone()[0], 1)
            self.assertEqual(device.store.db.execute("SELECT COUNT(*) FROM job_applications").fetchone()[0], 2)

    def test_duplicate_project_names_stop_merge_without_mutation(self):
        self.a.projects.save(ProjectDraft("同名项目"))
        self.b.projects.save(ProjectDraft("同名项目"))
        self.sync(self.a)
        before = self.b.sync.snapshot()
        with self.assertRaisesRegex(SyncError, "同名项目"):
            merge({}, before, self.remote)
        self.assertEqual(self.b.sync.snapshot(), before)

    def test_edit_during_upload_retains_local_changes_and_old_base(self):
        a, b = self.shared_task()
        expected = self.b.sync.snapshot()
        self.a.tasks.save(TaskDraft("远端编辑", ""), a)
        self.sync(self.a)
        merged, conflicts = merge(self.b.sync.baseline(), expected, self.remote)
        self.assertFalse(conflicts)
        base = self.b.sync.baseline()
        self.b.tasks.save(TaskDraft("上传期间编辑", ""), b)
        with self.assertRaises(LocalChanged):
            self.b.sync.apply(expected, merged)
        self.assertEqual(self.b.tasks.get(b).title, "上传期间编辑")
        self.assertEqual(self.b.sync.baseline(), base)

    def test_missing_remote_records_and_unknown_wire_version_are_rejected(self):
        self.shared_task()
        with self.assertRaisesRegex(SyncError, "缺少"):
            merge(self.a.sync.baseline(), self.a.sync.snapshot(), {})
        payload = json.loads(encode(self.remote))
        payload["version"] = 99
        with self.assertRaises(SyncError):
            decode(json.dumps(payload))
        with self.assertRaises(SyncError):
            decode('{"format":"agent-system-data","version":1,"records":{},"records":{}}')

    def test_day_membership_change_is_shared_and_delete_cascades_everywhere(self):
        a, b = self.shared_task()
        self.a.tasks.arrange_today(a)
        self.sync(self.a)
        self.sync(self.b)
        self.assertTrue(self.b.tasks.is_in_today(b))
        self.b.tasks.remove_today(b)
        self.sync(self.b)
        self.sync(self.a)
        self.assertFalse(self.a.tasks.is_in_today(a))
        self.a.tasks.complete(a, True)
        self.sync(self.a)
        self.sync(self.b)
        self.b.tasks.delete(b)
        self.sync(self.b)
        self.sync(self.a)
        self.assertEqual(self.a.store.db.execute('SELECT COUNT(*) FROM task_completions').fetchone()[0], 0)

    def test_project_name_swap_and_reopened_history_order_survive_import(self):
        p = self.a.projects.save(ProjectDraft("甲"))
        q = self.a.projects.save(ProjectDraft("乙"))
        t = self.a.tasks.save(TaskDraft("反复验收", "", project_id=p))
        self.a.tasks.complete(t, True)
        self.a.tasks.complete(t, False)
        self.a.tasks.complete(t, True)
        self.sync(self.a)
        self.sync(self.b)
        self.a.projects.save(ProjectDraft("临时名"), p)
        self.a.projects.save(ProjectDraft("甲"), q)
        self.a.projects.save(ProjectDraft("乙"), p)
        self.sync(self.a)
        self.sync(self.b)
        self.assertEqual(self.a.sync.snapshot(), self.b.sync.snapshot())
        self.assertEqual(self.b.store.db.execute('SELECT COUNT(*) FROM task_completions').fetchone()[0], 2)

    def test_invalid_references_and_rollback_leave_base_and_rows_intact(self):
        a, b = self.shared_task()
        before = self.b.sync.snapshot()
        invalid = deepcopy(before)
        next(iter(invalid.values()))["fields"]["project_id"] = "0" * 32
        with self.assertRaises(SyncError):
            self.b.sync.apply(before, invalid)
        modified = deepcopy(before)
        next(iter(modified.values()))["fields"]["title"] = "新标题"
        original_import = self.b.sync._import

        def fail(expected, merged):
            original_import(expected, merged)
            raise sqlite3.OperationalError("模拟写入失败")
        with patch.object(self.b.sync, "_import", side_effect=fail):
            with self.assertRaises(sqlite3.Error):
                self.b.sync.apply(before, modified)
        self.assertEqual(self.b.sync.snapshot(), before)
        self.assertEqual(self.b.sync.baseline(), before)

    def test_behavior_logs_never_enter_payload_and_identity_survives_restart(self):
        from datetime import datetime
        now = datetime.now().astimezone()
        row = self.a.store.begin(Activity("chrome.exe", "私密页面标题", 1), now)
        self.a.store.finish(row, now, 2)
        self.a.tasks.save(TaskDraft("共享事项", ""))
        content = encode(self.a.sync.snapshot())
        self.assertNotIn("私密页面标题", content)
        self.assertNotIn("segments", content)
        second = self.device("a")
        self.assertEqual(self.a.sync.snapshot(), second.sync.snapshot())


class Response(io.BytesIO):
    def __init__(self, value):
        super().__init__(json.dumps(value).encode())


class FakeOpener:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def open(self, request, timeout):
        self.requests.append(request)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return Response(value)


class TransportTests(unittest.TestCase):
    def test_private_repo_sha_and_expected_branch_are_used_for_cas(self):
        content = encode({})
        opener = FakeOpener({"private": True, "default_branch": "main"},
            {"type": "file", "encoding": "base64", "size": len(content), "sha": "a" * 40,
             "content": base64.b64encode(content.encode()).decode()},
            {"private": True, "default_branch": "main"}, {"commit": {}})
        transport = GitHubSync("test-only-token", opener=opener)
        records, sha = transport.fetch()
        transport.publish(records, sha)
        payload = json.loads(opener.requests[-1].data)
        self.assertEqual(payload["sha"], "a" * 40)
        self.assertEqual(payload["branch"], "main")
        self.assertNotIn("test-only-token", opener.requests[-1].data.decode())

    def test_public_repo_is_rejected_before_read_or_write(self):
        for operation in ("fetch", "publish"):
            opener = FakeOpener({"private": False, "default_branch": "main"})
            transport = GitHubSync("test-only-token", opener=opener)
            with self.assertRaisesRegex(SyncError, "私有"):
                transport.fetch() if operation == "fetch" else transport.publish({}, None)
            self.assertEqual(len(opener.requests), 1)

    def test_empty_repo_is_allowed_but_inaccessible_repo_is_not(self):
        missing = HTTPError("https://api.github.com", 404, "missing", {}, None)
        transport = GitHubSync("test-only-token", opener=FakeOpener({"private": True, "default_branch": "main"}, missing))
        self.assertEqual(transport.fetch(), ({}, None))
        with self.assertRaises(SyncError):
            GitHubSync("test-only-token", opener=FakeOpener(missing)).fetch()

    def test_remote_cas_race_and_timeout_are_safe_and_credentials_not_echoed(self):
        error = HTTPError("https://api.github.com", 409, "test-only-token", {}, None)
        transport = GitHubSync("test-only-token", opener=FakeOpener({"private": True, "default_branch": "main"}, error))
        with self.assertRaises(RemoteChanged) as context:
            transport.publish({}, "a" * 40)
        self.assertNotIn("test-only-token", str(context.exception))
        transport = GitHubSync("test-only-token", opener=FakeOpener(URLError("test-only-token")))
        with self.assertRaises(SyncError) as context:
            transport.fetch()
        self.assertNotIn("test-only-token", str(context.exception))

    def test_dpapi_round_trip_and_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            tokens = TokenStore(directory)
            tokens.save("test-only-token")
            self.assertNotIn(b"test-only-token", tokens.path.read_bytes())
            self.assertEqual(tokens.load(), "test-only-token")
            tokens.clear()
            self.assertEqual(tokens.load(), "")


if __name__ == "__main__":
    unittest.main()
