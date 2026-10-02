import unittest
from unittest.mock import Mock, patch


class BrowserFacadeTests(unittest.TestCase):
    @patch("bosshunter.browser.client.httpx.get")
    def test_runtime_client_allows_slow_new_tab_creation(self, get):
        from bosshunter.browser.client import RuntimeClient

        get.return_value.status_code = 200
        get.return_value.json.return_value = {"targetId": "target-1"}

        self.assertEqual(RuntimeClient({}).new_tab("https://example.com"), "target-1")
        self.assertEqual(get.call_args.kwargs["timeout"], 30)

    @patch("bosshunter.browser.client.httpx.post")
    def test_runtime_client_type_text_preserves_utf8_bytes(self, post):
        from bosshunter.browser.client import RuntimeClient

        post.return_value.status_code = 200

        self.assertTrue(RuntimeClient({}).type_text("target-1", "??", human=True))

        request = post.call_args
        self.assertEqual(request.kwargs["content"], "??".encode("utf-8"))
        self.assertEqual(request.kwargs["headers"], {"Content-Type": "text/plain; charset=utf-8"})
        self.assertEqual(request.kwargs["params"], {"target": "target-1", "human": "1"})

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_new_tab_returns_target_id_from_runtime_client(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.new_tab.return_value = "target-1"

        result = browser.new_tab("https://example.com")

        self.assertEqual(result, "target-1")
        ensure_runtime.assert_called_once()
        client_cls.return_value.new_tab.assert_called_once_with("https://example.com", background=False)

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_new_tab_can_open_in_background(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.new_tab.return_value = "target-1"

        result = browser.new_tab("https://example.com", background=True)

        self.assertEqual(result, "target-1")
        client_cls.return_value.new_tab.assert_called_once_with("https://example.com", background=True)

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_new_tab_returns_none_when_runtime_unavailable(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = False

        result = browser.new_tab("https://example.com")

        self.assertIsNone(result)
        client_cls.assert_not_called()

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_evaluate_returns_runtime_value(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.evaluate.return_value = {"title": "ok"}

        result = browser.evaluate("target-1", "document.title", timeout=12)

        self.assertEqual(result, {"title": "ok"})
        client_cls.return_value.evaluate.assert_called_once_with("target-1", "document.title", 12)

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_click_returns_boolean(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.click.return_value = True

        self.assertTrue(browser.click("target-1", "button"))

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_type_text_can_request_human_input_events(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.type_text.return_value = True

        self.assertTrue(browser.type_text("target-1", "hello", human=True))
        client_cls.return_value.type_text.assert_called_once_with("target-1", "hello", human=True)

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_press_key_delegates_to_runtime_client(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.press_key.return_value = True

        self.assertTrue(browser.press_key("target-1", "SelectAll"))
        client_cls.return_value.press_key.assert_called_once_with("target-1", "SelectAll")

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_get_page_info_returns_dict(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.info.return_value = {"title": "T", "url": "https://example.com", "ready": "complete"}

        result = browser.get_page_info("target-1")

        self.assertEqual(result["ready"], "complete")

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_wait_for_load_polls_until_ready_complete(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.info.side_effect = [
            {"ready": "complete", "url": "about:blank"},
            {"ready": "loading", "url": "https://www.zhaopin.com/jobs/1"},
            {"ready": "complete", "url": "https://www.zhaopin.com/jobs/1"},
        ]

        with patch("bosshunter.browser.time.sleep"):
            self.assertTrue(browser.wait_for_load(
                "target-1", timeout=2, expected_host="www.zhaopin.com"
            ))

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_wait_for_load_rejects_wrong_host(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.info.return_value = {
            "ready": "complete",
            "url": "https://www.zhipin.com/web/geek/job/1",
        }

        with patch("bosshunter.browser.time.sleep"):
            self.assertFalse(browser.wait_for_load(
                "target-1", timeout=0.01, expected_host="www.zhaopin.com"
            ))

    def test_page_url_matches_requires_http_page_and_expected_path(self):
        import bosshunter.browser as browser

        self.assertFalse(browser._page_url_matches("about:blank"))
        self.assertTrue(browser._page_url_matches(
            "https://www.zhaopin.com/jobs/abc?x=1",
            expected_url="https://www.zhaopin.com/jobs/abc",
            expected_host="www.zhaopin.com",
        ))
        self.assertFalse(browser._page_url_matches(
            "https://www.zhaopin.com/jobs/other",
            expected_url="https://www.zhaopin.com/jobs/abc",
        ))

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_check_chrome_connection_returns_health(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.health.return_value = {"status": "ok", "runtime": "bosshunter"}

        result = browser.check_chrome_connection()

        self.assertEqual(result["runtime"], "bosshunter")

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_find_boss_tab_matches_zhipin_url(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.targets.return_value = [
            {"targetId": "1", "url": "https://example.com"},
            {"targetId": "2", "url": "https://www.zhipin.com/web/geek/job"},
        ]

        result = browser.find_boss_tab()

        self.assertEqual(result["targetId"], "2")

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_find_boss_tab_prefers_search_page_over_chat_page(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.targets.return_value = [
            {"targetId": "chat", "url": "https://www.zhipin.com/web/geek/chat"},
            {"targetId": "jobs", "url": "https://www.zhipin.com/web/geek/jobs?query=python&city=101281600"},
        ]

        result = browser.find_boss_tab()

        self.assertEqual(result["targetId"], "jobs")

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_find_zhilian_tab_skips_stale_target_and_selects_live_target(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.targets.return_value = [
            {"targetId": "stale", "url": "https://www.zhaopin.com/jobs/?pageMode=search&jl=779"},
            {"targetId": "live", "url": "https://www.zhaopin.com/jobs/?pageMode=search&jl=779"},
        ]
        client_cls.return_value.evaluate.side_effect = [
            None,
            '{"ok":true,"ready":"complete","url":"https://www.zhaopin.com/jobs/?pageMode=search&jl=779"}',
        ]

        result = browser.find_zhilian_tab()

        self.assertEqual(result["targetId"], "live")
        self.assertEqual(client_cls.return_value.evaluate.call_count, 2)

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_find_zhilian_tab_returns_none_when_all_public_targets_are_stale(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.targets.return_value = [
            {"targetId": "stale-a", "url": "https://www.zhaopin.com/jobs/?jl=779"},
            {"targetId": "stale-b", "url": "https://www.zhaopin.com/jobs/?jl=779"},
        ]
        client_cls.return_value.evaluate.return_value = None

        self.assertIsNone(browser.find_zhilian_tab())

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_find_boss_tab_does_not_treat_chat_only_as_search_page(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.targets.return_value = [
            {"targetId": "chat", "url": "https://www.zhipin.com/web/geek/chat"},
        ]

        self.assertIsNone(browser.find_boss_tab())

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_find_zhilian_tab_prefers_public_job_page_over_im_page(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.targets.return_value = [
            {"targetId": "im", "url": "https://i.zhaopin.com/im?sessionId=abc"},
            {"targetId": "jobs", "url": "https://www.zhaopin.com/jobs/?pageMode=recommend"},
        ]
        client_cls.return_value.evaluate.return_value = '{"ok":true,"ready":"complete"}'

        result = browser.find_zhilian_tab()

        self.assertEqual(result["targetId"], "jobs")

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_find_zhilian_tab_does_not_treat_im_only_as_search_page(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.targets.return_value = [
            {"targetId": "im", "url": "https://i.zhaopin.com/im?sessionId=abc"},
        ]

        self.assertIsNone(browser.find_zhilian_tab())

    @patch("bosshunter.browser.RuntimeClient")
    @patch("bosshunter.browser.ensure_runtime")
    def test_print_pdf_delegates_to_client(self, ensure_runtime, client_cls):
        import bosshunter.browser as browser

        ensure_runtime.return_value = True
        client_cls.return_value.print_pdf.return_value = True

        self.assertTrue(browser.print_pdf("target-1", "out.pdf"))


if __name__ == "__main__":
    unittest.main()
