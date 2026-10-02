"""Orchestration boundary for the opt-in automatic full workflow."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Any, Callable

from bosshunter.automation.collector import collect_selected_platforms
from bosshunter.automation.delivery import deliver_eligible_jobs
from bosshunter.automation.models import AutomationPhase, AutomationRunResult
from bosshunter.automation.reconciliation import reconcile_deliveries
from bosshunter.automation.scoring import score_collected_jobs
from bosshunter.automation.state_machine import AutomationStateMachine


class AutoFullRunner:
    """Run collection -> score -> queue delivery -> local reconciliation."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        options: dict[str, Any],
        db_path: Path,
        task_id: str = "",
        stop_event: Event | None = None,
        confirm_delivery: Callable[[list[str]], list[str]] | None = None,
        auto_approve_delivery: bool = False,
        log: Callable[[str], None] | None = None,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = config
        self.options = options
        self.db_path = db_path
        self.task_id = task_id
        self.stop_event = stop_event or Event()
        self.confirm_delivery = confirm_delivery
        self.auto_approve_delivery = bool(auto_approve_delivery)
        self.log = log
        self.progress = progress
        self.machine = AutomationStateMachine()

    def run(self) -> AutomationRunResult:
        result = AutomationRunResult(phase=AutomationPhase.CREATED)
        # Reject unsafe or malformed delivery settings before opening a
        # platform page or performing any collection work.
        max_deliveries_per_platform = _max_deliveries_per_platform(self.options)
        min_delay, max_delay = _delivery_delay(self.config)
        if "boss" in self.options.get("platform_order", []):
            _boss_greeting(self.config)
        self.machine.transition(AutomationPhase.COLLECTING)
        result.phase = self.machine.phase
        if self.log:
            self.log("automatic workflow: collection started")
        collection = collect_selected_platforms(
            self.config,
            self.options,
            db_path=self.db_path,
            task_id=self.task_id,
            stop_event=self.stop_event,
            log=self.log,
            progress=self.progress,
        )
        result.collected_job_ids = collection.collected_job_ids
        # Scope automatic scoring to this search's matches, not merely rows
        # newly inserted into SQLite. Keep compatibility with older doubles.
        result.matched_job_ids = list(getattr(collection, "matched_job_ids", None) or result.collected_job_ids)
        result.platform_states = collection.platform_states
        result.errors.update(collection.errors)
        if self.stop_event.is_set():
            self.machine.stop()
            result.phase = self.machine.phase
            result.stop_reason = "user_stopped"
            return result
        failed_platforms = [
            platform
            for platform, state in collection.platform_states.items()
            if str(state.get("status") or "").lower() in {"failed", "blocked", "error", "aborted"}
        ]
        if collection.errors or failed_platforms:
            self.machine.fail()
            result.phase = self.machine.phase
            result.stop_reason = "collection_failed"
            if self.log:
                failed = ", ".join(sorted(set([*collection.errors, *failed_platforms])))
                self.log(f"automatic workflow stopped before scoring/delivery; collection failed: {failed}")
            return result
        if not result.matched_job_ids:
            self.machine.transition(AutomationPhase.SCORING)
            self.machine.fail()
            result.phase = self.machine.phase
            result.stop_reason = "collection_no_candidates"
            result.errors["collection"] = "no candidates were collected in this run"
            if self.log:
                self.log("automatic workflow failed before scoring/delivery: no candidates were collected")
            return result

        self.machine.transition(AutomationPhase.SCORING)
        result.phase = self.machine.phase
        threshold = _number(self.config.get("scoring", {}).get("threshold"), 60.0)
        scored = score_collected_jobs(
            self.config,
            result.matched_job_ids,
            threshold=threshold,
            max_per_platform=max_deliveries_per_platform,
            db_path=self.db_path,
            stop_event=self.stop_event,
            log=self.log,
            progress=progress_score(self.progress),
        )
        jobs_by_platform = scored["eligible_by_platform"]
        result.eligible_job_ids = list(scored["eligible_job_ids"])
        if not scored.get("scoring_complete", False):
            self.machine.fail()
            result.phase = self.machine.phase
            incomplete = scored.get("scoring_incomplete_job_ids") or []
            result.stop_reason = "scoring_incomplete"
            result.errors["scoring"] = (
                "scoring did not complete for the collected batch"
                + (f" ({len(incomplete)} job(s) incomplete)" if incomplete else "")
            )
            if self.log:
                self.log("automatic workflow stopped before delivery because batch scoring was incomplete")
            return result
        if not any(jobs_by_platform.values()):
            self.machine.fail()
            result.phase = self.machine.phase
            result.stop_reason = "no_eligible_jobs"
            result.errors["delivery"] = "no collected job reached the configured score threshold"
            if self.log:
                self.log("automatic workflow failed before delivery: no collected job reached the configured score threshold")
            return result
        if self.stop_event.is_set():
            self.machine.stop()
            result.phase = self.machine.phase
            result.stop_reason = "user_stopped"
            return result
        if self.auto_approve_delivery:
            # This is an explicit opt-in owned by the automatic workflow only.
            # Direct callers and the legacy manual workflow remain fail-closed.
            approved_ids = list(result.eligible_job_ids)
        elif self.confirm_delivery is None:
            approved_ids: list[str] = []
        else:
            approved_ids = self.confirm_delivery(list(result.eligible_job_ids))
        eligible_ids = set(result.eligible_job_ids)
        result.approved_job_ids = list(dict.fromkeys(
            str(job_id) for job_id in approved_ids if str(job_id) in eligible_ids
        ))
        if self.stop_event.is_set():
            self.machine.stop()
            result.phase = self.machine.phase
            result.stop_reason = "user_stopped"
            return result
        if not result.approved_job_ids:
            self.machine.transition(AutomationPhase.QUEUED)
            self.machine.transition(AutomationPhase.COMPLETED)
            result.phase = self.machine.phase
            result.stop_reason = "delivery_not_confirmed"
            if self.log:
                self.log("no delivery was sent: no eligible job received explicit user confirmation")
            return result
        approved = set(result.approved_job_ids)
        jobs_by_platform = {
            platform: [job_id for job_id in ids if str(job_id) in approved]
            for platform, ids in jobs_by_platform.items()
        }
        self.machine.transition(AutomationPhase.QUEUED)
        self.machine.transition(AutomationPhase.DELIVERING)
        result.phase = self.machine.phase
        boss_greeting = _boss_greeting(self.config)
        result.attempts = deliver_eligible_jobs(
            self.config,
            jobs_by_platform,
            db_path=self.db_path,
            boss_greeting=boss_greeting,
            min_delay_seconds=min_delay,
            max_delay_seconds=max_delay,
            stop_event=self.stop_event,
            log=self.log,
        )
        delivery_failed = any(not attempt.safe_success for attempt in result.attempts)
        verified_attempts = [attempt for attempt in result.attempts if attempt.safe_success]

        # A failed platform must never be promoted to success, but it must not
        # discard local evidence from a different platform that was already
        # verified successfully. Reconcile the verified subset first, then
        # keep the overall run failed when any delivery was not safely verified.
        # This matters for the parallel BOSS + Zhilian flow: one platform can
        # finish safely while the other is blocked by confirmation or risk control.
        if not verified_attempts:
            if self.stop_event.is_set():
                self.machine.stop()
                result.phase = self.machine.phase
                result.stop_reason = "user_stopped"
                return result
            self.machine.fail()
            result.phase = self.machine.phase
            result.stop_reason = "delivery_not_safely_verified"
            return result

        self.machine.transition(AutomationPhase.RECONCILING)
        result.phase = self.machine.phase
        result.reconciliation = reconcile_deliveries(
            self.db_path,
            [
                {"platform": attempt.platform, "job_id": attempt.job_id}
                for attempt in result.attempts
                if attempt.safe_success
            ],
        )
        if not result.reconciliation.get("ok"):
            self.machine.fail()
            result.phase = self.machine.phase
            result.stop_reason = "conversation_reconciliation_failed"
            return result
        if self.stop_event.is_set():
            # A stop can arrive after one platform has already verified a send
            # while another platform queue is still unwinding. Persist the
            # verified subset locally before honoring cancellation; do not
            # start monitoring or permit another delivery cycle afterwards.
            self.machine.stop()
            result.phase = self.machine.phase
            result.stop_reason = "user_stopped_after_verified_delivery"
            return result
        if delivery_failed:
            # A platform queue can be blocked after another platform has
            # already produced a safely verified delivery.  Keep the verified
            # subset usable by the automatic monitor and expose the failed
            # subset as a warning instead of discarding the whole run.
            self.machine.transition(AutomationPhase.PARTIAL_COMPLETED)
            result.phase = self.machine.phase
            result.stop_reason = "delivery_partially_completed"
            result.errors["delivery"] = (
                "one or more platform deliveries were not safely verified; "
                "verified deliveries were reconciled locally"
            )
            return result
        self.machine.transition(AutomationPhase.COMPLETED)
        result.phase = self.machine.phase
        return result


