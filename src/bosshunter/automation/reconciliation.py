"""Local conversation reconciliation for automatic verified deliveries."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from bosshunter.conversation_bridge import reconcile_verified_deliveries
from bosshunter.db import get_db


def reconcile_deliveries(
    db_path: Path,
    successful_deliveries: Iterable[Any],
) -> dict[str, Any]:
    """Project verified sends locally and assert each platform/job has a card.

    The automatic runner passes explicit platform/job pairs.  A plain job ID is
    retained only for backwards-compatible callers and is accepted when the
    local database resolves it to exactly one supported platform.
    """
    expected: list[tuple[str | None, str]] = []
    for item in successful_deliveries:
        if isinstance(item, dict):
            platform = str(item.get("platform") or "").strip().lower() or None
            job_id = str(item.get("job_id") or "").strip()
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            platform = str(item[0] or "").strip().lower() or None
            job_id = str(item[1] or "").strip()
        else:
            platform = None
            job_id = str(getattr(item, "job_id", item) or "").strip()
        if job_id:
            expected.append((platform, job_id))
    expected = list(dict.fromkeys(expected))
    conn = get_db(db_path)
    try:
        summary = reconcile_verified_deliveries(conn)
        missing: list[str] = []
        missing_messages: list[str] = []
        for platform, job_id in expected:
            if platform in {"boss", "zhilian"}:
                rows = conn.execute(
                    """SELECT c.id, COUNT(m.id) AS message_count
                       FROM conv_conversations c
                       LEFT JOIN conv_messages m ON m.conversation_id = c.id
                       WHERE c.job_id=? AND c.platform=?
                       GROUP BY c.id""",
                    (job_id, platform),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT c.id, c.platform, COUNT(m.id) AS message_count
                       FROM conv_conversations c
                       LEFT JOIN conv_messages m ON m.conversation_id = c.id
                       WHERE c.job_id=? AND c.platform IN ('boss','zhilian')
                       GROUP BY c.id""",
                    (job_id,),
                ).fetchall()
                if len(rows) != 1:
                    missing.append(job_id)
                    continue
            if not rows:
                missing.append(job_id)
                continue
            if not any(int(row["message_count"] or 0) > 0 for row in rows):
                missing_messages.append(f"{platform or 'unknown'}:{job_id}")
    finally:
        conn.close()
    return {
        "summary": summary,
        "successful_job_ids": [job_id for _, job_id in expected],
        "successful_deliveries": [
            {"platform": platform, "job_id": job_id} for platform, job_id in expected
        ],
        "missing_job_ids": missing,
        "missing_message_deliveries": missing_messages,
        "ok": not missing and not missing_messages,
    }
