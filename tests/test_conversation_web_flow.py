import io
import json
import tempfile
import unittest
from pathlib import Path

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

        status, paused = self.request(
            "/api/conversations/c1/messages", "POST",
            {"sender_type": "hr", "content": "薪资范围是多少？", "platform_message_id": "m2"},
        )
        self.assertTrue(status.startswith("200"), paused)
        self.assertEqual(paused["conversation"]["status"], "paused_salary")
        status, blocked = self.request("/api/conversations/c1/draft", "POST", {})
        self.assertTrue(status.startswith("409"), blocked)


if __name__ == "__main__":
    unittest.main()
