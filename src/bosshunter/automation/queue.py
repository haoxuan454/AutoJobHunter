"""Platform-isolated, serial delivery queues with injectable timing."""

from __future__ import annotations

import random
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import Event
from typing import Any

from .models import DeliveryAttempt


class QueueHalted(RuntimeError):
    def __init__(self, message: str, *, attempt: DeliveryAttempt | None = None, attempts: list[DeliveryAttempt] | None = None):
        super().__init__(message)
        self.attempt = attempt
        self.attempts = list(attempts or ([] if attempt is None else [attempt]))


@dataclass
class PlatformDeliveryQueue:
    """Run jobs one-by-one per platform.

    The callback owns the existing platform adapter/safety guards.  This class
    only provides deterministic ordering, cancellation, bounded jitter and the
    rule that an unverified result halts that queue immediately.
    """

    min_delay_seconds: float = 0.0
    max_delay_seconds: float = 0.0
    sleeper: Callable[[float], None] = time.sleep
    rng: random.Random = random.Random()

    def __post_init__(self) -> None:
        self.min_delay_seconds = max(float(self.min_delay_seconds), 0.0)
        self.max_delay_seconds = max(float(self.max_delay_seconds), self.min_delay_seconds)
        if self.max_delay_seconds > 180.0:
            raise ValueError("automatic delivery delay cannot exceed 180 seconds")

    def run(
        self,
        jobs_by_platform: dict[str, Iterable[str]],
        send_one: Callable[[str, str], DeliveryAttempt],
        *,
        stop_event: Event | None = None,
    ) -> list[DeliveryAttempt]:
        attempts: list[DeliveryAttempt] = []
        # The caller may execute separate instances concurrently for different
        # platforms.  One instance is always strictly serial.
        for platform, job_ids in jobs_by_platform.items():
            for index, raw_job_id in enumerate(job_ids):
                if stop_event is not None and stop_event.is_set():
                    raise QueueHalted("automatic delivery stopped", attempt=attempts[-1] if attempts else None, attempts=attempts)
                if index and self._wait_between_items(stop_event):
                    raise QueueHalted("automatic delivery stopped during cooldown", attempt=attempts[-1] if attempts else None, attempts=attempts)
                job_id = str(raw_job_id)
                attempt = send_one(str(platform), job_id)
                attempts.append(attempt)
                if not attempt.safe_success:
                    reason = attempt.error or attempt.status or "platform delivery was not safely verified"
                    raise QueueHalted(reason, attempt=attempt, attempts=[*attempts])
        return attempts

    def _wait_between_items(self, stop_event: Event | None) -> bool:
        delay = self.rng.uniform(self.min_delay_seconds, self.max_delay_seconds)
        if delay <= 0:
            return bool(stop_event and stop_event.is_set())
        if stop_event is None:
            self.sleeper(delay)
            return False
        # Use short interruptible slices so stop/cancel remains responsive.
        remaining = delay
        while remaining > 0:
            if stop_event.wait(min(1.0, remaining)):
                return True
            remaining -= min(1.0, remaining)
        return stop_event.is_set()


def group_job_ids(rows: Iterable[dict[str, Any]], allowed_platforms: set[str] | None = None) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    allowed = allowed_platforms or {"boss", "zhilian"}
    for row in rows:
        platform = str(row.get("source_platform") or "").strip().lower()
        job_id = str(row.get("id") or "").strip()
        if platform in allowed and job_id:
            grouped[platform].append(job_id)
    return {platform: list(ids) for platform, ids in grouped.items()}
