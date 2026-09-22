"""独立的猎聘岗位沟通适配器。"""

from typing import Any

from bosshunter.browser import close_tab
from .base import DeliveryContext, DeliveryResult, dry_run_result
from .browser_helpers import inspect_page, open_job


class LiepinDeliveryAdapter:
    platform = "liepin"
    verified = False

    def send_greeting(self, job: dict[str, Any], greeting: str, context: DeliveryContext) -> DeliveryResult:
        if context.dry_run:
            return dry_run_result(self.platform)
        target_id, failure = open_job(job)
        if failure:
            return DeliveryResult(False, platform=self.platform, error=failure["error"], history_detail=failure["history_detail"])
        state = inspect_page(target_id, self.platform)
        close_tab(target_id)
        return DeliveryResult(False, platform=self.platform, error="chat_capability_unverified", history_detail="猎聘当前尚未进入具体岗位页面，暂不执行沟通发送", target_id=target_id)
