"""Atomic daily quota reservations for the opt-in automatic delivery flow."""

from __future__ import annotations

from pathlib import Path

from bosshunter.db import (
    claim_automatic_delivery_slot,
    consume_automatic_delivery_slot,
    get_db,
    release_automatic_delivery_slot,
)


def _daily_limit(config: dict) -> int:
    throttle = config.get("throttle") if isinstance(config.get("throttle"), dict) else {}
    value = throttle.get("daily_limit", 30)
    if isinstance(value, bool):
        raise ValueError("automatic daily delivery limit must be an integer")
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("automatic daily delivery limit must be an integer") from exc
    if str(value).strip() != str(limit) or limit < 1:
        raise ValueError("automatic daily delivery limit must be a positive integer")
    return limit


def claim_slot(config: dict, *, db_path: Path, job_id: str, platform: str) -> dict:
    """Reserve one slot and return a small immutable decision payload."""
    conn = get_db(db_path)
    try:
        return claim_automatic_delivery_slot(
            conn,
            job_id=job_id,
            platform=platform,
            daily_limit=_daily_limit(config),
        )
    finally:
        conn.close()


def consume_slot(*, db_path: Path, claim_id: str) -> bool:
    conn = get_db(db_path)
    try:
        return consume_automatic_delivery_slot(conn, claim_id)
    finally:
        conn.close()


def release_slot(*, db_path: Path, claim_id: str) -> bool:
    conn = get_db(db_path)
    try:
        return release_automatic_delivery_slot(conn, claim_id)
    finally:
        conn.close()
