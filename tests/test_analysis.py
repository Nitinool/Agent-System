import csv
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from activitylog.models import Activity, CATEGORIES, Segment
from activitylog.storage import Store
from activitylog.analysis import category_totals, filter_rows, merge_for_display


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.base = datetime(2026, 10, 2, 14, tzinfo=timezone(timedelta(hours=8)))
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "analysis.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store.db.close)

    def segment(self, offset, seconds, activity=None, reason="", resume_reason="", kind="activity"):
        activity = activity or Activity("chrome.exe", "视频教程", -1)
        start = self.base + timedelta(seconds=offset)
        identifier = self.store.begin(activity, start, kind, resume_reason)
        self.store.finish(identifier, start + timedelta(seconds=seconds), seconds, reason)
        return identifier

    def test_batch_category_persists_without_changing_raw_title_or_duration(self):
        first = self.segment(0, 60, reason="查看日志")
        second = self.segment(80, 30, resume_reason="查看日志")
        original = self.store.db.execute("SELECT * FROM segments ORDER BY id").fetchall()
        merged = merge_for_display(self.store.rows())
        self.assertEqual(len(merged), 1)
        self.store.set_category(merged[0].references, "学习")
        self.assertEqual(category_totals(self.store.rows())["学习"], 90)
        self.assertEqual(category_totals(self.store.rows())["未分类"], 0)
        self.assertEqual(self.store.db.execute("SELECT * FROM segments ORDER BY id").fetchall(), original)
        self.assertEqual(set(merged[0].references), {first, second})
        self.store.db.close()
        reopened = Store(self.path)
        self.addCleanup(reopened.db.close)
        self.assertTrue(all(row.category == "学习" for row in reopened.rows()))
        self.assertEqual(len(merge_for_display(reopened.rows())), 1)

    def test_unknown_and_nonactivity_intervals_do_not_inflate_category_totals(self):
        self.segment(0, 15)
        development = self.segment(20, 45, Activity("Codex.exe", "实现分析图", -2))
        self.store.set_category([development], "开发")
        self.segment(80, 600, Activity("", "锁屏"), kind="locked")
        self.store.gap(self.base + timedelta(seconds=700), self.base + timedelta(hours=2))
        totals = category_totals(self.store.rows())
        self.assertEqual(totals["开发"], 45)
        self.assertEqual(totals["未分类"], 15)
        self.assertEqual(totals["求职"], 0)
        self.assertEqual(sum(totals.values()), 60)
        self.assertEqual(set(totals), set(CATEGORIES))

    def test_category_search_and_app_filters_can_be_combined(self):
        reference = self.segment(0, 20, Activity("chrome.exe", "Python 视频教程", -1))
        self.store.set_category([reference], "学习")
        self.segment(30, 30, Activity("chrome.exe", "某个招聘页面", -1))
        self.segment(70, 10, Activity("Codex.exe", "PYTHON 项目", -2))
        rows = self.store.rows()
        self.assertEqual(len(filter_rows(rows, "python")), 2)
        selected = filter_rows(rows, "python", "浏览器 · Chrome", "学习")
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].title, "Python 视频教程")
        self.assertEqual(filter_rows(rows, "python", category="娱乐"), [])
        self.assertEqual(sum(category_totals(rows).values()), 60)

    def test_different_categories_are_not_merged_and_csv_includes_category(self):
        first = self.segment(0, 10, reason="查看日志")
        second = self.segment(20, 15, resume_reason="查看日志")
        self.store.set_category([first], "学习")
        self.store.set_category([second], "娱乐")
        self.assertEqual(len(merge_for_display(self.store.rows())), 2)
        path = Path(self.directory.name) / "categories.csv"
        self.store.export(path, merged=True)
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([row["分类"] for row in rows], ["学习", "娱乐"])
        self.assertEqual(sum(float(row["停留秒数"]) for row in rows), 25)

    def test_cross_midnight_classification_counts_only_selected_day(self):
        self.base = self.base.replace(hour=23, minute=59, second=50)
        reference = self.segment(0, 30)
        self.store.set_category([reference], "学习")
        self.assertEqual(category_totals(self.store.rows(date(2026, 10, 2)))["学习"], 10)
        self.assertEqual(category_totals(self.store.rows(date(2026, 10, 3)))["学习"], 20)
        with self.assertRaises(ValueError):
            self.store.set_category([reference], "不存在的分类")
        self.assertEqual(category_totals(self.store.rows())["学习"], 30)



if __name__ == "__main__":
    unittest.main()
