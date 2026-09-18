import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from bosshunter.conversation_scheduler import SerialConversationScheduler, init_scheduler_tables
from bosshunter.conversations import ConversationRepository
from bosshunter.notifications import (
    enqueue_alert,
    init_notification_tables,
    list_outbox,
    save_email_settings,
    send_outbox_item,
)


class NotificationsAndSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.repo = ConversationRepository(self.conn)
        self.repo.upsert_conversation({"id": "c1", "platform": "test", "hr_name": "A"})
        self.repo.upsert_conversation({"id": "c2", "platform": "test", "hr_name": "B"})
        init_notification_tables(self.conn)
        init_scheduler_tables(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_alert_outbox_is_idempotent(self):
        first = enqueue_alert(self.conn, conversation_id="c1", recipient="me@example.com", subject="salary", body="manual")
        second = enqueue_alert(self.conn, conversation_id="c1", recipient="me@example.com", subject="salary", body="manual")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(list_outbox(self.conn)), 1)
        self.assertEqual(first["status"], "pending")

    def test_smtp_delivery_is_explicit_and_marks_outbox(self):
        item = enqueue_alert(self.conn, conversation_id="c1", recipient="me@example.com", subject="salary", body="manual")
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        sent = send_outbox_item(self.conn, item["id"], {
            "enabled": True, "smtp_host": "smtp.example.com", "smtp_port": 465,
            "to_email": "me@example.com", "from_email": "me@example.com", "username": "me", "password": "secret",
        }, smtp_factory=lambda *args, **kwargs: smtp)
        self.assertEqual(sent["status"], "sent")
        smtp.send_message.assert_called_once()

    def test_scheduler_processes_at_most_one_and_skips_paused(self):
        scheduler = SerialConversationScheduler(self.conn)
        seen = []
        result = scheduler.run_once(lambda item: seen.append(item["id"]))
        self.assertEqual(result["status"], "processed")
        self.assertEqual(len(seen), 1)
        self.repo.update_status("c1", "paused_salary", "salary")
        self.repo.update_status("c2", "paused_manual", "manual")
        self.assertEqual(scheduler.run_once(lambda item: seen.append(item["id"]))["status"], "idle")

    def test_email_settings_keep_password_out_of_public_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = save_email_settings(Path(tmp), {}, {
                "enabled": True, "auto_send": False, "smtp_host": "smtp.example.com",
                "to_email": "me@example.com", "password": "secret",
            })
            self.assertTrue(result["password_set"])
            self.assertNotIn("password", (Path(tmp) / "config.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
