import sqlite3
import unittest

from bosshunter.conversation_analytics import build_conversation_analytics
from bosshunter.conversations import ConversationRepository, IncomingMessage


class ConversationAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.repo = ConversationRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_empty_database_returns_empty_local_analytics(self):
        data = build_conversation_analytics(self.conn)
        self.assertEqual(data["conversations_total"], 0)
        self.assertEqual(data["messages_total"], 0)
        self.assertEqual(data["job_directions"], [])
        self.assertEqual(data["hr_question_keywords"], [])

    def test_analytics_excludes_unlinked_sync_rows_and_sorts_hr_quotes(self):
        self.conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, title TEXT)")
        self.conn.executemany("INSERT INTO jobs (id, title) VALUES (?, ?)", [
            ("job-py", "Python 工程师"), ("job-java", "Java 工程师"),
        ])
        self.conn.commit()
        self.repo.upsert_conversation({"id": "boss-py", "platform": "boss", "job_id": "job-py", "status": "active"})
        self.repo.upsert_conversation({"id": "zhilian-py", "platform": "zhilian", "job_id": "job-py", "status": "waiting_reply"})
        self.repo.upsert_conversation({"id": "boss-java", "platform": "boss", "job_id": "job-java", "status": "active"})
        self.repo.upsert_conversation({"id": "other-user", "user_id": "another-user", "platform": "boss", "job_id": "job-java", "status": "active"})
        self.repo.upsert_conversation({"id": "old-sync", "platform": "boss", "job_id": "sync:unknown"})
        self.repo.upsert_conversation({"id": "unlinked", "platform": "boss", "job_id": ""})

        self.repo.append_messages("boss-py", [
            IncomingMessage("hr", "可以介绍一下你的项目吗？", "2026-09-27 09:00", "q-1"),
            IncomingMessage("hr", "可以介绍一下你的项目吗？", "2026-09-27 09:01", "q-2"),
            IncomingMessage("user", "我做过 Python 项目。", "2026-09-27 09:02", "a-1", is_sent=True),
        ])
        self.repo.append_messages("boss-java", [
            IncomingMessage("hr", "你的期望薪资是多少？", "2026-09-26 15:00", "q-3"),
            IncomingMessage("system", "历史记录确认已投递；原始招呼正文未保存", "2026-09-26 10:00", "history-sent", raw_payload={"source": "local_delivery_reconciliation", "action": "sent"}),
        ])
        self.repo.append_messages("zhilian-py", [
            IncomingMessage("system", "平台默认招呼已确认", "2026-09-27 08:30", "default-greeting", raw_payload={"source": "verified_delivery", "delivery_kind": "platform_default_greeting"}),
        ])
        self.repo.append_messages("boss-py", [
            IncomingMessage("user", "补充说明：我也做过自动化测试。", "2026-09-28 09:00", "a-2", is_sent=True),
        ])
        self.repo.append_messages("other-user", [
            IncomingMessage("user", "另一用户的消息", "2026-09-25 09:00", "other-a", is_sent=True),
            IncomingMessage("hr", "另一用户的 HR 回复", "2026-09-26 09:00", "other-q"),
        ])

        data = build_conversation_analytics(self.conn)
        self.assertEqual(data["conversations_total"], 3)
        self.assertEqual(data["messages_total"], 7)
        self.assertEqual(data["hr_question_keywords"][0], {"content": "可以介绍一下你的项目吗？", "count": 2})
        directions = {row["label"]: row for row in data["job_directions"]}
        python_label = "Python \u5de5\u7a0b\u5e08"
        java_label = "Java \u5de5\u7a0b\u5e08"
        self.assertEqual(directions[python_label]["conversations"], 2)
        self.assertEqual(directions[python_label]["replied_conversations"], 1)
        self.assertEqual(directions[python_label]["reply_rate"], 50)
        self.assertEqual(directions[java_label]["conversations"], 1)
        self.assertEqual(directions[java_label]["replied_conversations"], 1)
        self.assertEqual(directions[java_label]["reply_rate"], 100)
        trend = {row["day"]: row for row in data["daily_trend"]}
        self.assertEqual(trend["2026-09-26"]["deliveries"], 1)
        self.assertEqual(trend["2026-09-27"]["deliveries"], 2)
        self.assertEqual(trend["2026-09-28"]["deliveries"], 0)
        self.assertEqual(trend["2026-09-28"]["outgoing_messages"], 1)
        self.assertEqual(sum(row["count"] for row in data["by_status"]), 3)

        other_user_data = build_conversation_analytics(self.conn, "another-user")
        self.assertEqual(other_user_data["conversations_total"], 1)
        self.assertEqual(other_user_data["messages_total"], 2)
        self.assertEqual(other_user_data["daily_trend"][0]["day"], "2026-09-25")

        injection_like_user = build_conversation_analytics(self.conn, "default' OR 1=1 --")
        self.assertEqual(injection_like_user["conversations_total"], 0)
        self.assertEqual(injection_like_user["messages_total"], 0)


if __name__ == "__main__":
    unittest.main()
