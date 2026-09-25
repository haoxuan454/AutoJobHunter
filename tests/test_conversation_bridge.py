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

    def test_outgoing_snapshot_is_recorded_as_user_sent_message(self):
        sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation,
            messages=[{"sender": "me", "text": "好的，我来介绍一下", "message_id": "out-1"}],
        )
        row = self.conn.execute("SELECT sender_type, is_sent FROM conv_messages").fetchone()
        self.assertEqual((row["sender_type"], row["is_sent"]), ("user", 1))

    def test_empty_snapshot_does_not_create_conversation_or_cursor(self):
        result = sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation, messages=[]
        )
        self.assertEqual(result["status"], "empty_messages")
        self.assertIsNone(result["conversation"])
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'conv_conversations'"
            ).fetchone()[0],
            0,
        )

    def test_unique_job_pool_match_replaces_synthetic_job_id_and_exposes_join_context(self):
        self.conn.executescript("""
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, title TEXT, company TEXT, hr_name TEXT, hr_title TEXT,
                url TEXT, score INTEGER, score_reason TEXT, status TEXT,
                source_platform TEXT, deleted_at TEXT, updated_at TEXT
            );
            INSERT INTO jobs VALUES (
                'job-real', 'Python 后端开发', 'Example', '李 HR', '招聘经理',
                'https://platform.test/job-real', 88, '技能匹配', 'scored', 'boss', NULL, '2026-09-25'
            );
        """)
        result = sync_extracted_messages(
            self.conn,
            job={"id": "sync:temporary", "hr_name": "李 HR", "company": "Example", "title": "Python 后端开发"},
            conversation={
                "hr_name": "李 HR", "company": "Example", "title": "Python 后端开发",
                "conversation_url": "https://www.zhipin.com/web/geek/chat?uid=hr-real",
            },
            messages=[{"sender": "hr", "text": "你好", "message_id": "m-real"}],
            platform="boss",
        )
        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["conversation"]["job_id"], "job-real")
        self.assertEqual(result["conversation"]["conversation_url"], "https://www.zhipin.com/web/geek/chat?uid=hr-real")
        self.assertEqual(result["conversation"]["job_company"], "Example")
        self.assertEqual(result["conversation"]["job_score"], 88)

    def test_multiple_job_pool_matches_are_rejected(self):
        self.conn.executescript("""
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, title TEXT, company TEXT, hr_name TEXT, hr_title TEXT,
                url TEXT, score INTEGER, score_reason TEXT, status TEXT,
                source_platform TEXT, deleted_at TEXT, updated_at TEXT
            );
            INSERT INTO jobs VALUES
                ('job-a', '同岗位', 'Example', '李 HR', '', 'https://a', 90, '', 'scored', 'boss', NULL, '2026-09-25'),
                ('job-b', '同岗位', 'Example', '李 HR', '', 'https://b', 80, '', 'scored', 'boss', NULL, '2026-09-24');
        """)
        result = sync_extracted_messages(
            self.conn,
            job={"id": "", "hr_name": "李 HR", "company": "Example", "title": "同岗位"},
            conversation={"hr_name": "李 HR", "company": "Example", "title": "同岗位"},
            messages=[{"sender": "hr", "text": "不能确定", "message_id": "m-ambiguous"}],
            platform="boss",
        )
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(sorted(result["job_candidates"]), ["job-a", "job-b"])
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'conv_conversations'"
            ).fetchone()[0],
            0,
        )


if __name__ == "__main__":
    unittest.main()
