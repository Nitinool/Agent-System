"""Application stage times: actual input, progress, migration and shared history."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from activitylog.job_store import JOB_V9_SCHEMA
from activitylog.jobs import ApplicationDraft, STAGE_TIMES, stage_time
from activitylog.models import Activity
from activitylog.service import ActivityService
from activitylog.storage import Store, SCHEMA_VERSION
from activitylog.sync import REPOSITORY, SyncError, decode, encode, merge, upgrade_records
from tests.ui_smoke import FixtureReader


class JobTimeTests(unittest.TestCase):
    def setUp(self):
        self.app = ActivityService(Store(':memory:'), FixtureReader())
        self.addCleanup(self.app.close)
        self.draft = ApplicationDraft('开发工程师', '2026-10-16', notes='保留备注')

    def current(self, identifier):
        return self.app.jobs.repository.get_application(identifier)

    def test_date_minute_and_second_precision_are_normalized_without_inventing_time(self):
        for raw, expected in (('2026-10-17', '2026-10-17'), (' 2026-10-17T09:30 ', '2026-10-17 09:30'),
                              ('2026-10-17 09:30:45', '2026-10-17 09:30:45'),
                              ('2026-10-17 09:30:00', '2026-10-17 09:30'), (' ', '')):
            with self.subTest(raw=raw):
                self.assertEqual(stage_time(raw), expected)

    def test_all_three_times_derive_progress_and_keep_the_other_fields(self):
        identifier = self.app.jobs.save_application('测试公司', replace(self.draft, written_at='2026-10-17 09:30'))
        self.assertEqual(self.current(identifier).status, '笔试中')
        self.app.jobs.update_application(identifier, replace(self.draft, interview_at='2026-10-18', written_at='2026-10-17 09:30'))
        self.assertEqual(self.current(identifier).status, '面试中')
        final = replace(self.draft, interview_at='2026-10-18', written_at='2026-10-17 09:30', rejected_at='2026-10-19')
        self.app.jobs.save_application('测试公司', final, identifier)
        record = self.current(identifier)
        self.assertEqual(record.status, '已拒绝')
        self.assertEqual(tuple(getattr(record, key) for key in STAGE_TIMES), ('2026-10-18', '2026-10-17 09:30', '2026-10-19'))
        self.assertEqual(record.notes, '保留备注')
        self.assertEqual(self.app.jobs.snapshot().summary.applications, 1)

    def test_clearing_time_falls_back_without_changing_legacy_manual_status(self):
        identifier = self.app.jobs.save_application('测试公司', replace(self.draft, rejected_at='2026-10-19'))
        for draft, expected in ((replace(self.draft, status='已拒绝', interview_at='2026-10-18'), '面试中'),
                                (replace(self.draft, status='面试中', written_at='2026-10-17'), '笔试中'),
                                (replace(self.draft, status='笔试中'), '已投递')):
            self.app.jobs.update_application(identifier, draft)
            self.assertEqual(self.current(identifier).status, expected)
        self.app.jobs.update_application(identifier, replace(self.draft, status='面试中'))
        self.app.jobs.update_application(identifier, replace(self.draft, status='面试中', notes='旧记录没有准确时间'))
        self.assertEqual(self.current(identifier).status, '面试中')
        self.assertEqual(self.current(identifier).interview_at, '')

    def test_offer_withdrawn_and_manual_rejection_never_get_fake_dates(self):
        for status in ('已获 Offer', '已撤回', '已拒绝'):
            identifier = self.app.jobs.save_application('测试公司', replace(self.draft, status=status))
            record = self.current(identifier)
            self.assertEqual(record.status, status)
            self.assertTrue(all(getattr(record, key) == '' for key in STAGE_TIMES))
        for status in ('已获 Offer', '已撤回'):
            identifier = self.app.jobs.save_application('测试公司', replace(self.draft, status=status, interview_at='2026-10-18'))
            self.assertEqual(self.current(identifier).status, status)
            self.app.jobs.update_application(identifier, replace(self.draft, status=status, rejected_at='2026-10-19'))
            self.assertEqual(self.current(identifier).status, '已拒绝')

    def test_invalid_times_leave_no_company_or_partial_application(self):
        for key in STAGE_TIMES:
            for value in ('2026-02-30', '2026-10-17 25:00', '2026-1-2', '2026-10-17T12:00+08:00', None):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.app.jobs.save_application('不应创建', replace(self.draft, **{key: value}))
        self.assertEqual(self.app.jobs.history().companies, ())
        company = self.app.jobs.add_company('已有公司')
        identifier = self.app.jobs.add_application(company, replace(self.draft, written_at='2026-10-17'))
        self.assertEqual(self.current(identifier).status, '笔试中')
        with self.assertRaises(ValueError):
            self.app.jobs.update_application(identifier, replace(self.draft, written_at='错误时间'))
        self.assertEqual(self.current(identifier).written_at, '2026-10-17')

    def test_job_times_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'persist.sqlite3'
            with Store(path) as store:
                service = ActivityService(store, FixtureReader())
                identifier = service.jobs.save_application('测试公司', replace(self.draft, interview_at='2026-10-18 14:00'))
            with Store(path) as store:
                service = ActivityService(store, FixtureReader())
                record = service.jobs.repository.get_application(identifier)
                self.assertEqual((record.status, record.interview_at, record.notes), ('面试中', '2026-10-18 14:00', '保留备注'))

    def test_all_old_wire_formats_upgrade_without_phantom_changes(self):
        self.app.jobs.save_application('旧记录', replace(self.draft, status='面试中'))
        current = self.app.sync.snapshot()
        old = deepcopy(current)
        for record in old.values():
            for key in STAGE_TIMES:
                del record['fields'][key]
        for version in (1, 2, 3, 4):
            wire = json.dumps({'format': 'agent-system-data', 'version': version, 'records': old})
            upgraded = decode(wire)
            self.assertEqual(upgraded, current)
            combined, conflicts = merge(old, current, upgraded)
            self.assertFalse(conflicts)
            self.assertEqual(combined, current)
        self.assertEqual(self.app.jobs.snapshot().groups[0].applications[0].status, '面试中')

    def test_new_wire_requires_times_and_rejects_inconsistent_progress(self):
        self.app.jobs.save_application('测试公司', replace(self.draft, interview_at='2026-10-18 14:00'))
        original = json.loads(encode(self.app.sync.snapshot()))
        self.assertEqual(original['version'], 5)
        for kind in ('missing', 'wrong-status', 'bad-date', 'old-version'):
            payload = deepcopy(original)
            fields = next(iter(payload['records'].values()))['fields']
            if kind == 'missing':
                del fields['written_at']
            elif kind == 'wrong-status':
                fields['status'] = '已投递'
            elif kind == 'bad-date':
                fields['interview_at'] = '2026-02-30'
            else:
                payload['version'] = 4
            with self.subTest(kind=kind), self.assertRaises(SyncError):
                decode(json.dumps(payload))

    def test_two_devices_share_progress_times_conflict_choice_and_deletion(self):
        peer = ActivityService(Store(':memory:'), FixtureReader())
        self.addCleanup(peer.close)
        identifier = self.app.jobs.save_application('测试公司', replace(self.draft, written_at='2026-10-17'))
        remote = decode(encode(self.app.sync.snapshot()))
        self.app.sync.apply(self.app.sync.snapshot(), remote)
        peer.sync.apply(peer.sync.snapshot(), remote)
        other = peer.jobs.snapshot().groups[0].applications[0]
        self.assertEqual((other.status, other.written_at), ('笔试中', '2026-10-17'))
        self.app.jobs.update_application(identifier, replace(self.draft, interview_at='2026-10-18 14:00'))
        peer.jobs.update_application(other.id, replace(self.draft, rejected_at='2026-10-19'))
        local, distant = self.app.sync.snapshot(), peer.sync.snapshot()
        _, conflicts = merge(remote, local, distant)
        self.assertEqual(len(conflicts), 1)
        combined, conflicts = merge(remote, local, distant, {conflicts[0].uid: 'remote'})
        self.assertFalse(conflicts)
        self.app.sync.apply(local, combined)
        peer.sync.apply(distant, combined)
        self.assertEqual(self.current(identifier).rejected_at, '2026-10-19')
        self.assertEqual(self.current(identifier).status, '已拒绝')
        peer.jobs.delete_application(other.id)
        deleted, conflicts = merge(combined, self.app.sync.snapshot(), peer.sync.snapshot())
        self.assertFalse(conflicts)
        self.app.sync.apply(self.app.sync.snapshot(), deleted)
        self.assertEqual(self.app.jobs.snapshot().summary.applications, 0)


class JobTimeMigrationTests(unittest.TestCase):
    def fixture(self, path):
        with Store(path) as store:
            service = ActivityService(store, FixtureReader())
            service.jobs.save_application('旧公司', ApplicationDraft('旧岗位', '2026-10-16', '面试中', notes='已有内容'))
            at = datetime(2026, 10, 16, 12).astimezone()
            identifier = store.begin(Activity('fixture.exe', '保留行为日志'), at)
            store.finish(identifier, at, 12)
            old = service.sync.snapshot()
            for record in old.values():
                for key in STAGE_TIMES:
                    del record['fields'][key]
            with store.db:
                store.db.execute('INSERT INTO sync_state VALUES(?,?,?)', (REPOSITORY, json.dumps(old), at.isoformat()))
                for key in STAGE_TIMES:
                    store.db.execute(f'ALTER TABLE job_applications DROP COLUMN {key}')
                store.db.execute('PRAGMA user_version=8')
            return old

    def test_upgrade_preserves_old_status_fields_logs_and_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'v8.sqlite3'
            old = self.fixture(path)
            with Store(path) as store:
                service = ActivityService(store, FixtureReader())
                record = service.jobs.snapshot().groups[0].applications[0]
                self.assertEqual((record.status, record.notes), ('面试中', '已有内容'))
                self.assertTrue(all(getattr(record, key) == '' for key in STAGE_TIMES))
                self.assertEqual(service.sync.snapshot(), upgrade_records(old))
                self.assertEqual(service.sync.status()[0], 0)
                self.assertEqual(store.rows()[0].title, '保留行为日志')
                self.assertEqual(store.db.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)

    def test_failed_upgrade_rolls_back_columns_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'v8.sqlite3'
            self.fixture(path)
            with patch('activitylog.storage.JOB_V9_SCHEMA', JOB_V9_SCHEMA[:2] + ('INVALID SQL',)):
                with self.assertRaises(sqlite3.Error):
                    Store(path)
            db = sqlite3.connect(path)
            try:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 8)
                self.assertTrue(set(STAGE_TIMES).isdisjoint({r[1] for r in db.execute('PRAGMA table_info(job_applications)')}))
                self.assertEqual(db.execute('SELECT status FROM job_applications').fetchone()[0], '面试中')
            finally:
                db.close()


if __name__ == '__main__':
    unittest.main()
