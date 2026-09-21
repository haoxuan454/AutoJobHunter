import unittest
from unittest.mock import patch

from bosshunter.notification_classifier import classify_hr_message


class NotificationClassifierTests(unittest.TestCase):
    def test_semantic_salary_variants_match(self):
        for text in ("薪酬结构方便聊聊吗", "这个岗位的待遇可以接受吗", "我们下一步沟通月薪范围"):
            result = classify_hr_message(text, {"notifications": {"email": {"notification_types": ["salary"], "confidence_threshold": 0.8}}})
            self.assertTrue(result["matched"], text)
            self.assertEqual(result["category"], "salary")

    def test_technical_question_does_not_match(self):
        result = classify_hr_message("你之前用 Python 做过哪些项目？", {})
        self.assertFalse(result["matched"])

    def test_interview_and_wechat_match(self):
        for text, category in (("方便约线上面试吗", "interview"), ("后续加个微信沟通", "wechat")):
            result = classify_hr_message(text, {"notifications": {"email": {"notification_types": [category]}}})
            self.assertTrue(result["matched"], text)
            self.assertEqual(result["category"], category)

    @patch("bosshunter.notification_classifier.call_anthropic_text", side_effect=RuntimeError("model down"))
    @patch("bosshunter.notification_classifier.get_ai_api_key", return_value="configured")
    def test_model_failure_is_fail_closed(self, _key, _call):
        result = classify_hr_message("这个岗位后续怎么安排比较合适？", {"notifications": {"email": {"notification_types": ["salary"]}}})
        self.assertFalse(result["matched"])


if __name__ == "__main__":
    unittest.main()
