import unittest
from unittest.mock import patch

from bosshunter.executor import sender


class BossFailureClassificationTests(unittest.TestCase):
    def test_explicit_closed_marker_is_classified(self):
        payload = '{"closed": true, "snippet": "职位已关闭"}'
        with patch.object(sender, "evaluate", return_value=payload):
            result = sender._detect_job_closed_on_page("target")
        self.assertEqual(result["error"], "job_page_unavailable")
        self.assertTrue(result["skip_backoff"])

    def test_missing_chat_button_without_closed_text_is_not_classified(self):
        with patch.object(sender, "evaluate", return_value='{"closed": false}'):
            self.assertIsNone(sender._detect_job_closed_on_page("target"))


if __name__ == "__main__":
    unittest.main()
