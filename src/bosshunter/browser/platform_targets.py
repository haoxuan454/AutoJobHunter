"""Strict ownership checks for already-open recruitment platform targets.

The browser can have BOSS and Zhilian tabs open at the same time. A plain
substring check is unsafe because it can accept look-alike hosts or select a
target belonging to the other platform.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit


PLATFORM_ROOT_DOMAINS = {
    "boss": "zhipin.com",
    "zhilian": "zhaopin.com",
}


def target_url(target: dict[str, Any] | None) -> str:
    """Return a target URL from Runtime or normalized target shape."""
    if not isinstance(target, dict):
        return ""
    return str(target.get("url") or target.get("targetUrl") or "").strip()


def target_id(target: dict[str, Any] | None) -> str:
    """Return a target id from Runtime or normalized target shape."""
    if not isinstance(target, dict):
        return ""
    return str(target.get("targetId") or target.get("target_id") or target.get("id") or "").strip()


def host_belongs_to_platform(host: str | None, platform: str) -> bool:
    """Match an exact root domain or a real subdomain, never a look-alike."""
    root = PLATFORM_ROOT_DOMAINS.get(str(platform or "").strip().lower())
    normalized = str(host or "").strip().lower().rstrip(".")
    return bool(root and normalized and (normalized == root or normalized.endswith(f".{root}")))


def target_belongs_to_platform(target: dict[str, Any] | None, platform: str) -> bool:
    """Return true only for HTTP(S) targets owned by ``platform``."""
    parsed = urlsplit(target_url(target))
    return parsed.scheme in {"http", "https"} and host_belongs_to_platform(parsed.hostname, platform)


def filter_platform_targets(
    targets: Iterable[dict[str, Any]] | None,
    platform: str,
) -> list[dict[str, Any]]:
    """Keep targets with a valid id and strict platform ownership."""
    result: list[dict[str, Any]] = []
    for target in targets or []:
        if target_id(target) and target_belongs_to_platform(target, platform):
            result.append(target)
    return result
