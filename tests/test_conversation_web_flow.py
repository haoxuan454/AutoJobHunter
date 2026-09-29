import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bosshunter.web import server


class ConversationWebFlowTests(unittest.TestCase):
    def setUp(self):
        self._old_base = server.BASE_DIR
        self._tmp = tempfile.TemporaryDirectory()
        server.set_base_dir(Path(self._tmp.name))

    def tearDown(self):
        server.set_base_dir(self._old_base)
        self._tmp.cleanup()

    def request(self, path, method="GET", body=None, multipart=None):
        status = {}

        def start_response(value, headers, exc_info=None):
            status["value"] = value

        if multipart is not None:
            boundary = "----BossHunterKnowledgeTest"
            filename, content, content_type = multipart
            payload = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
                + content
                + f"\r\n--{boundary}--\r\n".encode()
            )
            content_type_header = f"multipart/form-data; boundary={boundary}"
        else:
            payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else b""
            content_type_header = "application/json"
        environ = {
            "REMOTE_ADDR": "127.0.0.1", "REQUEST_METHOD": method,
            "PATH_INFO": path.split("?", 1)[0], "QUERY_STRING": path.split("?", 1)[1] if "?" in path else "",
            "SERVER_NAME": "127.0.0.1", "SERVER_PORT": "8686", "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http", "wsgi.input": io.BytesIO(payload), "wsgi.errors": io.StringIO(),
            "wsgi.multithread": False, "wsgi.multiprocess": False, "wsgi.run_once": False,
            "CONTENT_LENGTH": str(len(payload)), "CONTENT_TYPE": content_type_header,
        }
        response = server.app(environ, start_response)
        try:
            text = b"".join(chunk if isinstance(chunk, bytes) else chunk.encode() for chunk in response).decode()
        finally:
            if getattr(response, "close", None):
                response.close()
        return status["value"], json.loads(text)

    def test_opened_boss_rows_do_not_require_zhilian_scan_metadata(self):
        with patch.object(server, "_boss_im_targets", return_value=[
            {"target_id": "boss-tab", "url": "https://www.zhipin.com/web/geek/chat"},
        ]), patch.object(server, "evaluate", return_value=json.dumps([
            {"hr_name": "Recruiter", "company": "Example Co", "conversation_id": "boss-1"},
        ])):
            targets, rows = server._opened_platform_rows("boss")

        self.assertEqual(targets[0]["target_id"], "boss-tab")
        self.assertEqual(rows[0]["conversation_id"], "boss-1")
        self.assertNotIn("_scan_complete", rows[0])

    def test_zhilian_rows_with_same_visible_identity_are_deduplicated_across_tabs(self):
        row_a = {
            "target_id": "zhilian-tab-a",
            "hr_name": "HR",
            "company": "Example Co",
            "title": "Python Engineer",
            "preview": "不会强制晚班",
            "time": "19:07",
        }
        row_b = {**row_a, "target_id": "zhilian-tab-b"}

        self.assertEqual(
            server._conversation_row_identity(row_a, platform="zhilian"),
            server._conversation_row_identity(row_b, platform="zhilian"),
        )

    def test_zhilian_rows_with_different_visible_preview_remain_distinct(self):
        row_a = {
            "target_id": "zhilian-tab-a",
            "hr_name": "HR",
            "company": "Example Co",
            "title": "Python Engineer",
            "preview": "不会强制晚班",
            "time": "19:07",
        }
        row_b = {**row_a, "target_id": "zhilian-tab-b", "preview": "欢迎添加微信"}

        self.assertNotEqual(
            server._conversation_row_identity(row_a, platform="zhilian"),
            server._conversation_row_identity(row_b, platform="zhilian"),
        )

    def test_boss_rows_without_external_id_keep_tab_scoped_identity(self):
        row_a = {
            "target_id": "boss-tab-a",
            "hr_name": "HR",
            "company": "Example Co",
            "title": "Python Engineer",
        }
        row_b = {**row_a, "target_id": "boss-tab-b"}

        self.assertNotEqual(
            server._conversation_row_identity(row_a, platform="boss"),
            server._conversation_row_identity(row_b, platform="boss"),
        )

    def test_zhilian_sync_identity_requires_matching_job_title(self):
        local = {
            "hr_name": "刘先生", "job_company": "Example Co", "job_title": "Python Engineer",
        }
        same_hr_different_job = {
            "hr_name": "刘先生", "company": "Example Co", "title": "Java Engineer",
        }
        exact_job = {**same_hr_different_job, "title": "Python Engineer"}

        self.assertEqual(server._zhilian_identity_score(local, same_hr_different_job), 0)
        self.assertGreater(server._zhilian_identity_score(local, exact_job), 0)

    def test_knowledge_to_conversation_salary_pause_and_draft_gate(self):
        status, uploaded = self.request(
            "/api/knowledge/documents/upload", "POST",
            multipart=("..\\experience.md", b"# Python project\nBuilt a Python Flask API", "text/markdown"),
        )
        self.assertTrue(status.startswith("200"), uploaded)
        self.assertEqual(uploaded["facts_created"], 1)
        fact_id = uploaded["document"]["id"]
        status, confirmed = self.request(
            f"/api/knowledge/facts/{fact_id}", "PATCH",
            {"fact_status": "confirmed", "public_allowed": True},
        )
        self.assertTrue(status.startswith("200"), confirmed)
        self.assertEqual(self.request("/api/knowledge/search?q=Python")[1]["facts"][0]["id"], fact_id)

        status, created = self.request(
            "/api/conversations", "POST",
            {"id": "c1", "platform": "test", "external_conversation_id": "x1", "hr_name": "HR"},
        )
        self.assertTrue(status.startswith("201"), created)
        status, inserted = self.request(
            "/api/conversations/c1/messages", "POST",
            {"sender_type": "hr", "content": "你之前用 Python 做过什么？", "platform_message_id": "m1"},
        )
        self.assertTrue(status.startswith("200"), inserted)
        self.assertEqual(len(inserted["inserted"]), 1)
        status, duplicate = self.request(
            "/api/conversations/c1/messages", "POST",
            {"sender_type": "hr", "content": "你之前用 Python 做过什么？", "platform_message_id": "m1"},
        )
        self.assertTrue(status.startswith("200"), duplicate)
        self.assertEqual(duplicate["inserted"], [])
        status, draft = self.request("/api/conversations/c1/draft", "POST", {})
        self.assertTrue(status.startswith("200"), draft)
        self.assertFalse(draft["sent"])
        detail = self.request("/api/conversations/c1")[1]
        self.assertEqual(len(detail["drafts"]), 1)

        status, paused = self.request(
            "/api/conversations/c1/messages", "POST",
            {"sender_type": "hr", "content": "薪资范围是多少？", "platform_message_id": "m2"},
        )
        self.assertTrue(status.startswith("200"), paused)
        self.assertEqual(paused["conversation"]["status"], "paused_salary")
        status, blocked = self.request("/api/conversations/c1/draft", "POST", {})
        self.assertTrue(status.startswith("409"), blocked)

    def test_draft_delete_is_scoped_to_its_conversation(self):
        for conversation_id in ("draft-owner-a", "draft-owner-b"):
            status, created = self.request("/api/conversations", "POST", {
                "id": conversation_id, "platform": "boss", "hr_name": "HR",
            })
            self.assertTrue(status.startswith("201"), created)
        conn = server._get_web_db()
        try:
            repo = server.ConversationRepository(conn)
            owned_draft = repo.save_draft("draft-owner-a", "A conversation draft")
        finally:
            conn.close()

        status, wrong_owner = self.request(
            f"/api/conversations/draft-owner-b/draft/{owned_draft['id']}", "DELETE",
        )
        self.assertTrue(status.startswith("404"), wrong_owner)
        self.assertEqual(len(self.request("/api/conversations/draft-owner-a")[1]["drafts"]), 1)

        status, deleted = self.request(
            f"/api/conversations/draft-owner-a/draft/{owned_draft['id']}", "DELETE",
        )
        self.assertTrue(status.startswith("200"), deleted)
        self.assertEqual(self.request("/api/conversations/draft-owner-a")[1]["drafts"], [])

        status, missing = self.request(
            f"/api/conversations/draft-owner-a/draft/{owned_draft['id']}", "DELETE",
        )
        self.assertTrue(status.startswith("404"), missing)

    def test_draft_delete_rejects_wrong_user_at_repository_boundary(self):
        self.request("/api/conversations", "POST", {"id": "private-draft", "platform": "boss"})
        conn = server._get_web_db()
        try:
            repo = server.ConversationRepository(conn)
            draft = repo.save_draft("private-draft", "Private draft")
            self.assertFalse(repo.delete_draft("private-draft", draft["id"], user_id="another-user"))
            self.assertEqual(len(repo.list_drafts("private-draft")), 1)
        finally:
            conn.close()

    def test_conversation_detail_clears_unread_after_hr_message_sync(self):
        status, created = self.request("/api/conversations", "POST", {
            "id": "zhilian:delivery:job-unread", "platform": "zhilian",
            "job_id": "zhilian:job-unread", "hr_name": "刘先生", "company_id": "Example Co",
        })
        self.assertTrue(status.startswith("201"), created)

        status, added = self.request("/api/conversations/zhilian:delivery:job-unread/messages", "POST", {
            "sender_type": "hr", "content": "New HR message", "platform_message_id": "zhilian-message-1",
        })
        self.assertTrue(status.startswith("200"), added)
        self.assertEqual(len(added["inserted"]), 1)

        listed = self.request("/api/conversations")[1]
        card = next(item for item in listed["conversations"] if item["id"] == "zhilian:delivery:job-unread")
        self.assertEqual(card["unread_count"], 1)
        self.assertTrue(card["has_unread"])

        detail_status, detail = self.request("/api/conversations/zhilian:delivery:job-unread")
        self.assertTrue(detail_status.startswith("200"), detail)
        self.assertEqual(len(detail["messages"]), 1)
        self.assertEqual(detail["conversation"]["unread_count"], 0)
        self.assertFalse(detail["conversation"]["has_unread"])

    def test_notification_settings_scheduler_and_analytics_http_flow(self):
        status, saved = self.request(
            "/api/notifications/email", "POST",
            {"email": {"enabled": False, "auto_send": False, "smtp_host": "smtp.example.com", "to_email": "me@example.com", "password": "secret"}},
        )
        self.assertTrue(status.startswith("200"), saved)
        self.assertTrue(saved["email"]["password_set"])
        self.assertNotIn("password", saved["email"])
        self.request("/api/conversations", "POST", {"id": "c2", "platform": "boss", "job_id": "job-c2", "hr_name": "HR"})
        status, message = self.request(
            "/api/conversations/c2/messages", "POST",
            {"sender_type": "hr", "content": "我们想了解你的薪资期望", "platform_message_id": "salary-1"},
        )
        self.assertTrue(status.startswith("200"), message)
        self.assertEqual(message["notification"]["status"], "pending")
        self.assertEqual(len(self.request("/api/notifications/outbox")[1]["notifications"]), 1)
        analytics = self.request("/api/conversations/analytics")[1]
        self.assertEqual(analytics["conversations_total"], 1)
        self.assertEqual(analytics["salary_paused"], 1)
        self.assertEqual(analytics["daily_trend"][-1]["incoming_messages"], 1)
        self.assertEqual(self.request("/api/conversations/scheduler/next")[1]["candidate"], None)

    def test_configured_model_generates_contextual_draft_but_never_sends(self):
        status, uploaded = self.request(
            "/api/knowledge/documents/upload", "POST",
            multipart=("experience.md", b"# Python project\nBuilt a Flask API", "text/markdown"),
        )
        fact_id = uploaded["document"]["id"]
        self.request(f"/api/knowledge/facts/{fact_id}", "PATCH", {"fact_status": "confirmed", "public_allowed": True})
        self.request("/api/conversations", "POST", {"id": "model-c", "platform": "test", "hr_name": "HR"})
        self.request("/api/conversations/model-c/messages", "POST", {"sender_type": "hr", "content": "你用 Python 做过什么？", "platform_message_id": "m-model"})
        with patch.object(server, "load_config", return_value={"ai": {"api_key": "configured", "provider": "openai_compatible", "base_url": "https://example.invalid", "model": "test"}}), \
             patch.object(server, "call_anthropic_text", return_value="我之前用 Python 和 Flask 做过接口项目。") as call:
            status, result = self.request("/api/conversations/model-c/draft", "POST", {})
        self.assertTrue(status.startswith("200"), result)
        self.assertEqual(result["generation_mode"], "configured_model")
        self.assertFalse(result["sent"])
        call.assert_called_once()

    def test_conversation_center_sort_resume_and_local_delete_flow(self):
        self.request("/api/conversations", "POST", {"id": "c-delete", "platform": "boss", "external_conversation_id": "ext-delete", "company_id": "公司A", "job_id": "岗位A", "hr_name": "HR A"})
        self.request("/api/conversations/c-delete/messages", "POST", {"sender_type": "hr", "content": "我们聊一下薪资", "platform_message_id": "salary-delete"})
        status, listed = self.request("/api/conversations?sort=frequency")
        self.assertTrue(status.startswith("200"), listed)
        self.assertEqual(listed["conversations"][0]["round_count"], 1)
        self.assertEqual(listed["conversations"][0]["platform"], "boss")

        status, blocked = self.request("/api/conversations/c-delete", "DELETE", {})
        self.assertTrue(status.startswith("400"), blocked)
        status, resumed = self.request("/api/conversations/c-delete/status", "POST", {"status": "active", "reason": "用户人工恢复"})
        self.assertTrue(status.startswith("200"), resumed)
        self.assertEqual(resumed["conversation"]["status"], "active")
        status, deleted = self.request("/api/conversations/c-delete", "DELETE", {"confirmation": "DELETE_LOCAL_CONVERSATION"})
        self.assertTrue(status.startswith("200"), deleted)
        self.assertTrue(deleted["platform_untouched"])
        self.assertTrue(self.request("/api/conversations/c-delete")[0].startswith("404"))

    def test_liepin_conversation_sync_is_explicitly_unsupported(self):
        from unittest.mock import patch
        self.request("/api/conversations", "POST", {
            "id": "ambiguous", "platform": "liepin", "external_conversation_id": "same",
            "hr_name": "王HR", "company_id": "示例科技", "job_id": "job-1",
        })
        rows = [
            {"hr_name": "王HR", "company_role": "示例科技", "title": "数据分析师", "conversation_id": "same"},
            {"hr_name": "王HR", "company_role": "示例科技", "title": "数据分析师", "conversation_id": "same"},
        ]
        with patch.object(server, "_liepin_im_targets", return_value=[{"target_id": "im", "url": "https://c.liepin.com/im"}]), \
             patch.object(server, "_liepin_conversation_list_snapshot", return_value={"rows": rows, "success": True}):
            status, result = self.request("/api/conversations/ambiguous/sync", "POST")
        self.assertTrue(status.startswith("200"), result)
        self.assertEqual(result["status"], "unsupported_platform")
        self.assertEqual(result["platform"], "liepin")
        detail = self.request("/api/conversations/ambiguous")[1]
        self.assertEqual(detail["messages"], [])

    def test_zhilian_card_sync_reports_bounded_sidebar_scan_incomplete(self):
        self.request("/api/conversations", "POST", {
            "id": "zhilian-scan-incomplete", "platform": "zhilian", "job_id": "job-zhilian-1",
            "hr_name": "Masked HR", "company_id": "Example Co", "hr_title": "Python Engineer",
        })
        with patch.object(server, "_zhilian_im_targets", return_value=[
            {"target_id": "zhilian-im", "url": "https://i.zhaopin.com/im?refcode=4019"},
        ]), patch.object(server, "_scan_zhilian_conversation_list", return_value={
            "success": True, "complete": False, "scroll_rounds": 8, "loaded_count": 24,
            "rows": [{"hr_name": "Masked HR", "company": "Example Co", "title": "Python Engineer"}],
        }), patch.object(server, "_zhilian_identity_score", return_value=90), \
             patch.object(server, "_sync_platform_target") as sync_target:
            status, result = self.request("/api/conversations/zhilian-scan-incomplete/sync", "POST")

        self.assertTrue(status.startswith("200"), result)
        self.assertEqual(result["status"], "scan_incomplete")
        self.assertTrue(result["candidate_found"])
        self.assertFalse(result["scan_complete"])
        self.assertEqual(result["scan_rounds"], 8)
        sync_target.assert_not_called()
        self.assertEqual(self.request("/api/conversations/zhilian-scan-incomplete")[1]["messages"], [])

        status, first = self.request("/api/assistant-lab/session")
        self.assertTrue(status.startswith("200"), first)
        self.assertEqual(first["session"]["id"], "assistant-lab:default")
        status, sent = self.request("/api/assistant-lab/messages", "POST", {"content": "你之前做过哪些 Python 项目？"})
        self.assertTrue(status.startswith("200"), sent)
        status, sent_again = self.request("/api/assistant-lab/messages", "POST", {"session_id": "old-uuid-that-must-be-ignored", "content": "细说一下具体负责什么？"})
        self.assertTrue(status.startswith("200"), sent_again)
        self.assertEqual(sent_again["session"]["id"], "assistant-lab:default")
        status, listed = self.request("/api/conversations?sort=frequency")
        self.assertTrue(status.startswith("200"), listed)
        lab = [item for item in listed["conversations"] if item["platform"] == "assistant_lab"]
        self.assertEqual(len(lab), 1)
        self.assertEqual(lab[0]["round_count"], 2)
        detail_status, detail = self.request("/api/conversations/assistant-lab%3Aassistant-lab%3Adefault")
        self.assertTrue(detail_status.startswith("200"), detail)
        self.assertEqual(len(detail["messages"]), 4)
    def test_batch_sync_rejects_boss_history_card_without_job_identity(self):
        self.request('/api/conversations', 'POST', {
            'id': 'boss-history', 'platform': 'boss', 'job_id': 'job-history',
            'company_id': 'Example Co', 'hr_name': '',
        })
        synced_payload = {
            'status': 'synced', 'message_count': 1, 'platform_message_count': 2,
            'synced': {'inserted': [], 'conversation': {'hr_name': 'Recruiter'}},
        }
        with patch.object(server, '_opened_platform_rows', return_value=(
            [{'target_id': 'boss-tab', 'url': 'https://www.zhipin.com/web/geek/chat'}],
            [{'target_id': 'boss-tab', 'hr_name': 'Recruiter', 'company': 'Example Co'}],
        )), patch.object(server, '_sync_platform_target', return_value=synced_payload) as sync_target:
            status, result = self.request('/api/conversations/sync', 'POST', {'platforms': ['boss']})

        self.assertTrue(status.startswith('200'), result)
        self.assertFalse(result['success'])
        self.assertFalse(result['complete'])
        self.assertFalse(result['partial'])
        self.assertEqual(result['status'], 'not_synced')
        self.assertEqual(result['results'][0]['status'], 'not_loaded')
        self.assertEqual(result['results'][0]['message_count'], 0)
        self.assertEqual(result['results'][0]['inserted'], 0)
        sync_target.assert_not_called()

    def test_boss_sync_persists_only_a_concrete_validated_conversation_url(self):
        conn = server._get_web_db()
        server.ConversationRepository(conn)
        conn.execute(
            "INSERT INTO jobs (id, title, company, url, score, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("job-boss", "Python Engineer", "Example Co", "https://www.zhipin.com/job_detail/123.html", 82, "sent"),
        )
        conn.execute("INSERT INTO history (job_id, action) VALUES (?, 'sent')", ("job-boss",))
        conn.commit()
        target = {"target_id": "boss-tab", "url": "https://www.zhipin.com/web/geek/chat"}
        row = {
            "hr_name": "Recruiter", "company": "Example Co", "title": "Python Engineer",
            "job_id": "job-boss", "job_url": "https://www.zhipin.com/job_detail/123.html",
        }
        with patch.object(server, "_open_boss_conversation_row", return_value={
            "status": "matched_chat_loaded", "row": {
                "hr_name": "Recruiter", "company": "Example Co", "title": "Python Engineer",
                "conversation_id": "thread-123",
                "conversation_url": "https://www.zhipin.com/web/geek/chat?conversationId=thread-123",
            },
        }), patch.object(server, "evaluate", return_value=json.dumps([
            {"sender": "hr", "text": "Hello", "message_id": "m-1"},
        ])):
            try:
                result = server._sync_platform_target(
                    conn, platform="boss", target=target, row=row,
                    base_dir=server.BASE_DIR, config={},
                )
                self.assertEqual(
                    result["synced"]["conversation"]["conversation_url"],
                    "https://www.zhipin.com/web/geek/chat?conversationId=thread-123",
                )
            finally:
                conn.close()

    def test_boss_sync_does_not_promote_generic_chat_entry_to_conversation_link(self):
        conn = server._get_web_db()
        server.ConversationRepository(conn)
        conn.execute(
            "INSERT INTO jobs (id, title, company, url, score, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("job-boss", "Python Engineer", "Example Co", "https://www.zhipin.com/job_detail/123.html", 82, "sent"),
        )
        conn.execute("INSERT INTO history (job_id, action) VALUES (?, 'sent')", ("job-boss",))
        conn.commit()
        target_url = "https://www.zhipin.com/web/geek/chat"
        row = {
            "hr_name": "Recruiter", "company": "Example Co", "title": "Python Engineer",
            "job_id": "job-boss", "job_url": "https://www.zhipin.com/job_detail/123.html",
            "conversation_url": target_url,
        }
        with patch.object(server, "_open_boss_conversation_row", return_value={
            "status": "matched_chat_loaded", "row": {"hr_name": "Recruiter", "conversation_url": target_url},
        }), patch.object(server, "evaluate", return_value=json.dumps([
            {"sender": "hr", "text": "Hello", "message_id": "m-2"},
        ])):
            try:
                result = server._sync_platform_target(
                    conn, platform="boss", target={"target_id": "boss-tab", "url": target_url}, row=row,
                    base_dir=server.BASE_DIR, config={},
                )
                self.assertIsNone(result["synced"]["conversation"]["conversation_url"])
            finally:
                conn.close()

    def test_batch_sync_does_not_reuse_one_missing_id_row_for_two_jobs(self):
        for conversation_id, job_id in (('boss-a', 'job-a'), ('boss-b', 'job-b')):
            self.request('/api/conversations', 'POST', {
                'id': conversation_id, 'platform': 'boss', 'job_id': job_id,
                'company_id': 'Example Co', 'hr_name': '',
            })
        with patch.object(server, '_opened_platform_rows', return_value=(
            [{'target_id': 'boss-tab', 'url': 'https://www.zhipin.com/web/geek/chat'}],
            [{'target_id': 'boss-tab', 'hr_name': 'Recruiter', 'company': 'Example Co'}],
        )), patch.object(server, '_sync_platform_target') as sync_target:
            status, result = self.request('/api/conversations/sync', 'POST', {'platforms': ['boss']})

        self.assertTrue(status.startswith('200'), result)
        by_id = {item['conversation_id']: item for item in result['results']}
        self.assertEqual(by_id['boss-a']['status'], 'not_loaded')
        self.assertEqual(by_id['boss-b']['status'], 'not_loaded')
        sync_target.assert_not_called()

    def test_batch_sync_reports_loaded_contacts_without_active_chat(self):
        with patch.object(server, "_opened_platform_rows") as opened:
            status, result = self.request(
                "/api/conversations/sync", "POST", {"platforms": ["boss"]}
            )
        self.assertTrue(status.startswith("200"), result)
        self.assertEqual(result["results"][0]["status"], "no_active_conversation")
        self.assertFalse(result["success"])
        self.assertFalse(result["complete"])
        self.assertFalse(result["partial"])
        self.assertEqual(result["status"], "not_synced")
        self.assertEqual(result["results"][0]["updated"], 0)
        self.assertEqual(self.request("/api/conversations")[1]["conversations"], [])
        opened.assert_not_called()

    def test_batch_sync_reports_partial_per_card_results(self):
        for conversation_id, job_id, hr_name in (
            ("boss-a", "job-a", "Recruiter A"),
            ("boss-b", "job-b", "Recruiter B"),
        ):
            self.request("/api/conversations", "POST", {
                "id": conversation_id, "platform": "boss", "job_id": job_id,
                "company_id": "Example Co", "hr_name": hr_name,
            })
        synced_payload = {
            "status": "synced", "message_count": 1, "platform_message_count": 1,
            "synced": {"inserted": [], "conversation": {"hr_name": "Recruiter A"}},
        }

        def score(local, row):
            return 10 if local["id"] == "boss-a" and row.get("hr_name") == "Recruiter A" else 0

        with patch.object(server, "_opened_platform_rows", return_value=(
            [{"target_id": "boss-tab", "url": "https://www.zhipin.com/web/geek/chat"}],
            [{"target_id": "boss-tab", "hr_name": "Recruiter A", "company": "Example Co"}],
        )), patch.object(server, "_conversation_identity_score", side_effect=score), \
             patch.object(server, "_sync_platform_target", return_value=synced_payload) as sync_target:
            status, result = self.request("/api/conversations/sync", "POST", {"platforms": ["boss"]})

        self.assertTrue(status.startswith("200"), result)
        self.assertFalse(result["success"])
        self.assertFalse(result["complete"])
        self.assertTrue(result["partial"])
        self.assertEqual(result["status"], "partial")
        by_id = {item["conversation_id"]: item for item in result["results"]}
        self.assertEqual(by_id["boss-a"]["status"], "synced")
        self.assertEqual(by_id["boss-b"]["status"], "not_loaded")
        self.assertEqual(sync_target.call_count, 1)

    def test_batch_sync_collapses_same_zhilian_row_repeated_in_multiple_tabs(self):
        self.request("/api/conversations", "POST", {
            "id": "zhilian-duplicate-tabs", "platform": "zhilian",
            "job_id": "job-zhilian-duplicate", "company_id": "Example Co",
            "hr_name": "Recruiter", "job_title": "Python Engineer",
        })
        synced_payload = {
            "status": "synced", "message_count": 1,
            "platform_message_count": 1, "synced": {"inserted": []},
        }
        row = {
            "hr_name": "Recruiter", "company": "Example Co",
            "title": "Python Engineer", "preview": "已读",
            "time": "19:07", "session_id": "",
        }
        with patch.object(server, "_opened_platform_rows", return_value=(
            [
                {"target_id": "zhilian-tab-a", "url": "https://i.zhaopin.com/im"},
                {"target_id": "zhilian-tab-b", "url": "https://i.zhaopin.com/im"},
            ],
            [{**row, "target_id": "zhilian-tab-a"}, {**row, "target_id": "zhilian-tab-b"}],
        )), patch.object(server, "_zhilian_identity_score", return_value=90), \
             patch.object(server, "_sync_platform_target", return_value=synced_payload) as sync_target:
            status, result = self.request(
                "/api/conversations/sync", "POST", {"platforms": ["zhilian"]}
            )

        self.assertTrue(status.startswith("200"), result)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["results"][0]["status"], "synced")
        sync_target.assert_called_once()

    def test_batch_sync_persists_hr_unread_marker_for_the_card(self):
        """Global sync must reuse card sync persistence, including the red dot."""
        conn = server._get_web_db()
        conn.execute(
            "INSERT INTO jobs (id, title, company, url, score, status) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "job-zhilian-unread",
                "Python Engineer",
                "Example Co",
                "https://i.zhaopin.com/job/zhilian-unread",
                88,
                "sent",
            ),
        )
        conn.execute("INSERT INTO history (job_id, action) VALUES (?, 'sent')", ("job-zhilian-unread",))
        conn.commit()
        conn.close()
        self.request('/api/conversations', 'POST', {
            'id': 'zhilian-unread-batch', 'platform': 'zhilian', 'job_id': 'job-zhilian-unread',
            'company_id': 'Example Co', 'hr_name': 'Recruiter',
        })

        def sync_one(conn, **kwargs):
            synced = server.sync_extracted_messages(
                conn,
                job={
                    'id': 'job-zhilian-unread', 'company': 'Example Co',
                    'title': 'Python Engineer', 'score': 88,
                },
                conversation={
                    'hr_name': 'Recruiter', 'company': 'Example Co',
                    'title': 'Python Engineer', 'external_conversation_id': 'zhilian-thread-1',
                },
                platform='zhilian',
                messages=[{
                    'sender': 'hr', 'text': '请介绍一下你的 Python 项目',
                    'message_id': 'zhilian-hr-1',
                }],
                local_conversation_id=kwargs['row']['local_conversation_id'],
                base_dir=server.BASE_DIR,
                config={},
            )
            return {
                'status': 'synced',
                'message_count': 1,
                'platform_message_count': 1,
                'synced': synced,
            }

        with patch.object(server, '_opened_platform_rows', return_value=(
            [{'target_id': 'zhilian-tab', 'url': 'https://i.zhaopin.com/im?refcode=4019'}],
            [{'target_id': 'zhilian-tab', 'hr_name': 'Recruiter', 'company': 'Example Co',
              'title': 'Python Engineer', 'session_id': 'zhilian-thread-1'}],
        )), patch.object(server, '_sync_platform_target', side_effect=sync_one):
            status, result = self.request('/api/conversations/sync', 'POST', {'platforms': ['zhilian']})

        self.assertTrue(status.startswith('200'), result)
        self.assertEqual(result['results'][0]['status'], 'synced')
        self.assertEqual(result['results'][0]['inserted'], 1)
        card = next(item for item in self.request('/api/conversations')[1]['conversations']
                    if item['id'] == 'zhilian-unread-batch')
        self.assertEqual(card['unread_count'], 1)
        self.assertTrue(card['has_unread'])
        self.assertNotIn('last_sync_attempt_at', card)

    def test_legacy_reply_route_is_disabled_without_touching_platform(self):
        self.request("/api/conversations", "POST", {
            "id": "legacy-reply", "platform": "boss", "job_id": "job-legacy", "hr_name": "HR",
        })
        with patch.object(server, "_opened_platform_rows") as opened, \
                patch.object(server, "_send_message_in_chat") as send:
            status, result = self.request(
                "/api/conversations/legacy-reply/reply/send-legacy", "POST", {"message": "must not send"}
            )
        self.assertTrue(status.startswith("410"), result)
        self.assertEqual(result["status"], "deprecated")
        self.assertFalse(result["send_enabled"])
        opened.assert_not_called()
        send.assert_not_called()

if __name__ == "__main__":
    unittest.main()
