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

    def test_zhilian_legacy_dom_id_migrates_in_place_and_stays_idempotent(self):
        old_id = "dom-0--hello from me"
        stable_id = "zhilian-Tuesday 21:00-me-hello from me"
        legacy = [{"sender": "me", "text": "hello from me", "message_id": old_id}]
        current = [{
            "sender": "me", "text": "hello from me", "message_time": "Tuesday 21:00",
            "message_id": stable_id, "legacy_message_id": old_id,
        }]
        sync_extracted_messages(self.conn, job=self.job, conversation=self.conversation, platform="zhilian", messages=legacy)
        migrated = sync_extracted_messages(self.conn, job=self.job, conversation=self.conversation, platform="zhilian", messages=current)
        repeated = sync_extracted_messages(self.conn, job=self.job, conversation=self.conversation, platform="zhilian", messages=current)
        rows = self.conn.execute("SELECT platform_message_id, sender_type, is_sent, message_time FROM conv_messages").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(tuple(rows[0]), (stable_id, "user", 1, "Tuesday 21:00"))
        self.assertEqual(migrated["inserted"], [])
        self.assertEqual(repeated["inserted"], [])

    def test_zhilian_legacy_id_migration_requires_same_sender_and_text(self):
        old_id = "dom-0--same text"
        sync_extracted_messages(self.conn, job=self.job, conversation=self.conversation, platform="zhilian", messages=[
            {"sender": "hr", "text": "same text", "message_id": old_id},
        ])
        sync_extracted_messages(self.conn, job=self.job, conversation=self.conversation, platform="zhilian", messages=[
            {"sender": "me", "text": "same text", "message_id": "zhilian-new-me-same text", "legacy_message_id": old_id},
        ])
        rows = self.conn.execute("SELECT platform_message_id, sender_type FROM conv_messages ORDER BY id").fetchall()
        self.assertEqual([tuple(row) for row in rows], [
            (old_id, "hr"), ("zhilian-new-me-same text", "user"),
        ])

    def test_zhilian_old_generated_id_is_adopted_and_card_text_is_canonicalized(self):
        card_title = "\u6211\u60f3\u4e0e\u60a8\u7535\u8bdd\u6c9f\u901a\u804c\u4f4d"
        old_content = card_title + " \u540c\u610f\u540e\uff0c\u5bf9\u65b9\u5c06\u4f1a\u770b\u5230\u60a8\u7684\u7535\u8bdd \u62d2\u7edd \u540c\u610f"
        canonical = card_title + "\uff0c\u671f\u5f85\u56de\u590d"
        old_id = "zhilian--hr-" + old_content
        sync_extracted_messages(self.conn, job=self.job, conversation=self.conversation, platform="zhilian", messages=[
            {"sender": "hr", "text": old_content, "message_id": old_id},
        ])
        snapshot = [{
            "sender": "hr", "text": canonical, "message_time": "10:00",
            "message_id_is_native": False, "legacy_message_id": "dom-0--" + canonical,
        }]
        first = sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation, platform="zhilian",
            messages=snapshot, history_complete=True,
        )
        second = sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation, platform="zhilian",
            messages=snapshot, history_complete=True,
        )
        rows = self.conn.execute("SELECT platform_message_id, content FROM conv_messages").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0][0].startswith("zhilian-snapshot:"))
        self.assertEqual(rows[0][1], canonical)
        self.assertEqual(first["inserted"], [])
        self.assertEqual(second["inserted"], [])

    def test_zhilian_synthetic_ids_are_stable_and_keep_repeated_messages(self):
        snapshot = [
            {"sender": "hr", "text": "Same message", "message_time": "10:00", "message_id_is_native": False},
            {"sender": "hr", "text": "Same message", "message_time": "10:00", "message_id_is_native": False},
        ]
        first = sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation, platform="zhilian",
            messages=snapshot, history_complete=False,
        )
        second = sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation, platform="zhilian",
            messages=snapshot, history_complete=False,
        )
        rows = self.conn.execute(
            "SELECT platform_message_id FROM conv_messages ORDER BY id"
        ).fetchall()
        self.assertEqual(len(first["inserted"]), 2)
        self.assertEqual(second["inserted"], [])
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0][0], rows[1][0])
        self.assertTrue(all(row[0].startswith("zhilian-snapshot:") for row in rows))

    def test_zhilian_complete_snapshot_preserves_rows_outside_current_snapshot(self):
        duplicate_snapshot = [
            {"sender": "hr", "text": "Repeated", "message_id_is_native": False},
            {"sender": "hr", "text": "Repeated", "message_id_is_native": False},
        ]
        sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation, platform="zhilian",
            messages=duplicate_snapshot, history_complete=False,
        )
        result = sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation, platform="zhilian",
            messages=[{"sender": "hr", "text": "Repeated", "message_id_is_native": False}],
            history_complete=True,
        )
        # Even a complete platform-retention snapshot can be shorter than
        # locally retained history; never delete local-only messages.
        count = self.conn.execute("SELECT COUNT(*) FROM conv_messages").fetchone()[0]
        self.assertEqual(result["duplicates_removed"], 0)
        self.assertEqual(count, 2)

    def test_zhilian_complete_snapshot_preserves_unrepresented_legacy_message(self):
        sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation, platform="zhilian",
            messages=[{"sender": "hr", "text": "Earlier local message", "message_id": "old-local-id"}],
        )
        sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation, platform="zhilian",
            messages=[{"sender": "hr", "text": "Current platform message", "message_id": "current-id"}],
            history_complete=True,
        )
        rows = self.conn.execute("SELECT content FROM conv_messages ORDER BY id").fetchall()
        self.assertEqual([row[0] for row in rows], ["Earlier local message", "Current platform message"])

    def test_unknown_zhilian_direction_is_not_attributed_to_hr(self):
        sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation, platform="zhilian",
            messages=[{"sender": "unknown", "text": "Unclassified UI text", "message_id": "unknown-1"}],
        )
        sender_type = self.conn.execute("SELECT sender_type FROM conv_messages").fetchone()[0]
        self.assertEqual(sender_type, "unknown")

    def test_zhilian_external_thread_is_not_duplicated_into_another_job_card(self):
        first = sync_extracted_messages(
            self.conn,
            job={**self.job, "id": "job-one", "title": "Python Engineer"},
            conversation={**self.conversation, "external_conversation_id": "session-shared"},
            platform="zhilian",
            messages=[{"sender": "hr", "text": "原会话消息", "message_id": "hr-1"}],
        )
        second = sync_extracted_messages(
            self.conn,
            job={**self.job, "id": "job-two", "title": "Java Engineer"},
            conversation={**self.conversation, "external_conversation_id": "session-shared"},
            platform="zhilian",
            messages=[{"sender": "hr", "text": "不可复制的消息", "message_id": "hr-2"}],
        )

        self.assertEqual(first["status"], "synced")
        self.assertEqual(second["status"], "external_conversation_already_linked")
        self.assertEqual(second["linked_job_id"], "job-one")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM conv_conversations").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM conv_messages").fetchone()[0], 1)

    def test_zhilian_incomplete_snapshot_never_removes_generated_duplicates(self):
        duplicate_snapshot = [
            {"sender": "hr", "text": "Repeated", "message_id_is_native": False},
            {"sender": "hr", "text": "Repeated", "message_id_is_native": False},
        ]
        sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation, platform="zhilian",
            messages=duplicate_snapshot, history_complete=False,
        )
        result = sync_extracted_messages(
            self.conn, job=self.job, conversation=self.conversation, platform="zhilian",
            messages=[{"sender": "hr", "text": "Repeated", "message_id_is_native": False}],
            history_complete=False,
        )
        count = self.conn.execute("SELECT COUNT(*) FROM conv_messages").fetchone()[0]
        self.assertEqual(result["duplicates_removed"], 0)
        self.assertEqual(count, 2)

    def test_zhilian_masked_hr_name_from_platform_snapshot_is_preserved(self):
        masked_name = "\u5218\u5148\u751f"
        result = sync_extracted_messages(
            self.conn, job={**self.job, "hr_name": masked_name},
            conversation={**self.conversation, "hr_name": masked_name}, platform="zhilian",
            messages=[{"sender": "hr", "text": "Hello", "message_id": "native-1"}],
            history_complete=True,
        )
        self.assertEqual(result["conversation"]["hr_name"], masked_name)
        self.assertEqual(
            self.conn.execute("SELECT hr_name FROM conv_conversations").fetchone()[0],
            masked_name,
        )

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
