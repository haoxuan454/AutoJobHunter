import sqlite3
import unittest

from bosshunter.conversation_bridge import _stable_conversation_id, sync_extracted_messages
from bosshunter.conversations import ConversationRepository, IncomingMessage


class ConversationManagementTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.repo = ConversationRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def _conversation(self, conversation_id, platform, external_id, company, job):
        self.repo.upsert_conversation({
            "id": conversation_id, "platform": platform, "external_conversation_id": external_id,
            "company_id": company, "job_id": job, "hr_name": "HR", "status": "active",
        })
        self.repo.append_messages(conversation_id, [
            IncomingMessage(sender_type="hr", content="你好", message_time="2026-09-22T10:00:00Z"),
            IncomingMessage(sender_type="user", content="您好", message_time="2026-09-22T10:01:00Z"),
        ])

    def test_frequency_sort_and_round_count(self):
        self._conversation("boss:a", "boss", "a", "公司A", "岗位A")
        self._conversation("boss:b", "boss", "b", "公司B", "岗位B")
        self.repo.append_messages("boss:b", [IncomingMessage(sender_type="hr", content="请问技术方向？", message_time="2026-09-22T10:02:00Z")])
        items = self.repo.list_conversations(sort="frequency")
        self.assertEqual(items[0]["id"], "boss:b")
        self.assertEqual(items[0]["round_count"], 2)

    def test_delete_removes_local_history_and_blocks_bridge_recreation(self):
        conversation = {"external_conversation_id": "deleted", "hr_name": "HR"}
        conversation_id = _stable_conversation_id({"id": "岗位A", "company": "公司A"}, conversation, "boss")
        self._conversation(conversation_id, "boss", "deleted", "公司A", "岗位A")
        result = self.repo.delete_conversation(conversation_id)
        self.assertTrue(result["platform_untouched"])
        self.assertIsNone(self.repo.get_conversation(conversation_id))
        self.assertTrue(self.repo.is_deleted(conversation_id))
        self.assertEqual(self.repo.list_messages(conversation_id), [])
        sync = sync_extracted_messages(
            self.conn,
            job={"id": "岗位A", "company": "公司A"},
            conversation={"external_conversation_id": "deleted", "hr_name": "HR"},
            platform="boss",
            messages=[{"sender": "hr", "content": "新消息", "message_id": "m1"}],
        )
        self.assertTrue(sync["deleted"])
        self.assertEqual(sync["inserted"], [])


if __name__ == "__main__":
    unittest.main()