def progress_score(callback: Callable[[dict[str, Any]], None] | None):
    return callback


def _number(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _boss_greeting(config: dict[str, Any]) -> str:
    candidates = [
        config.get("automation", {}).get("boss_greeting") if isinstance(config.get("automation"), dict) else "",
        config.get("profile", {}).get("greeting_preference") if isinstance(config.get("profile"), dict) else "",
        config.get("greeting") if isinstance(config.get("greeting"), str) else "",
    ]
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    raise ValueError("automatic BOSS delivery requires a configured greeting")


def _delivery_delay(config: dict[str, Any]) -> tuple[float, float]:
    throttle = config.get("throttle") if isinstance(config.get("throttle"), dict) else {}
    minimum = max(_number(throttle.get("interval_min"), 60.0), 0.0)
    maximum = max(_number(throttle.get("interval_max"), 180.0), minimum)
    if minimum <= 0 or maximum <= 0:
        raise ValueError("automatic delivery delay must be greater than zero")
    if maximum > 180:
        raise ValueError("automatic delivery delay cannot exceed 180 seconds")
    return minimum, maximum


def _max_deliveries_per_platform(options: dict[str, Any]) -> int:
    value = options.get("max_deliveries_per_platform", 3)
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("automatic delivery limit must be an integer") from exc
    if isinstance(value, bool) or str(value).strip() != str(limit) or not 1 <= limit <= 3:
        raise ValueError("automatic delivery limit must be an integer from 1 to 3")
    return limit
