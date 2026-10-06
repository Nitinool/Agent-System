"""Exact amounts, settlement dates, source totals and transactional v5 upgrades."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from activitylog.finance import FinanceDraft, amount_text, filter_entries, money_text, parse_amount, validate_month
from activitylog.finance_store import FINANCE_SCHEMA
from activitylog.jobs import ApplicationDraft
from activitylog.models import Activity
from activitylog.projects import MilestoneDraft, ProjectDraft
from activitylog.service import ActivityService
from activitylog.storage import SCHEMA_VERSION, Store
from activitylog.sync import SyncError, decode, encode, merge
from activitylog.tasks import TaskDraft
from activitylog.ui.sync import version_text
from tests.ui_smoke import FixtureReader


class FinanceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "finance.sqlite3"
        self.app = ActivityService(Store(self.path), FixtureReader())
        self.addCleanup(self.app.close)
        self.finance = self.app.finance
        self.pending = FinanceDraft("收入", "1500.50", "2026-10-01", "卖出物品", "副业收入", "二手交易", "待结算", notes="等待平台结算")

    def test_amounts_are_exact_and_invalid_values_are_rejected(self):
        self.assertEqual(parse_amount("0.1") + parse_amount("0.2"), 30)
        self.assertEqual(parse_amount(" 120.50 "), 12050)
        self.assertEqual(amount_text(-101), "-1.01")
        self.assertEqual(money_text(150050), "¥1,500.50")
        for value in ("", "0", "-1", "+1", "1e2", "NaN", "Infinity", "1.005", "1,000", "1.", ".1", "1" * 30, "1000000000.01"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_amount(value)

    def test_pending_income_is_not_cash_and_survives_month_change(self):
        self.finance.save(self.pending)
        october = self.finance.snapshot("2026-10")
        self.assertEqual(october.totals.income, 0)
        self.assertEqual(october.totals.net, 0)
        self.assertEqual(october.totals.pending, 150050)
        november = self.finance.snapshot("2026-11")
        self.assertEqual(november.entries, ())
        self.assertEqual(len(november.pending_entries), 1)
        self.assertEqual(november.sources[0].totals.pending, 150050)

    def test_settlement_updates_same_record_and_counts_actual_month_and_amount(self):
        identifier = self.finance.save(self.pending)
        self.finance.save(replace(self.pending, amount="1450.25", status="已到账", settled_on="2026-11-03"), identifier)
        self.assertEqual(len(self.finance.repository.entries()), 1)
        entry = self.finance.get(identifier)
        self.assertEqual(entry.occurred_on, date(2026, 10, 1))
        self.assertEqual(entry.settled_on, date(2026, 11, 3))
        self.assertEqual(self.finance.snapshot("2026-10").totals.income, 0)
        november = self.finance.snapshot("2026-11")
        self.assertEqual(november.totals.income, 145025)
        self.assertEqual(november.totals.pending, 0)
        self.assertEqual(november.sources[0].totals.income, 145025)
        self.finance.save(replace(self.pending, amount="1450.25", status="已到账", settled_on="2026-11-03"), identifier)
        self.assertEqual(self.finance.snapshot("2026-11").totals.income, 145025)

    def test_side_costs_and_daily_expenses_share_ledger_without_duplicate_totals(self):
        self.finance.save(replace(self.pending, status="已到账", settled_on="2026-10-03"))
        self.finance.save(FinanceDraft("支出", "200.25", "2026-10-02", "运费与工具", "副业成本", "二手交易"))
        self.finance.save(FinanceDraft("支出", "50.10", "2026-10-02", "午饭", "餐饮"))
        self.finance.save(FinanceDraft("收入", "5000", "2026-10-02", "工资", "工资", status="已到账"))
        snapshot = self.finance.snapshot("2026-10")
        self.assertEqual(snapshot.totals.income, 650050)
        self.assertEqual(snapshot.totals.expense, 25035)
        self.assertEqual(snapshot.totals.net, 625015)
        self.assertEqual(len(snapshot.sources), 1)
        self.assertEqual(snapshot.sources[0].totals.net, 130025)
        filtered = filter_entries(snapshot.entries, direction="收入", source="二手交易")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(snapshot.totals.income, 650050)

    def test_source_history_reuses_case_and_search_uses_notes(self):
        self.finance.save(replace(self.pending, side_source="Store"))
        self.finance.save(FinanceDraft("支出", "12", "2026-10-01", "快递", "副业成本", "store", notes="寄往上海"))
        snapshot = self.finance.snapshot("2026-10")
        self.assertEqual(len(snapshot.sources), 1)
        self.assertEqual(snapshot.sources[0].totals.expense, 1200)
        self.assertEqual(self.finance.history()[0], ("Store",))
        self.assertEqual(len(filter_entries(snapshot.entries, keyword="上海")), 1)
        self.assertEqual(len(filter_entries(snapshot.entries, source="STORE")), 2)

    def test_validation_rejects_invalid_statuses_dates_and_sources_without_saving(self):
        for draft in (replace(self.pending, side_source=""), replace(self.pending, direction="支出"),
                      replace(self.pending, status="已支付"), replace(self.pending, occurred_on="2026-02-30"),
                      replace(self.pending, occurred_on="20261001"), replace(self.pending, category=""),
                      replace(self.pending, side_source="全部来源"), replace(self.pending, title="x" * 501),
                      replace(self.pending, status="已到账", settled_on="2026-09-30")):
            with self.subTest(draft=draft), self.assertRaises(ValueError):
                self.finance.save(draft)
        self.assertEqual(self.finance.repository.entries(), ())

    def test_reopening_receipt_clears_date_and_removes_received_income(self):
        identifier = self.finance.save(replace(self.pending, status="已到账", settled_on="2026-10-02"))
        self.finance.save(replace(self.pending, settled_on="2026-10-02"), identifier)
        self.assertIsNone(self.finance.get(identifier).settled_on)
        self.assertEqual(self.finance.snapshot("2026-10").totals.income, 0)
        self.assertEqual(self.finance.snapshot("2026-10").totals.pending, 150050)

    def test_restart_and_deleted_record_do_not_duplicate_or_recreate_entries(self):
        identifier = self.finance.save(self.pending)
        with Store(self.path) as store:
            reopened = ActivityService(store, FixtureReader())
            self.assertEqual(reopened.finance.get(identifier).notes, "等待平台结算")
            self.assertEqual(reopened.finance.snapshot("2026-10").totals.pending, 150050)
        self.finance.delete(identifier)
        with self.assertRaises(ValueError):
            self.finance.save(self.pending, identifier)
        with self.assertRaises(ValueError):
            self.finance.get(identifier)
        self.assertEqual(self.finance.snapshot("").totals.pending, 0)

    def test_month_validation_keeps_canonical_months(self):
        self.assertEqual(validate_month(""), "")
        self.assertEqual(validate_month("2026-01"), "2026-01")
        for value in ("2026-1", "2026-13", "0000-01", "2026-10-01", "bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.finance.snapshot(value)


class FinanceMigrationTests(unittest.TestCase):
    def fixture(self, path):
        app = ActivityService(Store(path), FixtureReader())
        try:
            project = app.projects.save(ProjectDraft("保留项目"))
            milestone = app.projects.save_milestone(project, MilestoneDraft("保留阶段"))
            task = app.tasks.save(TaskDraft("保留事项", "2026-10-05", project_id=project, milestone_id=milestone), in_today=True)
            app.tasks.complete(task, True)
            app.jobs.save_application("保留公司", ApplicationDraft("保留岗位", "2026-10-05"))
            now = datetime.now().astimezone()
            segment = app.store.begin(Activity("fixture.exe", "保留日志", -1), now)
            app.store.finish(segment, now, 10)
            app.store.set_category([segment], "学习")
            before = app.sync.snapshot()
            app.sync.apply(before, before)
            with app.store.db:
                app.store.db.execute("DROP TABLE finance_entries")
                app.store.db.execute('DROP TRIGGER sync_insert_projects')
                app.store.db.execute('DROP TRIGGER project_identity')
                app.store.db.execute('DROP INDEX project_keys')
                for column in ('priority', 'mode', 'project_key'):
                    app.store.db.execute(f'ALTER TABLE projects DROP COLUMN {column}')
                for column in ('range_start', 'range_end'):
                    app.store.db.execute(f'ALTER TABLE tasks DROP COLUMN {column}')
                app.store.db.execute('DROP TABLE task_day_exclusions')
                app.store.db.execute("PRAGMA user_version=5")
            return before
        finally:
            app.close()

    def test_v5_upgrade_preserves_all_shared_records_logs_and_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v5.sqlite3"
            before = self.fixture(path)
            with Store(path) as store:
                app = ActivityService(store, FixtureReader())
                self.assertEqual(app.sync.snapshot(), before)
                self.assertEqual(app.sync.baseline(), before)
                self.assertEqual(app.finance.repository.entries(), ())
                self.assertEqual(store.db.execute("SELECT category FROM classifications").fetchone()[0], "学习")
                self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                self.assertEqual(store.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_failed_v5_upgrade_rolls_back_finance_table_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v5.sqlite3"
            self.fixture(path)
            with patch("activitylog.storage.FINANCE_SCHEMA", FINANCE_SCHEMA + ("INVALID SQL",)):
                with self.assertRaises(sqlite3.Error):
                    Store(path)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='finance_entries'").fetchone())
                self.assertEqual(connection.execute("SELECT title FROM tasks").fetchone()[0], "保留事项")
            finally:
                connection.close()


class FinanceSyncTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.a = ActivityService(Store(Path(directory.name) / "a.sqlite3"), FixtureReader())
        self.b = ActivityService(Store(Path(directory.name) / "b.sqlite3"), FixtureReader())
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)
        self.remote = {}
        self.pending = FinanceDraft("收入", "888.88", "2026-10-01", "卖出耳机", "副业收入", "二手交易", "待结算")

    def sync(self, app, choices=None):
        local = app.sync.snapshot()
        merged, conflicts = merge(app.sync.baseline(), local, self.remote, choices)
        self.assertFalse(conflicts)
        self.remote = decode(encode(merged))
        app.sync.apply(local, self.remote)

    def test_two_devices_settlement_and_deletion_keep_exact_amounts_and_dates(self):
        identifier = self.a.finance.save(self.pending)
        self.sync(self.a)
        self.sync(self.b)
        self.assertEqual(self.b.finance.snapshot("2026-11").totals.pending, 88888)
        other = self.b.finance.repository.entries()[0].id
        self.b.finance.save(replace(self.pending, amount="850.01", status="已到账", settled_on="2026-11-05"), other)
        self.sync(self.b)
        self.sync(self.a)
        self.assertEqual(self.a.finance.get(identifier).settled_on, date(2026, 11, 5))
        self.assertEqual(self.a.finance.snapshot("2026-11").totals.income, 85001)
        self.assertEqual(self.a.finance.snapshot("2026-10").totals.income, 0)
        self.assertEqual(self.a.sync.status()[0], 0)
        self.b.finance.delete(other)
        self.sync(self.b)
        self.sync(self.a)
        self.assertEqual(self.a.finance.repository.entries(), ())

    def test_concurrent_amount_changes_require_explicit_choice(self):
        identifier = self.a.finance.save(self.pending)
        self.sync(self.a)
        self.sync(self.b)
        other = self.b.finance.repository.entries()[0].id
        self.a.finance.save(replace(self.pending, amount="800"), identifier)
        self.b.finance.save(replace(self.pending, amount="900"), other)
        self.sync(self.a)
        local = self.b.sync.snapshot()
        _, conflicts = merge(self.b.sync.baseline(), local, self.remote)
        self.assertEqual(len(conflicts), 1)
        preview = version_text(conflicts[0].local, local)
        self.assertIn("¥900.00", preview)
        self.assertIn("待结算", preview)
        self.assertNotIn("amount_cents", preview)
        self.sync(self.b, {conflicts[0].uid: "local"})
        self.sync(self.a)
        self.assertEqual(self.a.finance.get(identifier).amount_cents, 90000)

    def test_independent_local_ids_merge_and_deleted_entry_is_not_revived(self):
        identifier = self.a.finance.save(self.pending)
        other = self.b.finance.save(FinanceDraft("支出", "50.05", "2026-10-02", "副业运费", "副业成本", "二手交易"))
        self.assertEqual(identifier, other)
        self.sync(self.a)
        self.sync(self.b)
        self.sync(self.a)
        self.assertEqual(len(self.a.finance.repository.entries()), 2)
        self.assertEqual(self.a.finance.snapshot("2026-10").totals.expense, 5005)
        self.a.finance.delete(identifier)
        self.sync(self.a)
        self.sync(self.b)
        self.sync(self.a)
        self.assertEqual(len(self.a.finance.repository.entries()), 1)
        self.assertEqual(self.b.finance.snapshot("2026-10").totals.pending, 0)

    def test_version_one_remains_readable_and_financial_records_require_version_two(self):
        self.assertEqual(json.loads(encode({}))["version"], 1)
        self.a.finance.save(self.pending)
        content = encode(self.a.sync.snapshot())
        payload = json.loads(content)
        self.assertEqual(payload["version"], 2)
        self.assertEqual(decode(content), self.a.sync.snapshot())
        payload["version"] = 1
        with self.assertRaises(SyncError):
            decode(json.dumps(payload))

    def test_invalid_remote_amount_status_or_date_is_rejected_without_mutation(self):
        self.a.finance.save(self.pending)
        before = self.a.sync.snapshot()
        for key, value in (("amount_cents", True), ("amount_cents", 1.5), ("amount_cents", -1),
                           ("direction", "支出"), ("side_source", ""), ("settled_on", "2026-10-02"),
                           ("occurred_on", "bad"), ("status", "已到账")):
            invalid = deepcopy(before)
            next(iter(invalid.values()))["fields"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(SyncError):
                self.a.sync.apply(before, invalid)
            self.assertEqual(self.a.sync.snapshot(), before)
