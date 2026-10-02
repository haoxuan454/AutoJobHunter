"""Browser facade backed by BossHunter's built-in Browser Runtime."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bosshunter.browser.client import RuntimeClient
from bosshunter.browser.platform_targets import filter_platform_targets, target_id
from bosshunter.browser.runtime import ensure_runtime, get_runtime_url, set_browser_config

CDP_PROXY_URL = get_runtime_url()
CDP_DIRECT_URL = "http://localhost:9222"
CDP_DEFAULT_URL = "http://127.0.0.1:9222"
NAV_TIMEOUT_MS = 15000


def configure(config: dict[str, Any] | None = None) -> None:
    """Set process-wide browser configuration used by runtime helpers."""
    set_browser_config(config)


def _client() -> RuntimeClient:
    return RuntimeClient()


def _ready() -> bool:
    return ensure_runtime()


def check_chrome_connection() -> dict | None:
    """Check whether Browser Runtime can connect to Chrome."""
    if not _ready():
        return None
    return _client().health()


def get_page_targets() -> list[dict]:
    """Get page targets from Browser Runtime."""
    if not _ready():
        return []
    return _client().targets()


def find_boss_tab() -> dict | None:
    """Find the public BOSS job-search tab without selecting the chat tab.

    Chrome commonly has both ``/web/geek/jobs`` and ``/web/geek/chat`` open.
    Collection must use the former; selecting the first ``zhipin.com`` target
    makes list extraction return an empty list even though the search page is
    healthy.  Keep this helper search-page oriented, just like
    :func:`find_zhilian_tab` is oriented toward the public search site.
    """
    candidates: list[tuple[int, int, dict]] = []
    for index, target in enumerate(filter_platform_targets(get_page_targets(), "boss")):
        url = str(target.get("url", "")).strip().lower()
        if "passport.zhipin.com" in url or "/web/geek/chat" in url:
            continue
        if "/web/geek/jobs" in url or "/web/geek/job" in url:
            priority = 0
        else:
            priority = 1
        candidates.append((priority, index, target))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def find_zhilian_tab() -> dict | None:
    """Find the existing 智联岗位搜索 tab without opening or logging in.

    Chrome commonly keeps both the public job-search page (``www.zhaopin.com``)
    and the private IM page (``i.zhaopin.com``) open at the same time.  The
    collection/preflight path needs the former; returning the first tab that
    merely contains ``zhaopin.com`` can accidentally select the IM page and
    make a healthy logged-in browser look like a changed search-page schema.
    """
    candidates: list[tuple[int, int, dict]] = []
    for index, target in enumerate(filter_platform_targets(get_page_targets(), "zhilian")):
        url = str(target.get("url", "")).strip().lower()
        # Prefer the public recruitment site and explicitly exclude the IM
        # origin. If the exact search route changes, any public www page is
        # still safer than selecting a chat page for collection diagnostics.
        if "i.zhaopin.com" in url or "passport.zhaopin.com" in url:
            continue
        priority = 0 if "www.zhaopin.com" in url else 1
        candidates.append((priority, index, target))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))

    # A closed/stale CDP target can keep its old URL in ``/targets`` while
    # JavaScript execution has already stopped responding.  Do one bounded,
    # read-only DOM probe per candidate and select the first live search page.
    # This is deliberately kept here (rather than in diagnostics) so every
    # caller uses the same target-selection rule.
    client = _client()
    probe = """(() => {
      const input = document.querySelector(
        'input.query-sug__input, input.search-wrapper__input'
      );
      return JSON.stringify({
        ok: Boolean(input),
        ready: document.readyState,
        url: window.location.href,
      });
    })()"""
    for _priority, _index, target in candidates:
        target_key = target_id(target)
        if not target_key:
            continue
        try:
            raw = client.evaluate(target_key, probe, timeout=5)
        except Exception:
            continue
        payload = raw
        if isinstance(raw, str):
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                payload = None
        if isinstance(payload, dict) and payload.get("ok") and payload.get("ready") == "complete":
            return target
    return None


def new_tab(url: str, background: bool = False) -> str | None:
    """Open a tab and return its target ID."""
    if not _ready():
        return None
    return _client().new_tab(url, background=background)


def close_tab(target_id: str) -> bool:
    """Close a tab by target ID."""
    if not _ready():
        return False
    return _client().close_tab(target_id)


def navigate(target_id: str, url: str) -> bool:
    """Navigate a tab to a URL."""
    if not _ready():
        return False
    return _client().navigate(target_id, url)


def evaluate(target_id: str, expression: str, timeout: float = 30) -> Any:
    """Execute JavaScript in a tab and return the runtime value."""
    if not _ready():
        return None
    return _client().evaluate(target_id, expression, timeout)


def click(target_id: str, selector: str) -> bool:
    """Click an element by CSS selector using DOM click."""
    if not _ready():
        return False
    return _client().click(target_id, selector)


def click_at(target_id: str, selector_or_xy: str) -> bool:
    """Click by selector or x,y coordinates using CDP mouse events."""
    if not _ready():
        return False
    return _client().click_at(target_id, selector_or_xy)


def type_text(target_id: str, text: str, human: bool = False) -> bool:
    """Insert text using CDP input events."""
    if not _ready():
        return False
    return _client().type_text(target_id, text, human=human)


def press_key(target_id: str, key: str) -> bool:
    """Press a supported browser key using CDP keyboard events."""
    if not _ready():
        return False
    return _client().press_key(target_id, key)


def set_files(target_id: str, selector: str, files: list[str]) -> bool:
    """Set files on a file input."""
    if not _ready():
        return False
    return _client().set_files(target_id, selector, files)


def scroll(target_id: str, y: int = 0, direction: str = "") -> bool:
    """Scroll a page."""
    if not _ready():
        return False
    return _client().scroll(target_id, y=y, direction=direction)


def screenshot(target_id: str, file_path: str | Path, *, selector: str = "") -> bool:
    """Capture a screenshot to a file."""
    if not _ready():
        return False
    return _client().screenshot(target_id, file_path, selector=selector)


def print_pdf(target_id: str, file_path: str | Path) -> bool:
    """Render a target as PDF to a file."""
    if not _ready():
        return False
    return _client().print_pdf(target_id, file_path)


def get_page_info(target_id: str) -> dict | None:
    """Get page title, URL, and ready state."""
    if not _ready():
        return None
    return _client().info(target_id)


def _page_url_matches(
    url: Any,
    *,
    expected_url: Any = None,
    expected_host: Any = None,
) -> bool:
    """Return whether a loaded page is a real HTTP(S) page in the target scope."""
    actual = urlsplit(str(url or "").strip())
    if actual.scheme not in {"http", "https"} or not actual.hostname:
        return False

    if expected_host:
        host_value = str(expected_host).strip()
        host = urlsplit(host_value if "://" in host_value else f"//{host_value}").hostname
        if host and actual.hostname.lower() != host.lower():
            return False

    if expected_url:
        expected = urlsplit(str(expected_url).strip())
        if expected.hostname and actual.hostname.lower() != expected.hostname.lower():
            return False
        expected_path = (expected.path or "/").rstrip("/") or "/"
        actual_path = (actual.path or "/").rstrip("/") or "/"
        if actual_path != expected_path and not actual_path.startswith(expected_path + "/"):
            return False

    return True


def wait_for_load(
    target_id: str,
    timeout: float = 10.0,
    *,
    expected_url: Any = None,
    expected_host: Any = None,
) -> bool:
    """Wait for a real target page instead of the initial blank state."""
    start = time.time()
    while time.time() - start < timeout:
        info = get_page_info(target_id)
        if info and info.get("ready") == "complete" and _page_url_matches(
            info.get("url"), expected_url=expected_url, expected_host=expected_host
        ):
            return True
        time.sleep(0.25)
    return False
