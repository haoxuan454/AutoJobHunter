import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from bosshunter.daily_summary_scheduler import run_daily_summary_once, should_run_today


class DailySummarySchedulerTests(unittest.TestCase):
    CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

    def _config(self, *, summary=True, email=True):
        return {"notifications": {"daily_summary": {"enabled": summary, "auto_send": summary, "send_time": "20:00", "timezone": "Asia/Shanghai"}, "email": {"enabled": email, "auto_send": email, "to_email": "me@example.com"}}}

    def test_due_gate_requires_both_opt_ins(self):
        now = datetime(2026, 9, 21, 20, 1, tzinfo=self.CHINA_TZ)
        self.assertTrue(should_run_today(self._config()["notifications"]["daily_summary"], self._config()["notifications"]["email"], now=now))
        self.assertFalse(should_run_today(self._config(summary=False)["notifications"]["daily_summary"], self._config()["notifications"]["email"], now=now))
        self.assertFalse(should_run_today(self._config()["notifications"]["daily_summary"], self._config(email=False)["notifications"]["email"], now=now))

    def test_scheduler_is_due_once_and_records_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "local.db"
            now = datetime(2026, 9, 21, 20, 1, tzinfo=self.CHINA_TZ)
            calls = []

            def generate(conn, **kwargs):
                calls.append(kwargs["day"])
                return {"notification": {"id": 7}, "summary": {"job_count": 0}}

            first = run_daily_summary_once(db, base_dir=Path(tmp), config=self._config(), now=now, generate_fn=generate)
            second = run_daily_summary_once(db, base_dir=Path(tmp), config=self._config(), now=now, generate_fn=generate)
            self.assertEqual(first["status"], "sent")
            self.assertEqual(second["status"], "already_run")
            self.assertEqual(calls, ["2026-09-21"])
            conn = sqlite3.connect(db)
            self.assertEqual(conn.execute("SELECT status FROM daily_summary_scheduler_runs").fetchone()[0], "sent")
            conn.close()

    def test_scheduler_before_time_does_not_create_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "local.db"
            now = datetime(2026, 9, 21, 19, 59, tzinfo=self.CHINA_TZ)
            result = run_daily_summary_once(db, base_dir=Path(tmp), config=self._config(), now=now)
            self.assertEqual(result["status"], "not_due")
            self.assertFalse(db.exists())


if __name__ == "__main__":
    unittest.main()
