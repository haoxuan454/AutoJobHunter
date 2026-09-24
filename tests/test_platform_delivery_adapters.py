import unittest

from bosshunter.platform_delivery import DeliveryContext, get_delivery_adapter
from bosshunter.platform_delivery.zhilian import ZhilianDeliveryAdapter


class PlatformDeliveryAdapterTests(unittest.TestCase):
    def test_every_supported_platform_has_an_explicit_adapter(self):
        for platform in ("boss", "zhilian", "51job", "liepin"):
            adapter = get_delivery_adapter(platform)
            self.assertEqual(adapter.platform, platform)

    def test_unverified_platforms_fail_closed_without_dom_reuse(self):
        for platform in ("zhilian", "51job", "liepin"):
            result = get_delivery_adapter(platform).send_greeting(
                {"id": "fixture-job", "url": "https://fixture.invalid/job"},
                "本地测试，不发送到外部平台",
                DeliveryContext(dry_run=True),
            )
            self.assertFalse(result.success)
            self.assertFalse(result.verified)
            self.assertEqual(result.error, "platform_delivery_not_verified")
            self.assertIn("不会复用 BOSS", result.history_detail)

    def test_only_accepted_zhilian_adapter_is_marked_verified(self):
        self.assertTrue(get_delivery_adapter("zhilian").verified)
        for platform in ("51job", "liepin"):
            self.assertFalse(get_delivery_adapter(platform).verified)

    def test_boss_adapter_does_not_bypass_legacy_sender(self):
        result = get_delivery_adapter("boss").send_greeting(
            {"id": "fixture-job"}, "本地测试", DeliveryContext(dry_run=True)
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error, "legacy_sender_required")

    def test_zhilian_generic_greeting_never_sends_ai_first_message(self):
        result = ZhilianDeliveryAdapter().send_greeting({}, "AI 不应发送", DeliveryContext(dry_run=False))
        self.assertFalse(result.success)
        self.assertEqual(result.error, "platform_managed_first_contact")

    def test_zhilian_contact_state_is_company_scoped(self):
        self.assertEqual(ZhilianDeliveryAdapter.contact_scope, "company")

    def test_zhilian_platform_flow_clicks_default_greeting_and_verifies(self):
        import json
        from unittest.mock import patch

        calls = []

        def fake_open(_job):
            return "zhilian-target", None

        def fake_click(target, selectors):
            calls.append((target, selectors))
            return {"success": True, "selector": selectors[0]}

        def fake_eval(_target, _expression, timeout=15):
            if "getBoundingClientRect" in _expression:
                return json.dumps({"success": True, "visible": True, "confirmation": True})
            return json.dumps({"success": True, "modalVisible": False, "hasConversationEntry": True})

        verified_chat = {"imRoute": True, "hasChatInput": True, "modalVisible": False}
        with patch("bosshunter.platform_delivery.zhilian._open_zhilian_job", fake_open), \
             patch("bosshunter.platform_delivery.zhilian.inspect_page", return_value={"login_required": False}), \
             patch("bosshunter.platform_delivery.zhilian._entry_state", return_value={"mode": "first_contact"}), \
             patch("bosshunter.platform_delivery.zhilian._wait_for_conversation", return_value=verified_chat), \
             patch("bosshunter.platform_delivery.zhilian._post_start_state", return_value=verified_chat), \
             patch("bosshunter.platform_delivery.zhilian._click_zhilian_selector", fake_click), \
             patch("bosshunter.platform_delivery.zhilian.evaluate", fake_eval), \
             patch("bosshunter.platform_delivery.zhilian.close_tab"):
            result = ZhilianDeliveryAdapter().start_conversation(
                {"url": "https://www.zhaopin.com/jobdetail/example"},
                DeliveryContext(),
            )
        self.assertTrue(result.success)
        self.assertTrue(result.verified)
        self.assertEqual(len(calls), 2)
        self.assertIn("deliver-greeting-modal", calls[1][1][0])

    def test_zhilian_default_greeting_requires_im_conversation_after_confirmation(self):
        from unittest.mock import patch

        with patch("bosshunter.platform_delivery.zhilian._open_zhilian_job", return_value=("target", None)), \
             patch("bosshunter.platform_delivery.zhilian.inspect_page", return_value={"login_required": False}), \
             patch("bosshunter.platform_delivery.zhilian._entry_state", return_value={"mode": "first_contact"}), \
             patch("bosshunter.platform_delivery.zhilian._click_zhilian_selector", return_value={"success": True}), \
             patch("bosshunter.platform_delivery.zhilian._wait_for_default_greeting_modal", return_value={"confirmation": True, "visible": True}), \
             patch("bosshunter.platform_delivery.zhilian._wait_for_conversation", return_value={"imRoute": False, "hasChatInput": False}), \
             patch("bosshunter.platform_delivery.zhilian._post_start_state", return_value={"imRoute": False, "hasChatInput": False}), \
             patch("bosshunter.platform_delivery.zhilian.close_tab"):
            result = ZhilianDeliveryAdapter().start_conversation({}, DeliveryContext())

        self.assertFalse(result.success)
        self.assertFalse(result.verified)
        self.assertEqual(result.error, "default_greeting_not_verified")

    def test_sender_does_not_accept_zhilian_success_without_verification(self):
        from unittest.mock import patch
        from bosshunter.platform_delivery.base import DeliveryResult
        from bosshunter.executor.sender import _send_greeting_once

        unverified = DeliveryResult(success=True, verified=False, platform="zhilian")
        with patch("bosshunter.executor.sender.get_delivery_adapter") as get_adapter:
            get_adapter.return_value.start_conversation.return_value = unverified
            result, target_id = _send_greeting_once(
                {"id": "job-1", "source_platform": "zhilian"}, "hello", {}
            )

        self.assertFalse(result["success"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["error"], "delivery_not_verified")
        self.assertIsNone(target_id)

    def test_zhilian_draft_echo_without_new_outgoing_message_is_not_success(self):
        import json
        from unittest.mock import patch
        from bosshunter.platform_delivery.zhilian import _fill_and_send_zhilian_message

        clock = iter([0, 0, 2, 4, 6, 8])

        def fake_evaluate(_target, expression, timeout=10):
            if "messages" in expression:
                return json.dumps({"success": True, "messages": []})
            if "input.focus()" in expression:
                return json.dumps({"success": True})
            if "input = document.querySelector" in expression:
                return json.dumps({"success": True, "empty": True})
            raise AssertionError("unexpected browser evaluation")

        with patch("bosshunter.platform_delivery.zhilian.evaluate", side_effect=fake_evaluate), \
             patch("bosshunter.platform_delivery.zhilian.type_text", return_value=True), \
             patch("bosshunter.platform_delivery.zhilian._click_zhilian_selector", return_value={"success": True}), \
             patch("bosshunter.platform_delivery.zhilian.time.time", side_effect=lambda: next(clock)), \
             patch("bosshunter.platform_delivery.zhilian.time.sleep"):
            result = _fill_and_send_zhilian_message("target", "薪资可以沟通")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "message_sent_not_verified")

    def test_zhilian_hidden_modal_template_is_accepted_after_entry_changes(self):
        from unittest.mock import patch

        states = iter([
            {"success": True, "visible": False, "confirmation": True},
            {"success": True, "visible": False, "confirmation": True},
        ])
        with patch("bosshunter.platform_delivery.zhilian._modal_state", side_effect=states), \
             patch("bosshunter.platform_delivery.zhilian._entry_state", return_value={"mode": "existing_conversation"}):
            from bosshunter.platform_delivery.zhilian import _wait_for_default_greeting_modal
            result = _wait_for_default_greeting_modal("zhilian-target", timeout=0.1)

        self.assertTrue(result["confirmation"])
        self.assertEqual(result["entry_mode"], "existing_conversation")

    def test_zhilian_existing_conversation_without_greeting_fails_closed(self):
        from unittest.mock import patch

        with patch("bosshunter.platform_delivery.zhilian._open_zhilian_job", return_value=("zhilian-target", None)), \
             patch("bosshunter.platform_delivery.zhilian.inspect_page", return_value={"login_required": False}), \
             patch("bosshunter.platform_delivery.zhilian._entry_state", return_value={"mode": "existing_conversation"}), \
             patch("bosshunter.platform_delivery.zhilian._click_zhilian_selector", return_value={"success": True}), \
             patch("bosshunter.platform_delivery.zhilian._wait_for_conversation", return_value={"jobDetail": False, "imRoute": True, "modalVisible": False, "hasChatInput": True, "conversationRoute": True}), \
             patch("bosshunter.platform_delivery.zhilian._post_start_state", return_value={"jobDetail": False, "imRoute": True, "modalVisible": False, "hasChatInput": True, "conversationRoute": True}), \
             patch("bosshunter.platform_delivery.zhilian.close_tab") as close_tab:
            result = ZhilianDeliveryAdapter().start_conversation({"url": "https://www.zhaopin.com/jobdetail/example"}, DeliveryContext())

        self.assertFalse(result.success)
        self.assertEqual(result.error, "existing_conversation_greeting_missing")
        close_tab.assert_called_once_with("zhilian-target")

    def test_zhilian_existing_conversation_sends_and_verifies_greeting(self):
        from unittest.mock import DEFAULT, patch

        module = "bosshunter.platform_delivery.zhilian"
        names = ("_open_zhilian_job", "inspect_page", "_entry_state", "_click_zhilian_selector", "_wait_for_conversation", "_post_start_state", "_fill_and_send_zhilian_message")
        with patch.multiple(module, **{name: DEFAULT for name in names}) as mocks:
            mocks["_open_zhilian_job"].return_value = ("target", None)
            mocks["inspect_page"].return_value = {"login_required": False}
            mocks["_entry_state"].return_value = {"mode": "existing_conversation"}
            mocks["_click_zhilian_selector"].return_value = {"success": True}
            mocks["_wait_for_conversation"].return_value = {"imRoute": True, "hasChatInput": True}
            mocks["_post_start_state"].return_value = {"imRoute": True, "hasChatInput": True}
            mocks["_fill_and_send_zhilian_message"].return_value = {"success": True}
            result = ZhilianDeliveryAdapter().start_conversation({}, DeliveryContext(metadata={"greeting": "test"}))

        self.assertTrue(result.success)
        self.assertTrue(result.verified)
        self.assertEqual(result.delivery_kind, "custom_message")
        mocks["_fill_and_send_zhilian_message"].assert_called_once_with("target", "test")

    def test_zhilian_existing_conversation_does_not_count_nav_search_as_chat(self):
        from unittest.mock import patch

        with patch("bosshunter.platform_delivery.zhilian._open_zhilian_job", return_value=("zhilian-target", None)), \
             patch("bosshunter.platform_delivery.zhilian.inspect_page", return_value={"login_required": False}), \
             patch("bosshunter.platform_delivery.zhilian._entry_state", return_value={"mode": "existing_conversation"}), \
             patch("bosshunter.platform_delivery.zhilian._click_zhilian_selector", return_value={"success": True}), \
             patch("bosshunter.platform_delivery.zhilian._wait_for_conversation", return_value={"jobDetail": True, "imRoute": False, "modalVisible": False, "conversationRoute": False, "hasChatInput": False}), \
             patch("bosshunter.platform_delivery.zhilian.close_tab"):
            result = ZhilianDeliveryAdapter().start_conversation({"url": "https://www.zhaopin.com/jobdetail/example"}, DeliveryContext())

        self.assertFalse(result.success)
        self.assertEqual(result.error, "existing_conversation_not_verified")

    def test_zhilian_send_message_requires_im_route_and_sender(self):
        from unittest.mock import patch

        with patch("bosshunter.platform_delivery.zhilian._open_zhilian_job", return_value=("zhilian-target", None)), \
             patch("bosshunter.platform_delivery.zhilian.inspect_page", return_value={"login_required": False}), \
             patch("bosshunter.platform_delivery.zhilian._entry_state", return_value={"mode": "existing_conversation"}), \
             patch("bosshunter.platform_delivery.zhilian._click_zhilian_selector", return_value={"success": True}), \
             patch("bosshunter.platform_delivery.zhilian._wait_for_conversation", return_value={"imRoute": True, "hasChatInput": True}), \
             patch("bosshunter.platform_delivery.zhilian._fill_and_send_zhilian_message", return_value={"success": True}), \
             patch("bosshunter.platform_delivery.zhilian.close_tab"):
            result = ZhilianDeliveryAdapter().send_message({"url": "https://www.zhaopin.com/jobdetail/example"}, "本地测试", DeliveryContext())

        self.assertTrue(result.success)
        self.assertTrue(result.verified)


if __name__ == "__main__":
    unittest.main()
