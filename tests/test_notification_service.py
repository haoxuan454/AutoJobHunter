import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from bosshunter.conversations import ConversationRepository
from bosshunter.notification_service import process_hr_message, process_lab_message
from bosshunter.notifications import init_notification_tables, list_outbox, send_outbox_item


class NotificationServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.repo = ConversationRepository(self.conn)
        self.repo.upsert_conversation({"id": "a", "platform": "test", "hr_name": "HR A", "company_id": "A 公司", "hr_profile_url": "https://a.test"})
        self.repo.upsert_conversation({"id": "b", "platform": "test", "hr_name": "HR B", "company_id": "B 公司", "hr_profile_url": "https://b.test"})
        init_notification_tables(self.conn)

    def tearDown(self):
        self.conn.close()

    def _config(self, base_dir):
        return {"notifications": {"email": {"enabled": True, "auto_send": False, "to_email": "me@example.com", "notification_types": ["salary"]}}}

    def test_only_matching_conversation_is_paused_and_enqueued(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = process_hr_message(self.conn, conversation_id="a", message="薪酬结构可以聊聊吗", message_id="m1", base_dir=Path(tmp), config=self._config(Path(tmp)))
            self.assertEqual(result["conversation"]["status"], "paused_salary")
            self.assertEqual(self.repo.get_conversation("b")["status"], "new")
            rows = list_outbox(self.conn)
            self.assertEqual(len(rows), 1)
            self.assertIn("A 公司", rows[0]["body"])
            self.assertNotIn("B 公司", rows[0]["body"])

    def test_duplicate_message_id_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            process_hr_message(self.conn, conversation_id="a", message="薪资范围方便沟通吗", message_id="m1", base_dir=Path(tmp), config=config)
            process_hr_message(self.conn, conversation_id="a", message="薪资范围方便沟通吗", message_id="m1", base_dir=Path(tmp), config=config)
            self.assertEqual(len(list_outbox(self.conn)), 1)

    def test_lab_requires_explicit_notification_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            result = process_lab_message(self.conn, session_id="s1", message="薪资可以接受吗", base_dir=Path(tmp), config=config)
            self.assertIsNotNone(result["notification"])
            self.assertEqual(result["notification"]["status"], "pending")
            result = process_lab_message(self.conn, session_id="s2", message="薪资可以接受吗", base_dir=Path(tmp), config=config, allow_send=True)
            self.assertIsNotNone(result["notification"])

    def test_smtp_failure_is_recorded_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                item = __import__("bosshunter.notifications", fromlist=["enqueue_alert"]).enqueue_alert(self.conn, conversation_id="a", recipient="me@example.com", subject="x", body="x")
                smtp = MagicMock()
                smtp.__enter__.return_value = smtp
                smtp.send_message.side_effect = RuntimeError("smtp down")
                send_outbox_item(self.conn, item["id"], {"enabled": True, "auto_send": True, "smtp_host": "smtp.test", "smtp_port": 465, "to_email": "me@example.com", "username": "me", "password": "secret"}, smtp_factory=lambda *args, **kwargs: smtp)
            row = list_outbox(self.conn)[0]
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
