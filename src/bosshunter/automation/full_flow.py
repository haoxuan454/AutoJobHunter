"""Pure selection helpers for the opt-in automatic full workflow."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .queue import PlatformDeliveryQueue, group_job_ids


def select_eligible_jobs(
    rows: Iterable[dict[str, Any]],
    collected_job_ids: Iterable[str],
    *,
    threshold: float,
    max_per_platform: int | None = None,
) -> dict[str, list[str]]:
    """Return only this-run, scored, deliverable BOSS/智联 jobs."""
    current_ids = {str(value) for value in collected_job_ids if str(value)}
    selected_rows = [
        row for row in rows
        if str(row.get("id") or "") in current_ids
        and _platform(row) in {"boss", "zhilian"}
        and str(row.get("status") or "") in {"ready", "approved"}
        and _safe_score(row.get("score")) >= threshold
    ]
    if max_per_platform is None:
        return group_job_ids(selected_rows, {"boss", "zhilian"})

    try:
        limit = int(max_per_platform)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_per_platform must be an integer from 1 to 3") from exc
    if (
        isinstance(max_per_platform, bool)
        or str(max_per_platform).strip() != str(limit)
        or not 1 <= limit <= 3
    ):
        raise ValueError("max_per_platform must be an integer from 1 to 3")
    grouped: dict[str, list[dict[str, Any]]] = {"boss": [], "zhilian": []}
    for row in selected_rows:
        platform = _platform(row)
        if platform is None:
            continue
        grouped[platform].append(row)
    return {
        platform: [str(row["id"]) for row in sorted(
            candidates,
            key=lambda row: (-_safe_score(row.get("score")), str(row.get("id") or "")),
        )[:limit]]
        for platform, candidates in grouped.items()
        if candidates
    }


def _safe_score(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _platform(row: dict[str, Any]) -> str | None:
    """Return an explicit supported platform; never infer BOSS implicitly."""
    value = str(row.get("source_platform") or "").strip().lower()
    return value if value in {"boss", "zhilian"} else None


def run_delivery_queues(
    jobs_by_platform: dict[str, list[str]],
    send_one,
    *,
    min_delay_seconds: float,
    max_delay_seconds: float,
    stop_event=None,
    sleeper=None,
    rng=None,
):
    """Run platform queues without sharing job/conversation context."""
    queue = PlatformDeliveryQueue(
        min_delay_seconds=min_delay_seconds,
        max_delay_seconds=max_delay_seconds,
        sleeper=sleeper or __import__("time").sleep,
        rng=rng or __import__("random").Random(),
    )
    return queue.run(jobs_by_platform, send_one, stop_event=stop_event)
