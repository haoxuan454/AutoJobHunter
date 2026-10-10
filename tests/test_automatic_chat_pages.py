from threading import Event
from unittest.mock import patch

import pytest

from bosshunter.automation.chat_pages import AutomaticChatPages, ChatPageError, is_chat_page


@pytest.mark.parametrize("platform,url,expected", [
    ("boss", "https://www.zhipin.com/web/geek/chat", True),
    ("boss", "https://www.zhipin.com/web/geek/jobs", False),
    ("boss", "https://zhipin.com.evil.test/web/geek/chat", False),
    ("zhilian", "https://i.zhaopin.com/im?sessionId=123", True),
    ("zhilian", "https://www.zhaopin.com/im", False),
])
def test_chat_page_exact_ownership(platform, url, expected):
    assert is_chat_page({"id": "tab", "url": url}, platform) is expected


def test_monitor_bootstraps_once_reuses_and_only_closes_owned_tab():
    pages = AutomaticChatPages(Event())
    search = {"id": "user-search", "url": "https://www.zhipin.com/web/geek/jobs"}
    inbox = {"id": "own-chat", "url": "https://www.zhipin.com/web/geek/chat"}
    with (
        patch("bosshunter.automation.chat_pages.browser.get_page_targets", side_effect=[[search], [search, inbox], [search]]),
        patch("bosshunter.automation.chat_pages.browser.new_tab", return_value="own-chat") as new,
        patch("bosshunter.automation.chat_pages.browser.evaluate", return_value={"ready": "complete", "url": inbox["url"], "rows": 1}),
        patch("bosshunter.automation.chat_pages.browser.close_tab") as close,
    ):
        pages.ensure("boss")
        pages.ensure("boss")
        with pytest.raises(ChatPageError, match="monitor_chat_page_lost"):
            pages.ensure("boss")
        pages.close()
        pages.close()
    new.assert_called_once_with(inbox["url"], background=True)
    close.assert_called_once_with("own-chat")


def test_monitor_does_not_close_existing_user_chat():
    pages = AutomaticChatPages(Event())
    with (
        patch("bosshunter.automation.chat_pages.browser.get_page_targets", return_value=[{"id": "user", "url": "https://i.zhaopin.com/im"}]),
        patch("bosshunter.automation.chat_pages.browser.new_tab") as new,
        patch("bosshunter.automation.chat_pages.browser.close_tab") as close,
    ):
        pages.ensure("zhilian")
        pages.close()
    new.assert_not_called()
    close.assert_not_called()


def test_login_redirect_stops_without_reload_and_cleanup_remains_owned():
    pages = AutomaticChatPages(Event())
    with (
        patch("bosshunter.automation.chat_pages.browser.get_page_targets", return_value=[{"id": "s", "url": "https://www.zhipin.com/"}]),
        patch("bosshunter.automation.chat_pages.browser.new_tab", return_value="owned") as new,
        patch("bosshunter.automation.chat_pages.browser.evaluate", return_value={"ready": "complete", "url": "https://passport.zhipin.com/login"}),
        patch("bosshunter.automation.chat_pages.browser.close_tab") as close,
    ):
        with pytest.raises(ChatPageError, match="redirected"):
            pages.ensure("boss")
        with pytest.raises(ChatPageError, match="lost"):
            pages.ensure("boss")
        pages.close()
    new.assert_called_once()
    close.assert_called_once_with("owned")


def test_cancel_never_opens_platform_and_missing_tab_fails_closed():
    stop = Event()
    stop.set()
    with patch("bosshunter.automation.chat_pages.browser.get_page_targets") as targets:
        with pytest.raises(ChatPageError, match="user_stopped"):
            AutomaticChatPages(stop).ensure("boss")
    targets.assert_not_called()
    with patch("bosshunter.automation.chat_pages.browser.get_page_targets", return_value=[]):
        with pytest.raises(ChatPageError, match="missing"):
            AutomaticChatPages(Event()).ensure("zhilian")


def test_initial_blank_and_async_empty_list_are_not_login_redirects():
    pages = AutomaticChatPages(Event())
    with (
        patch("bosshunter.automation.chat_pages.browser.get_page_targets", return_value=[{"id": "search", "url": "https://www.zhipin.com/"}]),
        patch("bosshunter.automation.chat_pages.browser.new_tab", return_value="owned") as new,
        patch("bosshunter.automation.chat_pages.browser.evaluate", side_effect=[
            {"ready": "complete", "url": "about:blank", "rows": 0},
            {"ready": "complete", "url": "https://www.zhipin.com/web/geek/chat", "rows": 0},
            {"ready": "complete", "url": "https://www.zhipin.com/web/geek/chat", "rows": 40},
        ]),
        patch.object(pages.stop_event, "wait", return_value=False),
    ):
        pages.ensure("boss")
    new.assert_called_once()


def test_complete_empty_inbox_times_out_without_reloading():
    pages = AutomaticChatPages(Event(), load_timeout=0.01)
    with (
        patch("bosshunter.automation.chat_pages.browser.get_page_targets", return_value=[{"id": "search", "url": "https://www.zhipin.com/"}]),
        patch("bosshunter.automation.chat_pages.browser.new_tab", return_value="owned") as new,
        patch("bosshunter.automation.chat_pages.browser.evaluate", return_value={"ready": "complete", "url": "https://www.zhipin.com/web/geek/chat", "rows": 0}),
    ):
        with pytest.raises(ChatPageError, match="load_timeout"):
            pages.ensure("boss")
    new.assert_called_once()
