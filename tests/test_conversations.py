import sqlite3
import unittest

from bosshunter.conversations import ConversationRepository, IncomingMessage, init_conversation_tables


class ConversationRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.repo = ConversationRepository(self.conn)
        self.repo.upsert_conversation({
            "id": "conv-1",
            "platform": "boss",
            "external_conversation_id": "boss-chat-1",
            "hr_name": "李女士",
            "job_id": "job-1",
        })

    def tearDown(self):
        self.conn.close()

    def test_message_with_platform_id_is_inserted_only_once(self):
        message = IncomingMessage("hr", "你之前做过 Python 项目吗？", "2026-09-19T01:00:00+08:00", "m-1")
        self.assertEqual(len(self.repo.append_messages("conv-1", [message])), 1)
        self.assertEqual(len(self.repo.append_messages("conv-1", [message])), 0)
        self.assertEqual(len(self.repo.list_messages("conv-1")), 1)

    def test_message_without_platform_id_uses_fallback_identity(self):
        message = IncomingMessage("hr", "请介绍一下你的项目", "2026-09-19T01:01:00+08:00")
        self.assertEqual(len(self.repo.append_messages("conv-1", [message, message])), 1)
        self.assertEqual(len(self.repo.list_messages("conv-1")), 1)

    def test_cursor_is_saved_and_updated_on_conversation(self):
        self.assertIsNone(self.repo.get_cursor("conv-1"))
        self.repo.save_cursor("conv-1", "cursor-10")
        self.assertEqual(self.repo.get_cursor("conv-1"), "cursor-10")
        conversation = self.repo.get_conversation("conv-1")
        self.assertEqual(conversation["sync_cursor"], "cursor-10")
        self.assertIsNotNone(conversation["last_sync_at"])

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(ValueError):
            self.repo.upsert_conversation({"id": "conv-2", "platform": "boss", "status": "sending"})

    def test_initialization_is_idempotent(self):
        init_conversation_tables(self.conn)
        init_conversation_tables(self.conn)
        names = {
            row[0] for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'conv_%'"
            )
        }
        self.assertEqual(names, {"conv_conversations", "conv_messages", "conv_sync_cursors", "conv_drafts"})

    def test_draft_is_stored_but_not_sent(self):
        draft = self.repo.save_draft("conv-1", "这是一个需要人工确认的草稿", 1)
        self.assertEqual(draft["status"], "waiting_approval")
        self.assertEqual(draft["draft_text"], "这是一个需要人工确认的草稿")


if __name__ == "__main__":
    unittest.main()
