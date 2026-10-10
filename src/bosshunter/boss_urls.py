"""Resolve BOSS job addresses at collection and delivery boundaries."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlsplit


def resolve_boss_job_url(value: Any) -> str | None:
    """Expand legacy relative detail links without permitting foreign origins.

    Preserve the query string (including platform identity parameters). Chrome
    can silently open about:blank for a relative URL, so delivery must receive
    an absolute address even for jobs saved by older collectors.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = urlsplit(urljoin("https://www.zhipin.com/", raw))
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not (
            host == "zhipin.com" or host.endswith(".zhipin.com")
        ):
            return None
        if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            return None
        if not re.fullmatch(r"/job_detail/[A-Za-z0-9_-]+\.html", parsed.path):
            return None
    except (TypeError, ValueError):
        return None
    return parsed.geturl()
