"""BOSS relative-address regression and unsafe navigation boundaries."""

import pytest
from unittest.mock import patch

from bosshunter.boss_urls import resolve_boss_job_url
from bosshunter.executor.sender import _send_greeting_once


@pytest.mark.parametrize("value", [
    "/job_detail/abc_123.html?securityId=identity&lid=search",
    "job_detail/abc_123.html?securityId=identity&lid=search",
    "https://www.zhipin.com/job_detail/abc_123.html?securityId=identity&lid=search",
])
def test_detail_url_expands_to_absolute_and_preserves_identity_query(value):
    assert resolve_boss_job_url(value) == (
        "https://www.zhipin.com/job_detail/abc_123.html?securityId=identity&lid=search"
    )


@pytest.mark.parametrize("value", [
    "", None, "https://example.com/job_detail/abc.html",
    "//example.com/job_detail/abc.html", "javascript:alert(1)",
    "file:///job_detail/abc.html", "/web/geek/chat", "/job_detail/../abc.html",
    "https://www.zhipin.com:9222/job_detail/abc.html",
    "https://user:password@www.zhipin.com/job_detail/abc.html",
])
def test_invalid_or_foreign_addresses_never_open_a_browser(value):
    assert resolve_boss_job_url(value) is None
    with patch("bosshunter.executor.sender.new_tab") as opened:
        result, target = _send_greeting_once({"id": "abc", "url": value}, "您好", {})
    assert result["error"] == "invalid_job_url"
    assert target is None
    opened.assert_not_called()


def test_legacy_relative_saved_job_is_expanded_before_open_without_mutating_job():
    job = {"id": "abc", "url": "/job_detail/abc.html?securityId=identity"}
    with patch("bosshunter.executor.sender.new_tab", return_value="local-fixture") as opened, \
         patch("bosshunter.executor.sender.evaluate", return_value='{"success": false, "error": "job_page_unavailable"}'), \
         patch("bosshunter.executor.sender.close_tab"):
        _send_greeting_once(job, "您好", {"browse_before_greet": False})
    opened.assert_called_once_with(
        "https://www.zhipin.com/job_detail/abc.html?securityId=identity", background=True,
    )
    assert job["url"] == "/job_detail/abc.html?securityId=identity"
