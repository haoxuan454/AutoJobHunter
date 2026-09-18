import sqlite3
import unittest

from bosshunter.conversation_bridge import sync_extracted_messages


class ConversationBridgeTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.job = {"id": "job-1", "hr_name": "李 HR", "company": "Example", "url": "https://example.test/job"}
        self.conversation = {"hr_name": "李 HR", "company": "Example", "source_url": "https://example.test/job"}

    def tearDown(self):
        self.conn.close()

    def test_snapshot_is_incremental_and_idempotent(self):
        messages = [{"sender": "hr", "text": "请介绍一下 Python 项目", "message_id": "m1"}]
        first = sync_extracted_messages(self.conn, job=self.job, conversation=self.conversation, messages=messages)
        second = sync_extracted_messages(self.conn, job=self.job, conversation=self.conversation, messages=messages)
        self.assertEqual(len(first["inserted"]), 1)
        self.assertEqual(second["inserted"], [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM conv_conversations").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM conv_messages").fetchone()[0], 1)
        self.assertIsNotNone(self.conn.execute("SELECT cursor_value FROM conv_sync_cursors").fetchone()[0])

    def test_salary_snapshot_pauses_only_that_conversation(self):
        result = sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation,
            messages=[{"sender": "hr", "text": "薪资范围可以接受吗？", "message_id": "salary-1"}],
        )
        self.assertEqual(result["conversation"]["status"], "paused_salary")
        self.assertIsNone(result["notification"])


if __name__ == "__main__":
    unittest.main()
