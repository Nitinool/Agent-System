"""Company/application workflows and the additive schema upgrade."""

from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from activitylog.job_service import JobService
from activitylog.job_store import JOB_SCHEMA, JobRepository
from activitylog.jobs import ApplicationDraft, application_rows, filter_companies
from activitylog.models import Activity
from activitylog.storage import RECORDING_SCHEMA, SCHEMA_VERSION, Store


class JobTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "jobs.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        self.jobs = JobService(JobRepository(self.store.db))
        self.draft = ApplicationDraft("Python 开发", "2026-10-04", url="https://example.com/jobs/1", notes="已发送简历")

    def test_multiple_positions_count_as_one_applied_company(self):
        first = self.jobs.add_company("甲公司")
        second = self.jobs.add_company("乙公司")
        self.jobs.add_company("待投公司")
        self.jobs.add_application(first, self.draft)
        self.jobs.add_application(first, replace(self.draft, title="后端开发", status="面试中"))
        self.jobs.add_application(second, replace(self.draft, status="已获 Offer"))
        summary = self.jobs.snapshot().summary
        self.assertEqual(summary.applied_companies, 2)
        self.assertEqual(summary.applications, 3)
        self.assertEqual(summary.pending_companies, 1)
        self.assertEqual(summary.interviews, 1)
        self.assertEqual(summary.offers, 1)

    def test_empty_company_is_not_counted_as_applied(self):
        company = self.jobs.add_company("准备投递")
        summary = self.jobs.snapshot().summary
        self.assertEqual(summary.applied_companies, 0)
        self.assertEqual(summary.pending_companies, 1)
        application = self.jobs.add_application(company, self.draft)
        self.assertEqual(self.jobs.snapshot().summary.applied_companies, 1)
        self.jobs.delete_application(application)
        self.assertEqual(self.jobs.snapshot().summary.applied_companies, 0)
        self.assertEqual(len(self.jobs.snapshot().groups), 1)

    def test_edit_and_restart_preserve_unicode_dates_status_link_and_notes(self):
        company = self.jobs.add_company("甲公司")
        identifier = self.jobs.add_application(company, self.draft)
        edited = replace(self.draft, title="C++ / Python 工程师", applied_on="2026-10-03", status="已获 Offer",
                         notes="一面通过\n期望工作地点：上海")
        self.jobs.update_application(identifier, edited)
        self.jobs.rename_company(company, "甲公司 · 研发中心")
        self.store.close()
        with Store(self.path) as reopened:
            snapshot = JobService(JobRepository(reopened.db)).snapshot()
            application = snapshot.groups[0].applications[0]
            self.assertEqual(snapshot.groups[0].company.name, "甲公司 · 研发中心")
            self.assertEqual(application.id, identifier)
            self.assertEqual(application.applied_on, date(2026, 10, 3))
            self.assertEqual(application.title, edited.title)
            self.assertEqual(application.notes, edited.notes)
            self.assertEqual(application.url, edited.url)
            self.assertEqual(snapshot.summary.offers, 1)

    def test_duplicate_company_names_are_rejected_and_rename_rolls_back(self):
        self.jobs.add_company(" Example Inc ")
        with self.assertRaises(ValueError):
            self.jobs.add_company("example INC")
        another = self.jobs.add_company("Other")
        with self.assertRaises(ValueError):
            self.jobs.rename_company(another, "EXAMPLE INC")
        self.assertEqual({group.company.name for group in self.jobs.snapshot().groups}, {"Example Inc", "Other"})

    def test_required_fields_dates_statuses_and_links_are_validated(self):
        with self.assertRaises(ValueError):
            self.jobs.add_company("  ")
        company = self.jobs.add_company("甲公司")
        for draft in (replace(self.draft, title="  "), replace(self.draft, applied_on="2026-02-30"),
                      replace(self.draft, status="未知状态"), replace(self.draft, url="file:///C:/test"),
                      replace(self.draft, url="javascript:alert(1)"), replace(self.draft, url="https://example.com/invalid path")):
            with self.subTest(draft=draft), self.assertRaises(ValueError):
                self.jobs.add_application(company, draft)
        self.assertEqual(self.jobs.snapshot().summary.applications, 0)

    def test_company_and_position_search_combine_with_status_without_changing_totals(self):
        company = self.jobs.add_company("Example")
        self.jobs.add_application(company, self.draft)
        self.jobs.add_application(company, replace(self.draft, title="C 开发", status="面试中", notes="准备复习算法"))
        self.jobs.add_company("待投")
        snapshot = self.jobs.snapshot()
        self.assertEqual(len(filter_companies(snapshot, "EXAMPLE")[0].applications), 2)
        self.assertEqual(len(filter_companies(snapshot, "python")[0].applications), 1)
        selected = filter_companies(snapshot, "算法", "面试中")
        self.assertEqual(selected[0].applications[0].title, "C 开发")
        self.assertEqual(filter_companies(snapshot, "python", "已拒绝"), [])
        self.assertEqual(len(filter_companies(snapshot, "待投")), 1)
        self.assertEqual(snapshot.summary.applications, 2)

    def test_company_delete_cascades_only_its_positions_and_preserves_activity(self):
        at = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
        activity = self.store.begin(Activity("test.exe", "记录信息"), at)
        self.store.finish(activity, at, 0)
        company = self.jobs.add_company("甲公司")
        other = self.jobs.add_company("乙公司")
        self.jobs.add_application(company, self.draft)
        self.jobs.add_application(company, self.draft)
        self.jobs.add_application(other, self.draft)
        self.jobs.delete_company(company)
        self.assertEqual(self.jobs.snapshot().summary.applications, 1)
        self.assertEqual(len(self.store.rows()), 1)
        self.assertEqual(self.store.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_missing_company_does_not_create_orphan_application(self):
        company = self.jobs.add_company("甲公司")
        self.jobs.delete_company(company)
        with self.assertRaises(ValueError):
            self.jobs.add_application(company, self.draft)
        self.assertEqual(self.jobs.snapshot().summary.applications, 0)

    def test_edit_validation_preserves_saved_record(self):
        company = self.jobs.add_company("甲公司")
        identifier = self.jobs.add_application(company, self.draft)
        original = self.jobs.snapshot()
        with self.assertRaises(ValueError):
            self.jobs.update_application(identifier, replace(self.draft, applied_on="无效日期"))
        self.assertEqual(self.jobs.snapshot(), original)

    def test_direct_entry_reuses_company_and_provides_unique_name_history(self):
        self.jobs.save_application("Example", self.draft)
        self.jobs.save_application(" example ", self.draft)
        self.jobs.save_application("另一家公司", replace(self.draft, title="后端开发"))
        snapshot = self.jobs.snapshot()
        self.assertEqual(snapshot.summary.applied_companies, 2)
        self.assertEqual(snapshot.summary.applications, 3)
        self.assertEqual(set(self.jobs.history().companies), {"Example", "另一家公司"})
        self.assertEqual(self.jobs.history().titles, ("后端开发", "Python 开发"))
        self.store.close()
        with Store(self.path) as reopened:
            history = JobService(JobRepository(reopened.db)).history()
            self.assertEqual(set(history.companies), {"Example", "另一家公司"})
            self.assertEqual(history.titles, ("后端开发", "Python 开发"))

    def test_invalid_direct_entry_does_not_create_company(self):
        with self.assertRaises(ValueError):
            self.jobs.save_application("新公司", replace(self.draft, applied_on="错误日期"))
        self.assertEqual(self.jobs.snapshot().groups, ())

    def test_direct_entry_is_atomic_when_application_insert_fails(self):
        self.store.db.execute("""CREATE TRIGGER reject_application BEFORE INSERT ON job_applications
            BEGIN SELECT RAISE(ABORT, 'write failed'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.jobs.save_application("新公司", self.draft)
        self.assertEqual(self.jobs.history().companies, ())
        self.assertEqual(self.jobs.snapshot().summary.applications, 0)

    def test_edit_can_change_company_without_changing_other_applications(self):
        first = self.jobs.save_application("甲公司", self.draft)
        second = self.jobs.save_application("甲公司", replace(self.draft, title="后端开发"))
        self.jobs.save_application("乙公司", self.draft)
        self.jobs.save_application("乙公司", replace(self.draft, status="面试中"), first)
        rows = application_rows(self.jobs.snapshot())
        by_id = {row.application.id: row for row in rows}
        self.assertEqual(by_id[first].company.name, "乙公司")
        self.assertEqual(by_id[first].application.status, "面试中")
        self.assertEqual(by_id[second].company.name, "甲公司")
        self.assertEqual(self.jobs.snapshot().summary.applications, 3)

    def test_edit_missing_application_does_not_create_company(self):
        with self.assertRaises(ValueError):
            self.jobs.save_application("不能创建的公司", self.draft, 999)
        self.assertEqual(self.jobs.history().companies, ())

    def test_flat_rows_are_sorted_by_date_across_companies_and_can_be_filtered(self):
        newer = self.jobs.save_application("甲公司", self.draft)
        older = self.jobs.save_application("乙公司", replace(self.draft, applied_on="2026-10-01", status="面试中"))
        latest = self.jobs.save_application("乙公司", replace(self.draft, applied_on="2026-10-05"))
        rows = application_rows(self.jobs.snapshot())
        self.assertEqual([row.application.id for row in rows], [latest, newer, older])
        selected = application_rows(self.jobs.snapshot(), "乙公司", "面试中")
        self.assertEqual([row.application.id for row in selected], [older])


class JobSchemaTests(unittest.TestCase):
    def version_one(self, path):
        connection = sqlite3.connect(path)
        for statement in RECORDING_SCHEMA:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=1")
        connection.execute("""INSERT INTO segments(start_time, last_seen, app, process, title, kind, status, seconds)
            VALUES ('2026-10-04T12:00:00+08:00', '2026-10-04T12:01:00+08:00', 'Chrome', 'chrome.exe', '原有活动',
                    'activity', 'closed', 60)""")
        connection.execute("INSERT INTO classifications VALUES (1, '学习')")
        original = connection.execute("SELECT * FROM segments").fetchall()
        connection.commit()
        connection.close()
        return original

    def test_feature_upgrade_preserves_existing_activity_and_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.sqlite3"
            original = self.version_one(path)
            with Store(path) as store:
                self.assertEqual([tuple(row) for row in store.db.execute("SELECT * FROM segments")], original)
                self.assertEqual(store.rows()[0].category, "学习")
                self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                self.assertEqual(JobService(JobRepository(store.db)).snapshot().groups, ())

    def test_feature_upgrade_rolls_back_if_table_creation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.sqlite3"
            original = self.version_one(path)
            with patch("activitylog.storage.JOB_SCHEMA", (JOB_SCHEMA[0], "INVALID SQL")):
                with self.assertRaises(sqlite3.OperationalError):
                    Store(path)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT * FROM segments").fetchall(), original)
                self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE name LIKE 'job_%'").fetchall(), [])
            finally:
                connection.close()
            with Store(path) as store:
                self.assertEqual(store.rows()[0].seconds, 60)


if __name__ == "__main__":
    unittest.main()
