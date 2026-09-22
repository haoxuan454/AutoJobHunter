"""Safe, platform-neutral delivery adapter contract."""

from dataclasses import dataclass, field
from typing import Any, Protocol



@dataclass(slots=True)
class DeliveryContext:
    """Runtime dependencies passed to a platform adapter."""

    target_id: str | None = None
    dry_run: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DeliveryResult:
    success: bool
    verified: bool = False
    platform: str = ""
    error: str | None = None
    history_detail: str = ""
    message_id: str | None = None
    target_id: str | None = None


class DeliveryAdapter(Protocol):
    platform: str
    verified: bool

    def send_greeting(self, job: dict, greeting: str, context: DeliveryContext) -> DeliveryResult:
        ...


class UnverifiedDeliveryAdapter:
    """Fail closed until a platform-specific DOM acceptance test is approved."""

    def __init__(self, platform: str) -> None:
        self.platform = platform
        self.verified = False

    def send_greeting(self, job: dict, greeting: str, context: DeliveryContext) -> DeliveryResult:
        return DeliveryResult(
            success=False,
            verified=False,
            platform=self.platform,
            error="platform_delivery_not_verified",
            history_detail=(
                f"{self.platform} 尚未完成独立页面适配与单条验收，已安全阻止发送；"
                "当前不会复用 BOSS 页面选择器。"
            ),
        )


class _BossAdapter:
    """Marker adapter for the legacy BOSS sender implementation.

    The existing BOSS DOM workflow remains in ``executor.sender`` for now.
    This adapter is deliberately not called directly; it documents the seam
    and prevents accidental use of a non-BOSS adapter in that workflow.
    """

    platform = "boss"
    verified = True

    def send_greeting(self, job: dict, greeting: str, context: DeliveryContext) -> DeliveryResult:
        return DeliveryResult(
            success=False,
            verified=True,
            platform="boss",
            error="legacy_sender_required",
            history_detail="BOSS 仍由现有 sender 负责，适配器不会绕过其风控与状态记录。",
        )


_ADAPTERS: dict[str, DeliveryAdapter] = {
    "boss": _BossAdapter(),
    "zhilian": UnverifiedDeliveryAdapter("zhilian"),
    "51job": UnverifiedDeliveryAdapter("51job"),
    "liepin": UnverifiedDeliveryAdapter("liepin"),
}


def get_delivery_adapter(platform: str) -> DeliveryAdapter:
    return _ADAPTERS.get(str(platform or "boss"), UnverifiedDeliveryAdapter(str(platform or "unknown")))
