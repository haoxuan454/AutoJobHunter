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

    def test_notification_settings_scheduler_and_analytics_http_flow(self):
        status, saved = self.request(
            "/api/notifications/email", "POST",
            {"email": {"enabled": False, "auto_send": False, "smtp_host": "smtp.example.com", "to_email": "me@example.com", "password": "secret"}},
        )
        self.assertTrue(status.startswith("200"), saved)
        self.assertTrue(saved["email"]["password_set"])
        self.assertNotIn("password", saved["email"])
        self.request("/api/conversations", "POST", {"id": "c2", "platform": "test", "hr_name": "HR"})
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


if __name__ == "__main__":
    unittest.main()
