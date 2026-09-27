import io
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bosshunter.web import server


class ConversationReplyApiTests(unittest.TestCase):
    def setUp(self):
        self._old_base = server.BASE_DIR
        self._tmp = tempfile.TemporaryDirectory()
        server.set_base_dir(Path(self._tmp.name))

    def tearDown(self):
        server.set_base_dir(self._old_base)
        self._tmp.cleanup()

    def request(self, path, method="GET", body=None, *, add_default_key=True):
        status = {}

        def start_response(value, headers, exc_info=None):
            status["value"] = value

        if add_default_key and isinstance(body, dict) and path.endswith("/reply/send") and "message" in body and "idempotency_key" not in body:
            body = {**body, "idempotency_key": "test-reply-key-001"}
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else b""
        environ = {
            "REMOTE_ADDR": "127.0.0.1", "REQUEST_METHOD": method,
            "PATH_INFO": path.split("?", 1)[0],
            "QUERY_STRING": path.split("?", 1)[1] if "?" in path else "",
            "SERVER_NAME": "127.0.0.1", "SERVER_PORT": "8686", "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http", "wsgi.input": io.BytesIO(payload),
            "wsgi.errors": io.StringIO(), "wsgi.multithread": False,
            "wsgi.multiprocess": False, "wsgi.run_once": False,
            "CONTENT_LENGTH": str(len(payload)), "CONTENT_TYPE": "application/json",
        }
        response = server.app(environ, start_response)
        try:
            text = b"".join(
                chunk if isinstance(chunk, bytes) else chunk.encode() for chunk in response
            ).decode()
        finally:
            if getattr(response, "close", None):
                response.close()
        return status["value"], json.loads(text)

    def add_job_and_conversation(self, *, platform, conversation_id, external_conversation_id="external-1"):
        conn = server._get_web_db()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO jobs
                   (id, title, company, hr_name, hr_title, url, score, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("job-1", "Python Engineer", "Example Co", "刘先生", "HR", "https://www.example.com/job/1", 88, "ready"),
            )
            conn.commit()
        finally:
            conn.close()
        status, result = self.request(
            "/api/conversations", "POST",
            {
                "id": conversation_id, "platform": platform,
                "external_conversation_id": external_conversation_id, "hr_name": "刘先生",
                "company_id": "Example Co", "job_id": "job-1",
            },
        )
        self.assertTrue(status.startswith("201"), result)

    def test_boss_reply_requires_dom_message_match_before_persisting(self):
        self.add_job_and_conversation(platform="boss", conversation_id="boss-reply")
        row = {"target_id": "boss-tab", "hr_name": "刘先生", "company": "Example Co", "title": "Python Engineer", "conversation_id": "external-1"}
        with patch.object(server, "_opened_platform_rows", return_value=([{"target_id": "boss-tab", "url": "https://www.zhipin.com/web/geek/chat"}], [row])), \
             patch.object(server, "_open_boss_conversation_row", return_value={"status": "matched_chat_loaded"}), \
             patch.object(server, "_send_message_in_chat", return_value=True), \
             patch.object(server, "evaluate", side_effect=[json.dumps([]), json.dumps([{"sender": "me", "text": "感谢您的联系"}])]):
            status, result = self.request(
                "/api/conversations/boss-reply/reply/send", "POST", {"message": "感谢您的联系"}
            )
        self.assertTrue(status.startswith("200"), result)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["inserted"][0]["sender_type"], "user")
        self.assertEqual(result["inserted"][0]["is_sent"], 1)

    def test_boss_reply_does_not_persist_when_dom_verification_fails(self):
        self.add_job_and_conversation(platform="boss", conversation_id="boss-unverified")
        row = {"target_id": "boss-tab", "hr_name": "刘先生", "company": "Example Co", "title": "Python Engineer", "conversation_id": "external-1"}
        with patch.object(server, "_opened_platform_rows", return_value=([{"target_id": "boss-tab", "url": "https://www.zhipin.com/web/geek/chat"}], [row])), \
             patch.object(server, "_open_boss_conversation_row", return_value={"status": "matched_chat_loaded"}), \
             patch.object(server, "_send_message_in_chat", return_value=True), \
             patch.object(server, "evaluate", return_value=json.dumps([])):
            status, result = self.request(
                "/api/conversations/boss-unverified/reply/send", "POST", {"message": "未确认消息"}
            )
        self.assertTrue(status.startswith("502"), result)
        self.assertEqual(result["status"], "send_unknown")
        detail = self.request("/api/conversations/boss-unverified")[1]
        self.assertEqual(detail["messages"], [])

    def test_zhilian_reply_requires_verified_adapter_result(self):
        self.add_job_and_conversation(platform="zhilian", conversation_id="zhilian-reply")
        row = {"target_id": "zhilian-tab", "hr_name": "刘先生", "company": "Example Co", "title": "Python Engineer", "conversation_id": "external-1"}
        with patch.object(server, "_opened_platform_rows", return_value=([{"target_id": "zhilian-tab", "url": "https://i.zhaopin.com/im?refcode=4019"}], [row])), \
             patch.object(server, "_open_zhilian_conversation_row", return_value={"status": "matched_chat_loaded", "success": True}), \
             patch.object(server, "_fill_and_send_zhilian_message", return_value={"success": True, "verified": True, "verification": "dom_match"}):
            status, result = self.request(
                "/api/conversations/zhilian-reply/reply/send", "POST", {"message": "感谢您的沟通"}
            )
        self.assertTrue(status.startswith("200"), result)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["inserted"][0]["sender_type"], "user")

    def test_zhilian_unverified_reply_does_not_persist(self):
        self.add_job_and_conversation(platform="zhilian", conversation_id="zhilian-unverified")
        row = {"target_id": "zhilian-tab", "hr_name": "刘先生", "company": "Example Co", "title": "Python Engineer", "conversation_id": "external-1"}
        with patch.object(server, "_opened_platform_rows", return_value=([{"target_id": "zhilian-tab", "url": "https://i.zhaopin.com/im?refcode=4019"}], [row])), \
             patch.object(server, "_open_zhilian_conversation_row", return_value={"status": "matched_chat_loaded", "success": True}), \
             patch.object(server, "_fill_and_send_zhilian_message", return_value={"success": True, "verified": False}):
            status, result = self.request(
                "/api/conversations/zhilian-unverified/reply/send", "POST", {"message": "未确认智联消息"}
            )
        self.assertTrue(status.startswith("502"), result)
        self.assertEqual(result["status"], "send_unknown")
        self.assertEqual(self.request("/api/conversations/zhilian-unverified")[1]["messages"], [])

    def test_boss_equal_candidates_are_rejected_before_sending(self):
        self.add_job_and_conversation(platform="boss", conversation_id="boss-ambiguous", external_conversation_id="")
        rows = [
            {"target_id": "boss-tab-a", "hr_name": "刘先生", "company": "Example Co", "title": "Python Engineer", "conversation_id": "external-a"},
            {"target_id": "boss-tab-b", "hr_name": "刘先生", "company": "Example Co", "title": "Python Engineer", "conversation_id": "external-b"},
        ]
        with patch.object(server, "_opened_platform_rows", return_value=([
            {"target_id": "boss-tab-a", "url": "https://www.zhipin.com/web/geek/chat"},
            {"target_id": "boss-tab-b", "url": "https://www.zhipin.com/web/geek/chat"},
        ], rows)), \
             patch.object(server, "_send_message_in_chat") as send:
            status, result = self.request(
                "/api/conversations/boss-ambiguous/reply/send", "POST", {"message": "不能误发"}
            )
        self.assertTrue(status.startswith("409"), result)
        self.assertEqual(result["status"], "ambiguous")
        send.assert_not_called()
        self.assertEqual(self.request("/api/conversations/boss-ambiguous")[1]["messages"], [])

    def test_unsupported_platform_never_queries_browser(self):
        for platform in ("liepin", "51job"):
            conversation_id = f"{platform}-reply"
            self.add_job_and_conversation(platform=platform, conversation_id=conversation_id)
            with patch.object(server, "_opened_platform_rows") as opened, \
                 patch.object(server, "_send_message_in_chat") as send:
                status, result = self.request(
                    f"/api/conversations/{conversation_id}/reply/send", "POST", {"message": "人工回复"}
                )
            self.assertTrue(status.startswith("409"), result)
            self.assertEqual(result["status"], "unsupported_platform")
            opened.assert_not_called()
            send.assert_not_called()

    def test_invalid_message_and_missing_platform_are_side_effect_free(self):
        self.add_job_and_conversation(platform="boss", conversation_id="invalid-reply")
        with patch.object(server, "_opened_platform_rows") as opened:
            status, result = self.request(
                "/api/conversations/invalid-reply/reply/send", "POST", {"message": "   "}
            )
        self.assertTrue(status.startswith("400"), result)
        self.assertEqual(result["status"], "invalid_message")
        opened.assert_not_called()

        with patch.object(server, "_opened_platform_rows", return_value=([], [])) as opened:
            status, result = self.request(
                "/api/conversations/invalid-reply/reply/send", "POST", {"message": "平台未打开"}
            )
        self.assertTrue(status.startswith("503"), result)
        self.assertEqual(result["status"], "not_loaded")
        opened.assert_called_once_with("boss")
        self.assertEqual(self.request("/api/conversations/invalid-reply")[1]["messages"], [])

    def test_idempotency_key_is_required_and_validated(self):
        self.add_job_and_conversation(platform="zhilian", conversation_id="missing-key")
        status, result = self.request(
            "/api/conversations/missing-key/reply/send", "POST",
            {"message": "缺少幂等键"}, add_default_key=False,
        )
        self.assertTrue(status.startswith("400"), result)
        self.assertEqual(result["status"], "invalid_idempotency_key")

        status, result = self.request(
            "/api/conversations/missing-key/reply/send", "POST",
            {"message": "非法幂等键", "idempotency_key": "bad"}, add_default_key=False,
        )
        self.assertTrue(status.startswith("400"), result)
        self.assertEqual(result["status"], "invalid_idempotency_key")

    def test_sent_attempt_is_replayed_without_second_platform_send(self):
        self.add_job_and_conversation(platform="zhilian", conversation_id="replay-reply")
        row = {"target_id": "zhilian-tab", "hr_name": "刘先生", "company": "Example Co", "title": "Python Engineer", "conversation_id": "external-1"}
        body = {"message": "幂等回复", "idempotency_key": "replay-key-001"}
        with patch.object(server, "_opened_platform_rows", return_value=([{"target_id": "zhilian-tab", "url": "https://i.zhaopin.com/im?refcode=4019"}], [row])), \
             patch.object(server, "_open_zhilian_conversation_row", return_value={"status": "matched_chat_loaded", "success": True}), \
             patch.object(server, "_fill_and_send_zhilian_message", return_value={"success": True, "verified": True, "verification": "dom_match"}) as send:
            first_status, first = self.request("/api/conversations/replay-reply/reply/send", "POST", body)
            second_status, second = self.request("/api/conversations/replay-reply/reply/send", "POST", body)
        self.assertTrue(first_status.startswith("200"), first)
        self.assertTrue(second_status.startswith("200"), second)
        self.assertEqual(first["status"], "sent")
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(send.call_count, 1)
        self.assertEqual(len(self.request("/api/conversations/replay-reply")[1]["messages"]), 1)

    def test_same_idempotency_key_with_different_body_is_rejected(self):
        self.add_job_and_conversation(platform="zhilian", conversation_id="conflict-reply")
        row = {"target_id": "zhilian-tab", "hr_name": "刘先生", "company": "Example Co", "title": "Python Engineer", "conversation_id": "external-1"}
        with patch.object(server, "_opened_platform_rows", return_value=([{"target_id": "zhilian-tab", "url": "https://i.zhaopin.com/im?refcode=4019"}], [row])), \
             patch.object(server, "_open_zhilian_conversation_row", return_value={"status": "matched_chat_loaded", "success": True}), \
             patch.object(server, "_fill_and_send_zhilian_message", return_value={"success": True, "verified": True, "verification": "dom_match"}) as send:
            first_status, first = self.request(
                "/api/conversations/conflict-reply/reply/send", "POST",
                {"message": "第一段", "idempotency_key": "conflict-key-001"}, add_default_key=False,
            )
            second_status, second = self.request(
                "/api/conversations/conflict-reply/reply/send", "POST",
                {"message": "不同正文", "idempotency_key": "conflict-key-001"}, add_default_key=False,
            )
        self.assertTrue(first_status.startswith("200"), first)
        self.assertTrue(second_status.startswith("409"), second)
        self.assertEqual(second["status"], "idempotency_conflict")
        self.assertEqual(send.call_count, 1)

    def test_unknown_attempt_is_not_retried(self):
        self.add_job_and_conversation(platform="zhilian", conversation_id="unknown-reply")
        row = {"target_id": "zhilian-tab", "hr_name": "刘先生", "company": "Example Co", "title": "Python Engineer", "conversation_id": "external-1"}
        body = {"message": "可能已发送", "idempotency_key": "unknown-key-001"}
        with patch.object(server, "_opened_platform_rows", return_value=([{"target_id": "zhilian-tab", "url": "https://i.zhaopin.com/im?refcode=4019"}], [row])), \
             patch.object(server, "_open_zhilian_conversation_row", return_value={"status": "matched_chat_loaded", "success": True}), \
             patch.object(server, "_fill_and_send_zhilian_message", return_value={"success": True, "verified": False}) as send:
            first_status, first = self.request("/api/conversations/unknown-reply/reply/send", "POST", body)
            second_status, second = self.request("/api/conversations/unknown-reply/reply/send", "POST", body)
        self.assertTrue(first_status.startswith("502"), first)
        self.assertEqual(first["status"], "send_unknown")
        self.assertTrue(second_status.startswith("409"), second)
        self.assertEqual(second["status"], "unknown")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.request("/api/conversations/unknown-reply")[1]["messages"], [])

    def test_adapter_failure_is_not_sent_and_new_attempt_can_retry(self):
        self.add_job_and_conversation(platform="zhilian", conversation_id="retry-reply")
        row = {"target_id": "zhilian-tab", "hr_name": "刘先生", "company": "Example Co", "title": "Python Engineer", "conversation_id": "external-1"}
        body = {"message": "可重试回复", "idempotency_key": "retry-key-001"}
        with patch.object(server, "_opened_platform_rows", return_value=([{"target_id": "zhilian-tab", "url": "https://i.zhaopin.com/im?refcode=4019"}], [row])), \
             patch.object(server, "_open_zhilian_conversation_row", return_value={"status": "matched_chat_loaded", "success": True}), \
             patch.object(server, "_fill_and_send_zhilian_message", return_value={"success": False, "error": "input_not_found"}) as send:
            first_status, first = self.request("/api/conversations/retry-reply/reply/send", "POST", body)
        self.assertTrue(first_status.startswith("502"), first)
        self.assertEqual(first["status"], "send_not_verified")
        with patch.object(server, "_opened_platform_rows", return_value=([{"target_id": "zhilian-tab", "url": "https://i.zhaopin.com/im?refcode=4019"}], [row])), \
             patch.object(server, "_open_zhilian_conversation_row", return_value={"status": "matched_chat_loaded", "success": True}), \
             patch.object(server, "_fill_and_send_zhilian_message", return_value={"success": True, "verified": True, "verification": "dom_match"}) as retry_send:
            second_status, second = self.request("/api/conversations/retry-reply/reply/send", "POST", body)
        self.assertTrue(second_status.startswith("200"), second)
        self.assertEqual(second["status"], "sent")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(retry_send.call_count, 1)

    def test_boss_adapter_false_is_not_sent_not_unknown(self):
        self.add_job_and_conversation(platform="boss", conversation_id="boss-not-sent")
        row = {"target_id": "boss-tab", "hr_name": "刘先生", "company": "Example Co", "title": "Python Engineer", "conversation_id": "external-1"}
        with patch.object(server, "_opened_platform_rows", return_value=([{"target_id": "boss-tab", "url": "https://www.zhipin.com/web/geek/chat"}], [row])), \
             patch.object(server, "_open_boss_conversation_row", return_value={"status": "matched_chat_loaded"}), \
             patch.object(server, "_send_message_in_chat", return_value=False):
            status, result = self.request("/api/conversations/boss-not-sent/reply/send", "POST", {"message": "未发送"})
        self.assertTrue(status.startswith("502"), result)
        self.assertEqual(result["status"], "send_not_verified")

    def test_blocked_conversation_does_not_query_browser(self):
        self.add_job_and_conversation(platform="boss", conversation_id="blocked-reply")
        conn = server._get_web_db()
        try:
            conn.execute("UPDATE conv_conversations SET status = 'closed' WHERE id = ?", ("blocked-reply",))
            conn.commit()
        finally:
            conn.close()
        with patch.object(server, "_opened_platform_rows") as opened:
            status, result = self.request("/api/conversations/blocked-reply/reply/send", "POST", {"message": "已关闭"})
        self.assertTrue(status.startswith("409"), result)
        self.assertEqual(result["status"], "conversation_not_sendable")
        opened.assert_not_called()

    def test_pending_attempt_does_not_query_browser(self):
        self.add_job_and_conversation(platform="boss", conversation_id="pending-reply")
        key = "pending-key-001"
        message = "挂起中的回复"
        conn = server._get_web_db()
        try:
            repo = server.ConversationRepository(conn)
            repo.create_send_attempt(
                user_id="default", conversation_id="pending-reply", idempotency_key=key,
                message_hash=hashlib.sha256(message.encode("utf-8")).hexdigest(), platform="boss",
            )
        finally:
            conn.close()
        with patch.object(server, "_opened_platform_rows") as opened:
            status, result = self.request("/api/conversations/pending-reply/reply/send", "POST", {"message": message, "idempotency_key": key}, add_default_key=False)
        self.assertTrue(status.startswith("409"), result)
        self.assertEqual(result["status"], "pending")
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
