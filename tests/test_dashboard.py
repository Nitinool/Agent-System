"""Dashboard integration uses disposable stores and never a live window reader."""

from datetime import date, datetime, timedelta, timezone
import unittest

from activitylog.finance import FinanceDraft
from activitylog.jobs import ApplicationDraft
from activitylog.models import Activity
from activitylog.projects import ProjectDraft, MilestoneDraft
from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.tasks import TaskDraft


class UnusedReader:
    def read(self):
        raise AssertionError('Dashboard must not capture the desktop')

    def is_locked(self):
        raise AssertionError('Dashboard must not capture the desktop')


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.service = ActivityService(self.store, UnusedReader())
        self.addCleanup(self.service.close)
        self.day = date(2026, 10, 8)
        self.service.tasks.today = lambda: self.day

    def test_empty_snapshot_does_not_write_or_start_capture(self):
        before = self.service.sync.snapshot()
        snapshot = self.service.dashboard.snapshot()
        self.assertEqual(snapshot.day, self.day)
        self.assertEqual(snapshot.tasks, ())
        self.assertEqual(snapshot.projects, ())
        self.assertEqual(snapshot.finance.income, 0)
        self.assertEqual(snapshot.finance.expense, 0)
        self.assertEqual(snapshot.activity.summary.total, 0)
        self.assertEqual(self.service.sync.snapshot(), before)
        self.assertIsNone(self.service.recorder.current)

    def test_finance_uses_current_settlement_month_and_excludes_pending(self):
        finance = self.service.finance
        finance.save(FinanceDraft('收入', '100.01', '2026-09-29', status='已到账', settled_on='2026-10-02'))
        finance.save(FinanceDraft('收入', '999.99', '2026-10-03', side_source='二手交易', status='待结算'))
        finance.save(FinanceDraft('收入', '300.00', '2026-09-01', status='已到账'))
        finance.save(FinanceDraft('支出', '25.02', '2026-10-03'))
        finance.save(FinanceDraft('支出', '10.00', '2026-10-03', settled_on='2026-11-01'))
        totals = self.service.dashboard.snapshot().finance
        self.assertEqual((totals.income, totals.expense), (10001, 2502))
        self.day = date(2026, 11, 1)
        totals = self.service.dashboard.snapshot().finance
        self.assertEqual((totals.income, totals.expense), (0, 1000))

    def test_projects_follow_active_priority_progress_and_real_history(self):
        projects, tasks = self.service.projects, self.service.tasks
        target = projects.save(ProjectDraft('目标', priority='高'))
        explore = projects.save(ProjectDraft('探索', priority='紧急', mode='探索型'))
        projects.save(ProjectDraft('规划', status='暂停'))
        projects.save(ProjectDraft('归档', status='已完成'))
        first = projects.save_milestone(target, MilestoneDraft('第一阶段'))
        projects.save_milestone(target, MilestoneDraft('第二阶段'))
        done = tasks.save(TaskDraft('已做', '', project_id=target, milestone_id=first))
        tasks.complete(done, True)
        tasks.save(TaskDraft('待做', '', project_id=target, milestone_id=first))
        attempt = tasks.save(TaskDraft('探索事项', '', project_id=explore))
        tasks.complete(attempt, True)
        tasks.complete(attempt, True)
        tasks.complete(attempt, False)
        tasks.complete(attempt, True)
        active = self.service.dashboard.snapshot().projects
        self.assertEqual([item.summary.project.id for item in active], [explore, target])
        self.assertEqual(active[0].completion_count, 2)
        self.assertEqual((active[1].summary.completed, active[1].summary.total), (1, 2))
        self.assertEqual(active[1].stage, '阶段 1 · 第一阶段')
        tasks.complete(attempt, False)
        self.assertEqual(self.service.dashboard.snapshot().projects[0].completion_count, 2)

    def test_shared_today_ranges_skips_completion_and_midnight(self):
        tasks = self.service.tasks
        ranged = tasks.save(TaskDraft('范围', '2026-10-08', range_start='2026-10-08', range_end='2026-10-10'), in_today=None)
        manual = tasks.add_today('手动')
        self.assertEqual({t.id for t in self.service.dashboard.snapshot().tasks}, {ranged, manual})
        tasks.remove_today(ranged)
        self.assertEqual({t.id for t in self.service.dashboard.snapshot().tasks}, {manual})
        self.day += timedelta(days=1)
        self.assertEqual({t.id for t in self.service.dashboard.snapshot().tasks}, {ranged})
        tasks.complete(ranged, True)
        self.assertFalse(self.service.dashboard.snapshot().tasks)
        tasks.complete(ranged, False)
        self.assertEqual({t.id for t in self.service.dashboard.snapshot().tasks}, {ranged})
        self.assertEqual({t.id for t in tasks.all_tasks()}, {manual, ranged})

    def test_time_is_clipped_today_grouped_by_app_and_excludes_locks(self):
        start = datetime(2026, 10, 7, 23, 59, tzinfo=timezone(timedelta(hours=8)))
        identifier = self.store.begin(Activity('chrome.exe', '跨午夜'), start)
        self.store.finish(identifier, start + timedelta(minutes=2), 120)
        for process, title, seconds in (('chrome.exe', '另一个标签', 20), ('msedge.exe', '相同用途不同应用', 30)):
            begin = start + timedelta(minutes=3)
            identifier = self.store.begin(Activity(process, title), begin)
            self.store.finish(identifier, begin + timedelta(seconds=seconds), seconds)
        begin = start + timedelta(minutes=4)
        identifier = self.store.begin(Activity('', '', 0), begin, kind='locked')
        self.store.finish(identifier, begin + timedelta(seconds=10), 10)
        summary = self.service.dashboard.snapshot().activity.summary
        self.assertEqual(summary.app_totals, {'浏览器 · Chrome': 80, '浏览器 · Edge': 30})
        self.assertEqual(summary.total, 110)
        self.assertEqual(summary.locked, 10)

    def test_jobs_match_existing_overview(self):
        self.service.jobs.save_application('公司', ApplicationDraft('岗位', '2026-10-08', '面试中'))
        self.assertEqual(self.service.dashboard.snapshot().jobs, self.service.jobs.snapshot().summary)
        self.assertEqual(self.service.dashboard.snapshot().jobs.interviews, 1)

    def test_snapshot_keeps_one_day_if_clock_crosses_midnight_while_reading(self):
        identifier = self.service.tasks.add_today('午夜前待办')
        days = iter((self.day, self.day + timedelta(days=1)))
        self.service.tasks.today = lambda: next(days)
        snapshot = self.service.dashboard.snapshot()
        self.assertEqual(snapshot.day, self.day)
        self.assertEqual({task.id for task in snapshot.tasks}, {identifier})
        self.assertEqual(snapshot.activity.day, snapshot.day)


if __name__ == '__main__':
    unittest.main()
