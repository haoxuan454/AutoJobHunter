"""Safe, platform-isolated delivery stage for ``auto_full``."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from threading import Event
from typing import Any, Callable

from bosshunter.automation.models import DeliveryAttempt
from bosshunter.automation.queue import PlatformDeliveryQueue, QueueHalted
from bosshunter.automation.quota import claim_slot, consume_slot, release_slot
from bosshunter.db import get_db
from bosshunter.executor.sender import send_greetings


_RUNTIME_CONFIG_KEYS = frozenset({
    "_workbench_stop_event",
    "_workbench_log",
    "_workbench_send_report",
    "_workbench_collect_progress",
    "_workbench_score_progress",
    "_workbench_score_checkpoint",
})


def _copy_delivery_config(config: dict[str, Any]) -> dict[str, Any]:
    """Copy settings without cloning thread-bound runtime handles."""
    copied = {
        key: deepcopy(value)
        for key, value in config.items()
        if key not in _RUNTIME_CONFIG_KEYS
    }
    for key in _RUNTIME_CONFIG_KEYS:
        if key in config:
            copied[key] = config[key]
    copied.pop("_workbench_send_report", None)
    return copied


def prepare_eligible_jobs(
    db_path: Path,
    jobs_by_platform: dict[str, list[str]],
    *,
    boss_greeting: str,
) -> None:
    """Mark only this run's qualifying jobs as approved and configure greeting."""
    conn = get_db(db_path)
    try:
        for platform, job_ids in jobs_by_platform.items():
            for job_id in job_ids:
                if platform == "boss":
                    conn.execute(
                        "UPDATE jobs SET status='approved', greeting=?, updated_at=CURRENT_TIMESTAMP "
                        "WHERE id=? AND deleted_at IS NULL AND source_platform='boss' AND status IN ('ready','approved')",
                        (boss_greeting, job_id),
                    )
                else:
                    conn.execute(
                        "UPDATE jobs SET status='approved', updated_at=CURRENT_TIMESTAMP "
                        "WHERE id=? AND deleted_at IS NULL AND source_platform='zhilian' AND status IN ('ready','approved')",
                        (job_id,),
                    )
        conn.commit()
    finally:
        conn.close()


def deliver_eligible_jobs(
    config: dict[str, Any],
    jobs_by_platform: dict[str, list[str]],
    *,
    db_path: Path,
    boss_greeting: str,
    min_delay_seconds: float,
    max_delay_seconds: float,
    stop_event: Event | None = None,
    log: Callable[[str], None] | None = None,
    sleeper=None,
    rng=None,
) -> list[DeliveryAttempt]:
    """Send per-platform queues concurrently, serially within each platform."""
    prepare_eligible_jobs(db_path, jobs_by_platform, boss_greeting=boss_greeting)
    results: list[DeliveryAttempt] = []

    def send_one(platform: str, job_id: str) -> DeliveryAttempt:
        local_config = _copy_delivery_config(config)
        local_config["_workbench_job_ids"] = [job_id]
        local_config["_workbench_stop_event"] = stop_event
        local_config["_workbench_log"] = log
        if platform == "boss":
            local_config.setdefault("profile", {})
        if log:
            log(f"{platform}: sending job {job_id}")
        try:
            claim = claim_slot(config, db_path=db_path, job_id=job_id, platform=platform)
        except Exception as exc:
            return DeliveryAttempt(
                platform,
                job_id,
                False,
                False,
                status="quota_claim_error",
                error=str(exc),
            )
        if claim.get("status") != "claimed":
            status = str(claim.get("status") or "quota_unavailable")
            return DeliveryAttempt(
                platform,
                job_id,
                False,
                False,
                status=status,
                error=("automatic daily delivery quota exhausted" if status == "exhausted" else "job delivery is already in flight"),
                metadata={"quota": claim},
            )
        claim_id = str(claim["claim_id"])
        local_config["_automatic_delivery_claim_id"] = claim_id
        try:
            send_greetings(local_config, force=False, db_path=db_path)
        except Exception as exc:
            release_slot(db_path=db_path, claim_id=claim_id)
            return DeliveryAttempt(platform, job_id, False, False, status="exception", error=str(exc))
        report = local_config.get("_workbench_send_report") or {}
        sent = int(report.get("sent_count", 0) or 0)
        failed = int(report.get("failed_count", 0) or 0)
        reason = str(report.get("stop_reason") or "")
        safe = sent > 0 and failed == 0 and not reason
        if safe:
            consumed = consume_slot(db_path=db_path, claim_id=claim_id)
            if not consumed:
                # Do not leave an in-flight reservation behind when the
                # accounting transition itself cannot be verified.
                release_slot(db_path=db_path, claim_id=claim_id)
                return DeliveryAttempt(
                    platform,
                    job_id,
                    False,
                    False,
                    status="quota_consume_failed",
                    error="automatic quota claim could not be consumed safely",
                    metadata={"report": report, "claim_id": claim_id},
                )
        else:
            release_slot(db_path=db_path, claim_id=claim_id)
        return DeliveryAttempt(
            platform,
            job_id,
            success=safe,
            verified=safe,
            status="sent" if safe else (reason or "failed"),
            error=None if safe else (reason or "platform delivery was not safely verified"),
            metadata={"report": report, "claim_id": claim_id},
        )

    def run_platform(platform: str, job_ids: list[str]) -> list[DeliveryAttempt]:
        queue = PlatformDeliveryQueue(
            min_delay_seconds=min_delay_seconds,
            max_delay_seconds=max_delay_seconds,
            sleeper=sleeper or __import__("time").sleep,
            rng=rng or __import__("random").Random(),
        )
        try:
            return queue.run({platform: job_ids}, send_one, stop_event=stop_event)
        except QueueHalted as exc:
            if log:
                log(f"{platform}: queue stopped: {exc}")
            return list(exc.attempts)

    selected = {platform: list(ids) for platform, ids in jobs_by_platform.items() if ids}
    if not selected:
        return []
    with ThreadPoolExecutor(max_workers=len(selected), thread_name_prefix="auto-deliver") as executor:
        futures = {executor.submit(run_platform, platform, ids): platform for platform, ids in selected.items()}
        for future in as_completed(futures):
            results.extend(future.result())
    return results
