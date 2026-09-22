"""独立的智联招聘岗位沟通适配器。"""

from typing import Any

from bosshunter.browser import close_tab
from .base import DeliveryContext, DeliveryResult, dry_run_result
from .browser_helpers import find_text_or_selectors, inspect_page, open_job


class ZhilianDeliveryAdapter:
    platform = "zhilian"
    verified = False

    def send_greeting(self, job: dict[str, Any], greeting: str, context: DeliveryContext) -> DeliveryResult:
        if context.dry_run:
            return dry_run_result(self.platform)
        target_id, failure = open_job(job)
        if failure:
            return DeliveryResult(False, platform=self.platform, error=failure["error"], history_detail=failure["history_detail"])
        try:
            state = inspect_page(target_id, self.platform)
            if state.get("login_required"):
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error="login_required", history_detail="智联招聘当前页面未确认登录")
            action = find_text_or_selectors(target_id, ["在线沟通", "立即沟通", "先聊聊"], [".job-detail-summary__prechat"])
            close_tab(target_id)
            if action.get("success"):
                return DeliveryResult(
                    False,
                    platform=self.platform,
                    error="default_greeting_action_required",
                    history_detail=(
                        "智联招聘当前入口会先发送平台默认招呼语，未发现可安全确认的自定义消息输入流程；"
                        "本次未点击入口、未发送任何外部消息。"
                    ),
                    target_id=target_id,
                )
            return DeliveryResult(False, platform=self.platform, error="chat_capability_unverified", history_detail="智联招聘未发现可安全验证的自定义消息入口", target_id=target_id)
        except Exception as exc:
            close_tab(target_id)
            return DeliveryResult(False, platform=self.platform, error="adapter_exception", history_detail=f"智联招聘适配器异常：{exc}", target_id=target_id)
