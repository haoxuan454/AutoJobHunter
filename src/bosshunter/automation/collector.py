"""Collection stage for the opt-in automatic full workflow.

The legacy collection orchestrator is intentionally reused, but each selected
platform receives its own orchestrator and SQLite connection.  This keeps the
platforms independent while allowing BOSS and Zhilian collection to overlap.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable

from bosshunter.collection.orchestrator import CollectionOrchestrator


@dataclass
class CollectionStageResult:
    collected_job_ids: list[str] = field(default_factory=list)
    matched_job_ids: list[str] = field(default_factory=list)
    platform_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    run_ids: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


_RUNTIME_CONFIG_KEYS = frozenset({
    "_workbench_stop_event",
    "_workbench_log",
    "_workbench_collect_progress",
})


def _copy_collection_config(config: dict[str, Any]) -> dict[str, Any]:
    """Copy serializable settings without cloning live runtime handles."""
    return {
        key: deepcopy(value)
        for key, value in config.items()
        if key not in _RUNTIME_CONFIG_KEYS
    }


def collect_selected_platforms(
    config: dict[str, Any],
    options: dict[str, Any],
    *,
    db_path: Path,
    task_id: str = "",
    stop_event: Event | None = None,
    log: Callable[[str], None] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> CollectionStageResult:
    """Collect only the selected BOSS/Zhilian platforms in parallel.

    A platform failure is retained in the result and does not silently turn
    into a successful run.  The other platform may finish independently unless
    the shared stop event is set.
    """
    order = [str(value).strip().lower() for value in options.get("platform_order", [])]
    platforms = options.get("platforms") if isinstance(options.get("platforms"), dict) else {}
    selected = [platform for platform in order if platform in {"boss", "zhilian"} and isinstance(platforms.get(platform), dict)]
    if not selected:
        raise ValueError("automatic workflow requires BOSS or Zhilian")

    lock = Lock()
    result = CollectionStageResult(platform_states={platform: {"status": "queued", "new": 0} for platform in selected})

    def run_one(platform: str) -> dict[str, Any]:
        if stop_event is not None and stop_event.is_set():
            return {"status": "stopped", "reason_code": "user_stopped", "collected_job_ids": []}

        platform_config = _copy_collection_config(config)
        platform_config["_workbench_stop_event"] = stop_event
        platform_config["_workbench_log"] = (
            lambda message, p=platform: log(f"{p}: {message}") if log else None
        )

        def emit(state: dict[str, Any], p: str = platform) -> None:
            if progress is None:
                return
            with lock:
                progress({"platform": p, **state})

        platform_config["_workbench_collect_progress"] = emit
        single_options = {
            "platform_order": [platform],
            "auto_score": False,
            "platforms": {platform: deepcopy(platforms[platform])},
        }
        return CollectionOrchestrator(
            platform_config,
            db_path=db_path,
            task_id=task_id,
        ).run(single_options)

    with ThreadPoolExecutor(max_workers=len(selected), thread_name_prefix="auto-collect") as executor:
        futures = {executor.submit(run_one, platform): platform for platform in selected}
        for future in as_completed(futures):
            platform = futures[future]
            try:
                payload = future.result()
            except Exception as exc:  # keep the other platform independent
                result.errors[platform] = f"{type(exc).__name__}: {exc}"
                result.platform_states[platform] = {"status": "failed", "error": str(exc), "new": 0}
                if log:
                    log(f"{platform}: collection failed: {exc}")
                continue
            result.run_ids[platform] = str(payload.get("run_id") or "")
            result.platform_states[platform] = dict(payload.get("platforms", {}).get(platform) or {})
            result.collected_job_ids.extend(str(job_id) for job_id in payload.get("collected_job_ids", []) if str(job_id))
            result.matched_job_ids.extend(str(job_id) for job_id in payload.get("matched_job_ids", []) if str(job_id))
            if str(payload.get("status") or "") in {"failed", "blocked"}:
                message = str(result.platform_states[platform].get("message") or payload.get("error") or payload.get("status"))
                result.errors[platform] = message
            if progress:
                progress({"platform": platform, "result": payload, "stage": "completed"})

    result.collected_job_ids = list(dict.fromkeys(result.collected_job_ids))
    result.matched_job_ids = list(dict.fromkeys(result.matched_job_ids))
    return result
