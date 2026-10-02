"""Strict phase transitions for ``auto_full``."""

from __future__ import annotations

from dataclasses import dataclass

from .models import AutomationPhase


class InvalidTransition(RuntimeError):
    pass


_ALLOWED: dict[AutomationPhase, set[AutomationPhase]] = {
    AutomationPhase.CREATED: {AutomationPhase.COLLECTING, AutomationPhase.STOPPED, AutomationPhase.FAILED},
    AutomationPhase.COLLECTING: {AutomationPhase.SCORING, AutomationPhase.STOPPED, AutomationPhase.FAILED},
    AutomationPhase.SCORING: {AutomationPhase.QUEUED, AutomationPhase.COMPLETED, AutomationPhase.STOPPED, AutomationPhase.FAILED},
    AutomationPhase.QUEUED: {AutomationPhase.DELIVERING, AutomationPhase.COMPLETED, AutomationPhase.STOPPED, AutomationPhase.FAILED},
    AutomationPhase.DELIVERING: {AutomationPhase.RECONCILING, AutomationPhase.STOPPED, AutomationPhase.FAILED},
    AutomationPhase.RECONCILING: {
        AutomationPhase.COMPLETED,
        AutomationPhase.PARTIAL_COMPLETED,
        AutomationPhase.STOPPED,
        AutomationPhase.FAILED,
    },
    AutomationPhase.COMPLETED: set(),
    AutomationPhase.PARTIAL_COMPLETED: set(),
    AutomationPhase.STOPPED: set(),
    AutomationPhase.FAILED: set(),
}


@dataclass
class AutomationStateMachine:
    phase: AutomationPhase = AutomationPhase.CREATED

    def transition(self, target: AutomationPhase) -> AutomationPhase:
        if target not in _ALLOWED[self.phase]:
            raise InvalidTransition(f"cannot transition {self.phase.value} -> {target.value}")
        self.phase = target
        return self.phase

    def stop(self) -> AutomationPhase:
        if self.phase in {AutomationPhase.COMPLETED, AutomationPhase.STOPPED, AutomationPhase.FAILED}:
            return self.phase
        return self.transition(AutomationPhase.STOPPED)

    def fail(self) -> AutomationPhase:
        if self.phase in {AutomationPhase.COMPLETED, AutomationPhase.STOPPED, AutomationPhase.FAILED}:
            return self.phase
        return self.transition(AutomationPhase.FAILED)
