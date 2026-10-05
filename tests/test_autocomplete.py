import unittest

from activitylog.ui.autocomplete import matching_history


class HistoryMatchingTests(unittest.TestCase):
    def test_chinese_prefix_before_substring(self):
        values = ('中国能源建设集团', '华润电力', '中国电力工程顾问集团', '电力设计院')
        self.assertEqual(matching_history(values, ' 电力 '),
                         ('电力设计院', '华润电力', '中国电力工程顾问集团'))

    def test_case_and_duplicate_names(self):
        self.assertEqual(matching_history(('Python 开发', 'python 开发', ' AI Agent ', '', 'Agent开发'), 'agent'),
                         ('Agent开发', 'AI Agent'))

    def test_empty_and_unmatched_input(self):
        self.assertEqual(matching_history(('副业收入', '工资'), ''), ('副业收入', '工资'))
        self.assertEqual(matching_history(('副业收入', '工资'), '全新的分类'), ())
