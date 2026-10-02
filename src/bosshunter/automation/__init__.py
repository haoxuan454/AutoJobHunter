"""Safe, opt-in automation workflow primitives.

The legacy ``full`` workbench mode intentionally remains separate.  This
package contains the deterministic pieces used by the explicit ``auto_full``
mode so they can be tested without a live browser.
"""

from .models import AutomationPhase, AutomationRunResult, DeliveryAttempt
from .queue import PlatformDeliveryQueue, QueueHalted
from .runner import AutoFullRunner
from .state_machine import AutomationStateMachine, InvalidTransition

__all__ = [
    "AutomationPhase",
    "AutomationRunResult",
    "AutomationStateMachine",
    "DeliveryAttempt",
    "InvalidTransition",
    "PlatformDeliveryQueue",
    "QueueHalted",
    "AutoFullRunner",
]
