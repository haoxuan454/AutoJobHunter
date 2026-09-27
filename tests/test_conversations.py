import sqlite3
import os
import tempfile
import threading
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

    def test_distinct_platform_ids_preserve_identical_messages(self):
        first = IncomingMessage("ai", "same reply", "2026-09-19T01:02:00+08:00", "lab-1")
        second = IncomingMessage("ai", "same reply", "2026-09-19T01:02:00+08:00", "lab-2")
        self.assertEqual(len(self.repo.append_messages("conv-1", [first, second])), 2)
        self.assertEqual(len(self.repo.list_messages("conv-1")), 2)

    def test_new_hr_message_sets_unread_and_duplicate_does_not_increment(self):
        message = IncomingMessage("hr", "New inbound message", "2026-09-19T01:03:00+08:00", "hr-new-1")

        self.assertEqual(len(self.repo.append_messages("conv-1", [message])), 1)
        self.assertEqual(len(self.repo.append_messages("conv-1", [message])), 0)

        conversation = self.repo.get_conversation("conv-1")
        self.assertEqual(conversation["unread_count"], 1)
        self.assertEqual(conversation["has_unread"], 1)

    def test_user_message_does_not_set_unread(self):
        message = IncomingMessage(
            "user", "Previously sent greeting", "2026-09-19T01:04:00+08:00", "user-1", is_sent=True,
        )

        self.repo.append_messages("conv-1", [message])

        conversation = self.repo.get_conversation("conv-1")
        self.assertEqual(conversation["unread_count"], 0)
        self.assertEqual(conversation["has_unread"], 0)

    def test_empty_hr_message_is_rejected_without_setting_unread(self):
        with self.assertRaises(ValueError):
            self.repo.append_messages("conv-1", [IncomingMessage("hr", "   ", platform_message_id="empty-1")])

        conversation = self.repo.get_conversation("conv-1")
        self.assertEqual(conversation["unread_count"], 0)
        self.assertEqual(conversation["has_unread"], 0)
        self.assertEqual(self.repo.list_messages("conv-1"), [])

    def test_opening_conversation_clears_unread_marker(self):
        self.repo.append_messages("conv-1", [
            IncomingMessage("hr", "Unread one", "2026-09-19T01:05:00+08:00", "hr-2"),
            IncomingMessage("hr", "Unread two", "2026-09-19T01:06:00+08:00", "hr-3"),
        ])
        self.assertEqual(self.repo.get_conversation("conv-1")["unread_count"], 2)

        conversation = self.repo.mark_conversation_read("conv-1")

        self.assertEqual(conversation["unread_count"], 0)
        self.assertEqual(conversation["has_unread"], 0)
        self.assertIsNotNone(conversation["last_read_at"])

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

    def test_send_attempt_claim_is_atomic_across_independent_connections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "claims.sqlite3")
            seed = sqlite3.connect(db_path)
            seed.row_factory = sqlite3.Row
            ConversationRepository(seed)
            seed.close()

            barrier = threading.Barrier(2)
            results = []
            errors = []

            def claim():
                conn = sqlite3.connect(db_path, timeout=10)
                conn.row_factory = sqlite3.Row
                try:
                    repo = ConversationRepository(conn)
                    barrier.wait(timeout=5)
                    results.append(repo.claim_send_attempt(
                        user_id="user-1",
                        conversation_id="conv-atomic",
                        idempotency_key="same-atomic-key",
                        message_hash="same-message-hash",
                        platform="boss",
                    )[1])
                except Exception as exc:  # surfaced in the parent test thread
                    errors.append(exc)
                finally:
                    conn.close()

            workers = [threading.Thread(target=claim) for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=15)

            self.assertTrue(all(not worker.is_alive() for worker in workers), "claim worker hung")
            self.assertEqual(errors, [])
            self.assertEqual(sorted(results), [False, True])
        names = {
            row[0] for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'conv_%'"
            )
        }
        self.assertEqual(names, {"conv_conversations", "conv_messages", "conv_sync_cursors", "conv_drafts", "conv_deleted_conversations", "conv_send_attempts"})

    def test_legacy_jobs_schema_without_hr_snapshot_columns_is_readable(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE jobs (
                id TEXT PRIMARY KEY, title TEXT, company TEXT,
                url TEXT, score INTEGER, status TEXT
            )"""
        )
        conn.execute(
            "INSERT INTO jobs (id, title, company, url, score, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("legacy-job", "Python Engineer", "Example Co", "https://example.test/job/1", 80, "ready"),
        )
        repo = ConversationRepository(conn)
        repo.upsert_conversation({
            "id": "legacy-conversation", "platform": "boss",
            "job_id": "legacy-job", "hr_name": "刘先生",
        })

        detail = repo.get_conversation("legacy-conversation")
        listed = repo.list_conversations()

        self.assertEqual(detail["job_title"], "Python Engineer")
        self.assertEqual(detail["job_company"], "Example Co")
        self.assertIsNone(detail["job_hr_name"])
        self.assertEqual(detail["display_hr_name"], "刘先生")
        self.assertEqual(listed[0]["job_score"], 80)
        self.assertIsNone(listed[0]["job_score_reason"])
        conn.close()

    def test_draft_is_stored_but_not_sent(self):
        draft = self.repo.save_draft("conv-1", "这是一个需要人工确认的草稿", 1)
        self.assertEqual(draft["status"], "waiting_approval")
        self.assertEqual(draft["draft_text"], "这是一个需要人工确认的草稿")


if __name__ == "__main__":
    unittest.main()
