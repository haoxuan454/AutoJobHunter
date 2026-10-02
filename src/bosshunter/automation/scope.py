"""Exact scope helpers for the automatic conversation monitor.

The automatic workflow must only monitor conversations created by the current
run's safely verified deliveries.  A job ID alone is not enough because the
same job identifier can be present in different platform projections, and a
conversation list can contain older runs.  This module keeps that policy in a
small, reusable boundary so the runner, monitor, and tests share one rule.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


SUPPORTED_PLATFORMS = frozenset({"boss", "zhilian"})


class DeliveryScopeError(ValueError):
    """Raised when an automatic delivery scope cannot be trusted."""


def normalize_delivery_scope(value: Iterable[Any] | None) -> list[dict[str, str]]:
    """Validate and normalize exact ``platform + job_id`` delivery pairs.

    The function is deliberately fail-closed: ``None``, an empty iterable,
    unsupported platforms, legacy ``sync:*`` IDs, and malformed entries are
    all rejected before any browser/platform callback can run.
    """

    if value is None:
        raise DeliveryScopeError("automatic delivery scope is missing")
    if isinstance(value, (str, bytes, Mapping)):
        raise DeliveryScopeError("automatic delivery scope must be a list of delivery pairs")
    try:
        items = list(value)
    except TypeError as exc:
        raise DeliveryScopeError("automatic delivery scope is not iterable") from exc
    if not items:
        raise DeliveryScopeError("automatic delivery scope is empty")

    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, Mapping):
            raise DeliveryScopeError("automatic delivery scope contains a malformed entry")
        platform = str(item.get("platform") or "").strip().lower()
        job_id = str(item.get("job_id") or "").strip()
        if platform not in SUPPORTED_PLATFORMS:
            raise DeliveryScopeError(f"automatic delivery scope contains unsupported platform: {platform or 'missing'}")
        if not job_id:
            raise DeliveryScopeError(f"automatic delivery scope is missing job_id for platform: {platform}")
        if job_id.startswith("sync:"):
            raise DeliveryScopeError("automatic delivery scope cannot contain legacy sync:* job IDs")
        key = (platform, job_id)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"platform": platform, "job_id": job_id})
    if not normalized:
        raise DeliveryScopeError("automatic delivery scope is empty")
    return normalized


def scope_keys(value: Iterable[Any] | None) -> set[tuple[str, str]]:
    """Return normalized scope pairs for exact membership comparisons."""

    return {
        (item["platform"], item["job_id"])
        for item in normalize_delivery_scope(value)
    }


def build_verified_delivery_scope(
    attempts: Iterable[Any] | None,
    reconciliation: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    """Build a scope only when delivery and reconciliation agree exactly.

    ``safe_success`` is the only accepted delivery signal.  The reconciliation
    payload must also contain the same explicit platform/job pairs; a list of
    job IDs without platform identity is not sufficient for monitoring.
    """

    safe_deliveries: list[dict[str, str]] = []
    for attempt in attempts or []:
        if isinstance(attempt, Mapping):
            safe = bool(attempt.get("success") and attempt.get("verified"))
            platform = attempt.get("platform")
            job_id = attempt.get("job_id")
        else:
            safe = bool(getattr(attempt, "safe_success", False))
            platform = getattr(attempt, "platform", "")
            job_id = getattr(attempt, "job_id", "")
        if not safe:
            continue
        safe_deliveries.append({"platform": platform, "job_id": job_id})

    expected = normalize_delivery_scope(safe_deliveries)
    if not isinstance(reconciliation, Mapping) or reconciliation.get("ok") is not True:
        raise DeliveryScopeError("automatic delivery reconciliation was not confirmed")
    reconciled = normalize_delivery_scope(reconciliation.get("successful_deliveries"))
    if scope_keys(expected) != scope_keys(reconciled):
        raise DeliveryScopeError(
            "automatic delivery scope does not match reconciled safe deliveries"
        )
    return expected


def filter_conversations(
    conversations: Iterable[Any],
    delivery_scope: Iterable[Any] | None,
) -> list[dict[str, Any]]:
    """Keep only cards matching an exact current-run platform/job pair."""

    allowed = scope_keys(delivery_scope)
    filtered: list[dict[str, Any]] = []
    for item in conversations:
        if not isinstance(item, Mapping):
            continue
        platform = str(item.get("platform") or "").strip().lower()
        job_id = str(item.get("job_id") or "").strip()
        if (platform, job_id) in allowed:
            filtered.append(dict(item))
    return filtered
