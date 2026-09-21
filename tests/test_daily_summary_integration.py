import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from bosshunter.conversations import ConversationRepository, IncomingMessage
from bosshunter.daily_summary import generate_daily_summary
from bosshunter.db import get_db
from bosshunter.notifications import list_outbox


class DailySummaryIntegrationTests(unittest.TestCase):
    DAY = "2026-09-21"
    UTC_ACTIVITY_TIME = "2026-09-20 16:30:00"

    def _config(self):
        return {
            "notifications": {
                "email": {
                    "enabled": False,
                    "auto_send": False,
                    "to_email": "owner@example.com",
                },
                "daily_summary": {
                    "enabled": True,
                    "auto_send": False,
                    "send_time": "20:00",
                    "timezone": "Asia/Shanghai",
                    "top_jobs_limit": 3,
                    "include_job_count": True,
                    "include_conversation_count": True,
                    "include_interested_hr": True,
                    "include_top_jobs": True,
                    "detail_level": "compact",
                },
            }
        }

    def test_real_sqlite_rows_are_aggregated_and_daily_outbox_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            db_path = base_dir / "data" / "bosshunter.db"
            conn = get_db(db_path)
            conn.execute(
                """INSERT INTO jobs (id, title, company, city, jd, url, score, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "job-1",
                    "Python 后端工程师",
                    "<Acme & Co>",
                    "长沙",
                    "FastAPI",
                    "https://jobs.example/job-1",
                    88,
                    "ready",
                    self.UTC_ACTIVITY_TIME,
                    self.UTC_ACTIVITY_TIME,
                ),
            )
            repo = ConversationRepository(conn)
            repo.upsert_conversation({
                "id": "hr-a",
                "platform": "boss",
                "hr_name": "李 HR",
                "company_id": "<Acme & Co>",
                "job_id": "job-1",
                "interest_score": 92,
                "status": "active",
            })
            repo.append_messages("hr-a", [IncomingMessage("hr", "方便聊聊薪资吗？", self.UTC_ACTIVITY_TIME, "hr-msg-1")])
            conn.execute("UPDATE conv_messages SET created_at = ? WHERE platform_message_id = ?", (self.UTC_ACTIVITY_TIME, "hr-msg-1"))
            conn.execute("UPDATE conv_conversations SET updated_at = ? WHERE id = ?", (self.UTC_ACTIVITY_TIME, "hr-a"))
            conn.commit()
            conn.close()

            config = self._config()
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            first = generate_daily_summary(conn, base_dir=base_dir, config=config, day=self.DAY)
            second = generate_daily_summary(conn, base_dir=base_dir, config=config, day=self.DAY)
            rows = list_outbox(conn)

            self.assertEqual(first["summary"]["job_count"], 1)
            self.assertEqual(first["summary"]["conversation_count"], 1)
            self.assertEqual(first["summary"]["interested_hr"][0]["hr_name"], "李 HR")
            self.assertEqual(first["summary"]["top_jobs"][0]["company"], "<Acme & Co>")
            self.assertEqual(first["notification"]["id"], second["notification"]["id"])
            self.assertEqual(len(rows), 1)
            self.assertIn("&lt;Acme &amp; Co&gt;", first["notification"]["html_body"])
            self.assertNotIn("<Acme & Co>", first["notification"]["html_body"])
            self.assertEqual(first["notification"]["status"], "pending")
            conn.close()


if __name__ == "__main__":
    unittest.main()
