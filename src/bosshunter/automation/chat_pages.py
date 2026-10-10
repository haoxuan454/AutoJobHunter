"""Bounded chat-page ownership for an explicitly started automatic task.

Sending closes its temporary pages. Monitoring may open one inbox per platform,
but must never navigate user tabs, repeatedly reload, or close user-owned pages.
"""

from __future__ import annotations

import json
from threading import Event
from urllib.parse import urlsplit

from bosshunter import browser
from bosshunter.browser.platform_targets import filter_platform_targets, target_id, target_url


CHAT_URLS = {
    "boss": "https://www.zhipin.com/web/geek/chat",
    "zhilian": "https://i.zhaopin.com/im",
}


class ChatPageError(RuntimeError):
    """No safe inbox is available; stop rather than resubmit the greeting."""


def is_chat_page(target: dict, platform: str) -> bool:
    if not filter_platform_targets([target], platform):
        return False
    parsed = urlsplit(target_url(target))
    if platform == "boss":
        return parsed.path.rstrip("/") == "/web/geek/chat"
    return platform == "zhilian" and parsed.hostname == "i.zhaopin.com" and parsed.path.rstrip("/") == "/im"


class AutomaticChatPages:
    """Own only pages created by this run; reuse existing inboxes untouched."""

    def __init__(self, stop_event: Event, *, load_timeout: float = 12) -> None:
        self.stop_event = stop_event
        self.load_timeout = load_timeout
        self.created: set[str] = set()
        self.attempted: set[str] = set()

    def ensure(self, platform: str) -> None:
        if platform not in CHAT_URLS:
            raise ChatPageError("unsupported_platform")
        if self.stop_event.is_set():
            raise ChatPageError("user_stopped")
        targets = browser.get_page_targets()
        if any(is_chat_page(target, platform) for target in targets):
            return
        if platform in self.attempted:
            raise ChatPageError("monitor_chat_page_lost")
        # Do not open another account/window or attempt to log in automatically.
        if not filter_platform_targets(targets, platform):
            raise ChatPageError("platform_browser_tab_missing")
        self.attempted.add(platform)
        page_id = browser.new_tab(CHAT_URLS[platform], background=True)
        if not page_id:
            raise ChatPageError("monitor_chat_page_open_failed")
        self.created.add(page_id)
        from time import monotonic

        deadline = monotonic() + self.load_timeout
        # DOM-only readiness checks: never refresh or issue a direct platform API request.
        while not self.stop_event.is_set() and monotonic() < deadline:
            selector = "li[role=listitem]" if platform == "boss" else ".im-session-item"
            expression = "JSON.stringify({ready:document.readyState,url:location.href,rows:document.querySelectorAll(%s).length})" % json.dumps(selector)
            raw = browser.evaluate(page_id, expression, timeout=3)
            try:
                info = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                info = None
            if isinstance(info, dict) and info.get("ready") == "complete":
                # Runtime /new returns before the initial navigation commits.
                # about:blank is complete too; it is not a login redirect.
                if str(info.get("url") or "") in {"", "about:blank"}:
                    self.stop_event.wait(0.5)
                    continue
                if not is_chat_page({"target_id": page_id, "url": info.get("url")}, platform):
                    raise ChatPageError("monitor_chat_page_redirected")
                if isinstance(info.get("rows"), int) and info["rows"] > 0:
                    return
            self.stop_event.wait(0.5)
        raise ChatPageError("user_stopped" if self.stop_event.is_set() else "monitor_chat_page_load_timeout")

    def close(self) -> None:
        for page_id in tuple(self.created):
            try:
                browser.close_tab(page_id)
            except Exception:
                pass  # Cleanup must not hide the monitor's actual stop reason.
            self.created.discard(page_id)
