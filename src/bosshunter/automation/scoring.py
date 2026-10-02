"""Scoring stage for the opt-in automatic full workflow."""

from __future__ import annotations

import uuid
from pathlib import Path
from threading import Event
from typing import Any, Callable

from bosshunter.ai.scorer import sanitize_score_trace, score_jobs
from bosshunter.automation.full_flow import select_eligible_jobs
from bosshunter.db import get_db, get_score_trace


# Search results can include jobs that this application already handled. Keep
# those rows in the collection audit, but do not rescore or redeliver them.
# This scope is local to the automatic path; manual scoring behavior remains
# unchanged.
_AUTOMATIC_SCORING_SKIP_STATUSES = frozenset({
    "approved",
    "error",
    "rejected",
    "sent",
    "replied",
    "resume_sent",
    "needs_resume",
    "follow_up_sent",
})
_AUTOMATIC_SCORING_STATUSES = frozenset({
    "pending",
    "scored",
    "ready",
    "filtered",
})


def score_collected_jobs(
    config: dict[str, Any],
    collected_job_ids: list[str],
    *,
    threshold: float,
    max_per_platform: int,
    db_path: Path,
    stop_event: Event | None = None,
    log: Callable[[str], None] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Score only this run's jobs, then return threshold-qualified IDs."""
    ids = list(dict.fromkeys(str(job_id) for job_id in collected_job_ids if str(job_id)))
    if not ids:
        return {"eligible_by_platform": {}, "eligible_job_ids": [], "scored_job_ids": []}
    # Resolve the search scope before invoking the scorer.  Collection tracks
    # every search match, while the scorer intentionally only selects jobs in
    # its normal scoring states.  Keep those two scopes explicit so a prior
    # delivery cannot be reported as a missing score.
    conn = get_db(db_path)
    placeholders = ",".join("?" for _ in ids)
    initial_rows = [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM jobs WHERE deleted_at IS NULL AND id IN ({placeholders})",
            ids,
        ).fetchall()
    ]
    conn.close()
    row_by_id = {str(row.get("id")): row for row in initial_rows}
    missing_ids = [job_id for job_id in ids if job_id not in row_by_id]
    invalid_platform_ids = [
        job_id
        for job_id in ids
        if job_id in row_by_id
        and str(row_by_id[job_id].get("source_platform") or "").strip().lower()
        not in {"boss", "zhilian"}
    ]
    skipped_job_ids = [
        job_id
        for job_id in ids
        if job_id in row_by_id
        and str(row_by_id[job_id].get("status") or "").strip().lower()
        in _AUTOMATIC_SCORING_SKIP_STATUSES
    ]
    scoring_ids = [
        job_id
        for job_id in ids
        if job_id in row_by_id
        and job_id not in invalid_platform_ids
        and str(row_by_id[job_id].get("status") or "").strip().lower()
        in _AUTOMATIC_SCORING_STATUSES
    ]
    unknown_status_ids = [
        job_id
        for job_id in ids
        if job_id in row_by_id
        and job_id not in invalid_platform_ids
        and job_id not in skipped_job_ids
        and job_id not in scoring_ids
    ]

    score_config = dict(config)
    score_config["_workbench_stop_event"] = stop_event
    score_config["_workbench_log"] = log
    score_config["_workbench_score_progress"] = progress
    score_run_id = uuid.uuid4().hex
    score_config["_workbench_score_run_id"] = score_run_id
    score_config["_workbench_automatic_scoring"] = True
    # Automatic delivery requires a fresh, auditable AI trace for each
    # scorable collected job and must not use the quick-score shortcut.
    score_config["_workbench_require_ai_score_trace"] = True
    checkpoint: dict[str, Any] = {}

    def capture_checkpoint(state: dict[str, Any]) -> None:
        if isinstance(state, dict):
            checkpoint.clear()
            checkpoint.update(state)

    score_config["_workbench_score_checkpoint"] = capture_checkpoint
    if log:
        log(
            f"starting automatic scoring for {len(scoring_ids)} scorable jobs "
            f"({len(skipped_job_ids)} already handled/skipped)"
        )
    if scoring_ids:
        score_jobs(
            score_config,
            scope="selected",
            job_ids=scoring_ids,
            limit=None,
            # Keep rescore bounded to this run's currently scorable matches.
            force_rescore=True,
            db_path=db_path,
        )
    else:
        # A search containing only already-handled jobs is a safe no-op, not a
        # failed AI batch. No model request is made in this branch.
        checkpoint["status"] = "skipped"
    conn = get_db(db_path)
    rows = [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM jobs WHERE deleted_at IS NULL AND id IN ({placeholders})",
            ids,
        ).fetchall()
    ]
    # Re-read after scoring, but retain the initial scope classification above.
    # Terminal rows were intentionally not rescored and must not become false
    # trace failures in this run.
    row_ids = {str(row.get("id")) for row in rows}
    missing_ids = [job_id for job_id in ids if job_id not in row_ids]
    invalid_platform_ids = [
        job_id
        for job_id in ids
        if job_id in row_by_id
        and str(row_by_id[job_id].get("source_platform") or "").strip().lower()
        not in {"boss", "zhilian"}
    ]
    remaining_ids = [
        str(job_id)
        for job_id in checkpoint.get("remaining_job_ids", [])
        if str(job_id)
    ]
    incomplete_rows = [
        str(row.get("id"))
        for row in rows
        if str(row.get("id") or "") in scoring_ids and (
            str(row.get("status") or "").lower() in {"pending", "scoring"}
        or str(row.get("score_reason") or "").startswith("AI评分失败:")
        )
    ]
    trace_missing_ids: list[str] = []
    trace_invalid_ids: list[str] = []
    for row in rows:
        job_id = str(row.get("id") or "")
        if job_id not in scoring_ids:
            continue
        found, trace = get_score_trace(conn, job_id)
        if not found or not isinstance(trace, dict):
            trace_missing_ids.append(job_id)
            continue
        if trace.get("_automatic_run_id") != score_run_id:
            trace_invalid_ids.append(job_id)
            continue
        if sanitize_score_trace(trace) is None:
            trace_invalid_ids.append(job_id)

    checkpoint_status = str(checkpoint.get("status") or "")
    scoring_complete = (
        not missing_ids
        and not invalid_platform_ids
        and not unknown_status_ids
        and not remaining_ids
        and not incomplete_rows
        and not trace_missing_ids
        and not trace_invalid_ids
        and checkpoint_status in {"completed", "skipped"}
    )
    conn.close()
    eligible = select_eligible_jobs(
        rows,
        scoring_ids,
        threshold=threshold,
        max_per_platform=max_per_platform,
    )
    eligible_ids = [job_id for values in eligible.values() for job_id in values]
    return {
        "eligible_by_platform": eligible,
        "eligible_job_ids": eligible_ids,
        "scored_job_ids": list(scoring_ids),
        "skipped_job_ids": list(skipped_job_ids),
        "unknown_status_job_ids": list(unknown_status_ids),
        "scoring_complete": scoring_complete,
        "scoring_checkpoint_status": checkpoint_status,
        "scoring_incomplete_job_ids": list(dict.fromkeys([
            *missing_ids,
            *invalid_platform_ids,
            *unknown_status_ids,
            *remaining_ids,
            *incomplete_rows,
            *trace_missing_ids,
            *trace_invalid_ids,
        ])),
        "scoring_trace_missing_job_ids": list(dict.fromkeys(trace_missing_ids)),
        "scoring_trace_invalid_job_ids": list(dict.fromkeys(trace_invalid_ids)),
        "invalid_platform_job_ids": list(dict.fromkeys(invalid_platform_ids)),
        "rows": rows,
    }
