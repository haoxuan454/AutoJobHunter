import io
import json
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from bosshunter.db import get_db, insert_job, update_job_status
from bosshunter.web import server


class PlatformDeliveryGuardTests(TestCase):
    @staticmethod
    def _request(path: str, body: dict | None = None):
        raw = json.dumps(body or {}).encode("utf-8")
        result = {}

        def start_response(status, headers, exc_info=None):
            result["status"] = status
            result["headers"] = dict(headers)

        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(raw)),
            "CONTENT_TYPE": "application/json",
            "SERVER_NAME": "127.0.0.1",
            "SERVER_PORT": "8686",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": io.BytesIO(raw),
            "wsgi.errors": io.StringIO(),
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }
        payload = b"".join(
            chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
            for chunk in server.app(environ, start_response)
        ).decode("utf-8")
        return result["status"], json.loads(payload)

    def test_zhilian_requires_default_greeting_ack_but_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            job_id = "zhilian:zl-1"
            db = get_db(base_dir / "data" / "bosshunter.db")
            try:
                insert_job(db, {
                    "id": job_id,
                    "title": "采集岗位",
                    "company": "示例公司",
                    "jd": "JD",
                    "url": "https://www.zhaopin.com/jobdetail/zl-1.htm",
                    "source_platform": "zhilian",
                    "source_job_id": "zl-1",
                })
                update_job_status(db, job_id, "ready")
            finally:
                db.close()
            server.set_base_dir(base_dir)

            with mock.patch.object(
                server.task_runner,
                "start",
                return_value={"id": "task-1", "status": "queued"},
            ) as start:
                blocked_status, blocked_payload = self._request(
                    "/api/workbench/deliver",
                    {"job_ids": [job_id]},
                )
                delivered_status, delivered_payload = self._request(
                    "/api/workbench/deliver",
                    {
                        "job_ids": [job_id],
                        "ack_zhilian_default_greeting": True,
                    },
                )

        self.assertTrue(blocked_status.startswith("409"), blocked_payload)
        self.assertEqual(blocked_payload["code"], "delivery_confirmation_required")
        self.assertEqual(
            blocked_payload["confirmations_required"]["zhilian_default_greeting_ids"],
            [job_id],
        )
        self.assertTrue(delivered_status.startswith("200"), delivered_payload)
        self.assertEqual(delivered_payload["id"], "task-1")
        self.assertEqual(delivered_payload["manual_required_count"], 0)
        start.assert_called_once()

    def test_51job_uses_manual_delivery_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            job_id = "51job:job-1"
            db = get_db(base_dir / "data" / "bosshunter.db")
            try:
                insert_job(db, {
                    "id": job_id,
                    "title": "采集岗位",
                    "company": "示例公司",
                    "jd": "JD",
                    "url": "https://jobs.51job.com/shanghai/job-1.html",
                    "source_platform": "51job",
                    "source_job_id": "job-1",
                })
            finally:
                db.close()
            server.set_base_dir(base_dir)

            with mock.patch.object(server.task_runner, "start") as start:
                deliver_status, deliver_payload = self._request(
                    "/api/workbench/deliver",
                    {"job_ids": [job_id]},
                )
            resume_status, resume_payload = self._request(f"/api/jobs/{job_id}/mark-resume-sent")

        self.assertTrue(deliver_status.startswith("200"), deliver_payload)
        self.assertEqual(deliver_payload["manual_required_count"], 1)
        self.assertEqual(deliver_payload["manual_required_ids"], [job_id])
        self.assertTrue(resume_status.startswith("403"), resume_payload)
        start.assert_not_called()
