"""独立的智联招聘岗位沟通适配器。"""

from typing import Any

from bosshunter.browser import close_tab
from .base import DeliveryContext, DeliveryResult, dry_run_result
from .browser_helpers import click_text_or_selectors, fill_first_visible_input, inspect_page, open_job, verify_sent


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
            action = click_text_or_selectors(target_id, ["在线沟通", "立即沟通"], [".job-detail-summary__prechat"])
            if not action.get("success"):
                close_tab(target_id)
                return DeliveryResult(
                    False,
                    platform=self.platform,
                    error="default_greeting_action_required",
                    history_detail=(
                        "智联招聘当前岗位只有“先聊聊”入口，点击会立即发送平台默认招呼语；"
                        "为避免误发，适配器不会把它当作自定义消息发送。请人工确认后继续。"
                    ),
                    target_id=target_id,
                )
            filled = fill_first_visible_input(target_id, ["textarea", "input[placeholder*='消息']", "textarea[placeholder*='消息']"], greeting)
            if not filled.get("success"):
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error=filled.get("error", "message_input_missing"), history_detail="智联招聘沟通窗口未找到输入框", target_id=target_id)
            sent = click_text_or_selectors(target_id, ["发送", "发送消息"], ["button[type='submit']", ".send-btn", ".message-send"])
            if not sent.get("success"):
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error="send_button_missing", history_detail="智联招聘沟通窗口未找到发送按钮", target_id=target_id)
            verified = verify_sent(target_id, greeting, self.platform)
            return DeliveryResult(bool(verified.get("success")), bool(verified.get("verified")), self.platform, verified.get("error"), verified.get("history_detail", ""), target_id=target_id)
        except Exception as exc:
            close_tab(target_id)
            return DeliveryResult(False, platform=self.platform, error="adapter_exception", history_detail=f"智联招聘适配器异常：{exc}", target_id=target_id)
