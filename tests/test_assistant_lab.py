import sqlite3
import unittest
from unittest.mock import patch

from bosshunter import assistant_lab


class AssistantLabContextTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.knowledge = sqlite3.connect(":memory:")
        self.knowledge.row_factory = sqlite3.Row
        assistant_lab._init(self.conn)

    def tearDown(self):
        self.conn.close()
        self.knowledge.close()

    @patch("bosshunter.assistant_lab.get_ai_api_key", return_value="test-key")
    @patch("bosshunter.assistant_lab.call_anthropic_text")
    @patch("bosshunter.assistant_lab.search_confirmed_facts", return_value=[])
    def test_second_turn_prompt_contains_only_same_session_history(self, facts, call_model, api_key):
        call_model.side_effect = ["我接触过 Spring Boot 和 MyBatis，主要用于接口和业务逻辑开发。", "上一轮提到的 Java 项目中，我主要负责接口、数据处理和联调。"]
        first = assistant_lab.send_message(self.conn, self.knowledge, {"ai": {"api_key": "x"}}, "session-a", "你之前学过 Java 框架吗？")
        assistant_lab.send_message(self.conn, self.knowledge, {"ai": {"api_key": "x"}}, "session-a", "细说一下做了哪些项目？")
        prompt = call_model.call_args_list[1].args[0]
        self.assertIn("HR：你之前学过 Java 框架吗？", prompt)
        self.assertIn("求职者：我接触过 Spring Boot 和 MyBatis", prompt)
        self.assertIn("HR 当前问题：细说一下做了哪些项目？", prompt)
        self.assertEqual(first["generation_mode"], "configured_model")

    @patch("bosshunter.assistant_lab.get_ai_api_key", return_value="test-key")
    @patch("bosshunter.assistant_lab.call_anthropic_text", return_value="我先直接说结论：这样讲既体现了你的能力。")
    @patch("bosshunter.assistant_lab.search_confirmed_facts")
    def test_coaching_or_document_dump_never_becomes_hr_reply(self, facts, call_model, api_key):
        facts.return_value = [{"id": 1, "title": "Java 项目", "content": "负责接口开发和联调，处理异常问题。"}]
        result = assistant_lab.send_message(self.conn, self.knowledge, {"ai": {"api_key": "x"}}, "session-a", "你做过哪些 Java 项目？")
        reply = result["messages"][-1]["content"]
        self.assertNotIn("我先直接说结论", reply)
        self.assertNotIn("面试官听到", reply)
        self.assertEqual(result["model_error"], "unsafe_or_irrelevant_output_rejected")

        call_model.return_value = "负责接口开发和联调，处理异常问题，完成数据处理并跟进测试交付。" * 50
        result = assistant_lab.send_message(self.conn, self.knowledge, {"ai": {"api_key": "x"}}, "session-a", "你做过哪些 Java 项目？")
        self.assertEqual(result["generation_mode"], "local_evidence")

    @patch("bosshunter.assistant_lab.search_confirmed_facts", return_value=[])
    def test_context_isolated_between_sessions(self, facts):
        assistant_lab.send_message(self.conn, self.knowledge, {}, "session-a", "A 公司的 Java 项目是什么？")
        assistant_lab.send_message(self.conn, self.knowledge, {}, "session-b", "B 公司的 Python 项目是什么？")
        self.assertNotIn("A 公司的", assistant_lab._conversation_context(self.conn, "session-b"))
        self.assertIn("B 公司的", assistant_lab._conversation_context(self.conn, "session-b"))


if __name__ == "__main__":
    unittest.main()
