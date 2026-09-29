import json
import unittest
from unittest.mock import patch

from bosshunter.executor import sender


class BossDeliveryMetadataTests(unittest.TestCase):
    def test_reads_masked_name_and_stable_identity_from_current_chat_dom_snapshot(self):
        payload = {
            "success": True,
            "hr_name": "刘先生",
            "company": "示例公司",
            "title": "Python 后端开发工程师",
            "external_conversation_id": "conversation-1",
            "hr_external_id": "geek-1",
            "conversation_url": "https://www.zhipin.com/web/geek/chat?uid=geek-1",
        }
        with patch.object(sender, "evaluate", return_value=json.dumps(payload)):
            result = sender._boss_delivery_metadata("target-1", {"title": "Python 后端开发工程师"})
        self.assertEqual(result["conversation"]["hr_name"], "刘先生")
        self.assertEqual(result["conversation"]["hr_external_id"], "geek-1")
        self.assertEqual(result["conversation"]["conversation_url"], payload["conversation_url"])

    def test_snapshot_failure_is_best_effort_and_does_not_invent_identity(self):
        with patch.object(sender, "evaluate", side_effect=RuntimeError("dom unavailable")):
            self.assertEqual(sender._boss_delivery_metadata("target-1", {"title": "岗位"}), {})


if __name__ == "__main__":
    unittest.main()
