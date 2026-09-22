import sqlite3
import unittest

from bosshunter.common_questions import list_common_questions, upsert_common_question


class CommonQuestionQueryTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        upsert_common_question(self.conn, "Python 框架怎么用？", "我会结合项目场景说明。")
        upsert_common_question(self.conn, "Python 框架怎么用？", "我会结合项目场景说明。")
        upsert_common_question(self.conn, "你做过哪些项目？", "我会按项目背景和职责说明。")

    def tearDown(self):
        self.conn.close()

    def test_default_sort_orders_by_occurrence_descending(self):
        rows = list_common_questions(self.conn)
        self.assertEqual(rows[0]["occurrence_count"], 2)
        self.assertEqual(rows[1]["occurrence_count"], 1)

    def test_question_search_is_fuzzy(self):
        rows = list_common_questions(self.conn, query="框架", sort="occurrence")
        self.assertEqual(len(rows), 1)
        self.assertIn("python", rows[0]["question"])

    def test_updated_sort_is_supported(self):
        rows = list_common_questions(self.conn, sort="updated")
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
