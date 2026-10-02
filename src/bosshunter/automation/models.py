"""Small immutable-ish models for the opt-in automatic workbench flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AutomationPhase(str, Enum):
    """String enum compatible with the project's Python 3.10 floor."""

    CREATED = "created"
    COLLECTING = "collecting"
    SCORING = "scoring"
    QUEUED = "queued"
    DELIVERING = "delivering"
    RECONCILING = "reconciling"
    COMPLETED = "completed"
    PARTIAL_COMPLETED = "partial_completed"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class DeliveryAttempt:
    """A single verified delivery decision.

    ``verified`` is deliberately explicit.  A platform response that merely
    says that a click was attempted must not be treated as a successful send.
    """

    platform: str
    job_id: str
    success: bool
    verified: bool
    status: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def safe_success(self) -> bool:
        return self.success and self.verified


@dataclass
class AutomationRunResult:
    phase: AutomationPhase
    collected_job_ids: list[str] = field(default_factory=list)
    matched_job_ids: list[str] = field(default_factory=list)
    eligible_job_ids: list[str] = field(default_factory=list)
    approved_job_ids: list[str] = field(default_factory=list)
    attempts: list[DeliveryAttempt] = field(default_factory=list)
    stop_reason: str | None = None
    platform_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    reconciliation: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def succeeded_job_ids(self) -> list[str]:
        return [item.job_id for item in self.attempts if item.safe_success]

    @property
    def failed_job_ids(self) -> list[str]:
        return [item.job_id for item in self.attempts if not item.safe_success]
