"""Shared ordering rules for locally persisted HR conversations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping


def parse_message_datetime(value: Any) -> datetime | None:
    """Parse absolute timestamps; relative platform labels return ``None``."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _platform_sequence(row: Mapping[str, Any]) -> int | None:
    raw = row.get("raw_payload_json")
    if isinstance(raw, Mapping):
        payload = raw
    else:
        try:
            payload = json.loads(str(raw or "{}"))
        except (TypeError, ValueError):
            payload = {}
    for key in ("sequence", "seq", "index", "order", "position"):
        try:
            if payload.get(key) is not None and str(payload[key]).strip() != "":
                return int(payload[key])
        except (TypeError, ValueError):
            continue
    return None


def message_order_key(row: Mapping[str, Any]) -> tuple[int, int, float, str, int]:
    """Return a stable ascending key with adapter order as strongest signal."""
    sequence = _platform_sequence(row)
    parsed = parse_message_datetime(row.get("message_time"))
    created = parse_message_datetime(row.get("created_at"))
    timestamp = (parsed or created).timestamp() if (parsed or created) else float("-inf")
    return (1 if sequence is not None else 0, sequence if sequence is not None else -1,
            timestamp, str(row.get("created_at") or ""), int(row.get("id") or 0))


def latest_message(rows: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return max(rows, key=message_order_key, default=None)

