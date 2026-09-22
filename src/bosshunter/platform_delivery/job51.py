"""独立的前程无忧岗位申请适配器。

前程无忧当前页面能力不等同于即时 HR 聊天；没有确认沟通窗口前不会把
“立即申请”伪装成聊天发送。
"""

from typing import Any

from bosshunter.browser import close_tab
from .base import DeliveryContext, DeliveryResult, dry_run_result
from .browser_helpers import inspect_page, open_job


class Job51DeliveryAdapter:
    platform = "51job"
    verified = False

    def send_greeting(self, job: dict[str, Any], greeting: str, context: DeliveryContext) -> DeliveryResult:
        if context.dry_run:
            return dry_run_result(self.platform)
        target_id, failure = open_job(job)
        if failure:
            return DeliveryResult(False, platform=self.platform, error=failure["error"], history_detail=failure["history_detail"])
        state = inspect_page(target_id, self.platform)
        close_tab(target_id)
        return DeliveryResult(False, platform=self.platform, error="chat_capability_unverified", history_detail="前程无忧当前适配器仅识别页面，尚未确认 HR 即时聊天能力", target_id=target_id)
