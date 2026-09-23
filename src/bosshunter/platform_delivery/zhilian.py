"""独立的智联招聘岗位沟通适配器。"""

import json
from typing import Any

import time

from bosshunter.browser import click_at, close_tab, evaluate, get_page_info, navigate, new_tab, type_text, wait_for_load
from .base import DeliveryContext, DeliveryResult, dry_run_result
from .browser_helpers import inspect_page, parse_result


def _modal_state(target_id: str) -> dict[str, Any]:
    return parse_result(evaluate(target_id, """
    (() => {
      const modal = document.querySelector('.deliver-greeting-modal');
      if (!modal) return JSON.stringify({success:true, visible:false, confirmation:false});
      const rect = modal.getBoundingClientRect();
      const style = getComputedStyle(modal);
      const visible = !!(rect.width && rect.height && style.display !== 'none' &&
        style.visibility !== 'hidden' && style.opacity !== '0');
      const title = modal.querySelector('.deliver-greeting-modal__title');
      const titleText = (title && (title.innerText || title.textContent) || '').replace(/\s+/g, '');
      return JSON.stringify({success:true, visible,
        confirmation:/\u5df2\u5411\u5bf9\u65b9\u53d1\u9001(\u7b80\u5386\u548c)?\u6253\u62db\u547c\u8bed/.test(titleText),
        title:titleText, url:location.href});
    })()
    """, timeout=10))


def _wait_for_default_greeting_modal(target_id: str, timeout: float = 8.0) -> dict[str, Any]:
    """Wait for智联默认招呼完成，兼容隐藏模板和实际可见弹框。"""
    deadline = time.time() + timeout
    state: dict[str, Any] = {}
    while time.time() < deadline:
        state = _modal_state(target_id)
        if state.get("visible") and state.get("confirmation"):
            return state
        # 智联部分版本会把弹框容器保持为 display:none，但同时把岗位入口
        # 更新为“继续沟通”；此时主按钮仍是平台实际的继续入口。
        entry_mode = _entry_state(target_id).get("mode")
        if state.get("confirmation") and entry_mode == "existing_conversation":
            state["entry_mode"] = entry_mode
            return state
        time.sleep(0.4)
    return state


def _entry_state(target_id: str) -> dict[str, Any]:
    return parse_result(evaluate(target_id, """
    (() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return !!(r.width && r.height && s.display !== 'none' && s.visibility !== 'hidden' &&
          s.pointerEvents !== 'none');
      };
      const items = [...document.querySelectorAll('button.summary-planes__prechat,.job-detail-summary__prechat')]
        .filter(visible);
      const item = items.find(el => (el.innerText || el.textContent || '').trim());
      const text = item ? (item.innerText || item.textContent || '').replace(/\s+/g, '') : '';
      const mode = /\u5148\u804a\u804a|\u7acb\u5373\u6c9f\u901a/.test(text) ? 'first_contact' :
        (/\u7ee7\u7eed\u6c9f\u901a/.test(text) ? 'existing_conversation' : 'unknown');
      return JSON.stringify({success:true, mode, text, selector:item ?
        (item.matches('button.summary-planes__prechat') ? 'button.summary-planes__prechat' : '.job-detail-summary__prechat') : null});
    })()
    """, timeout=10))


def _post_start_state(target_id: str) -> dict[str, Any]:
    return parse_result(evaluate(target_id, """
    (() => {
      const modal = document.querySelector('.deliver-greeting-modal');
      const rect = modal && modal.getBoundingClientRect();
      const style = modal && getComputedStyle(modal);
      const modalVisible = !!(modal && rect.width && rect.height && style.display !== 'none' &&
        style.visibility !== 'hidden' && style.opacity !== '0');
      const text = document.body ? (document.body.innerText || '') : '';
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return !!(r.width && r.height && s.display !== 'none' && s.visibility !== 'hidden');
      };
      const hasChatInput = [...document.querySelectorAll('textarea,[contenteditable="true"]')].some(visible);
      const jobDetail = /\/jobdetail\//.test(location.pathname);
      const imRoute = location.hostname === 'i.zhaopin.com' && location.pathname === '/im';
      return JSON.stringify({success:true, url:location.href, modalVisible, jobDetail, hasChatInput,
        imRoute, conversationRoute:imRoute && /\u6d88\u606f|\u6c9f\u901a|\u4f1a\u8bdd/.test(text)});
    })()
    """, timeout=10))


def _open_zhilian_job(job: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """Open a Zhilian page and repair runtimes that create an about:blank tab."""
    url = str(job.get("url") or "")
    # 智联首次联系的弹框依赖前台页面事件；后台标签页可能只保留隐藏模板。
    target_id = new_tab(url, background=False)
    if not target_id:
        return None, {"success": False, "error": "open_page_failed", "history_detail": "无法打开智联岗位页面"}
    info = get_page_info(target_id) or {}
    if str(info.get("url") or "") in {"", "about:blank"}:
        if not url or not navigate(target_id, url):
            close_tab(target_id)
            return None, {"success": False, "error": "open_page_failed", "history_detail": "智联岗位新标签未完成导航"}
    if not wait_for_load(target_id, timeout=15):
        close_tab(target_id)
        return None, {"success": False, "error": "page_load_timeout", "history_detail": "智联岗位页面加载超时"}
    return target_id, None


def _click_zhilian_selector(target_id: str, selectors: list[str]) -> dict[str, Any]:
    for selector in selectors:
        if click_at(target_id, selector):
            return {"success": True, "selector": selector}
        fallback = parse_result(evaluate(target_id, f"""
        (() => {{
          const el = document.querySelector({json.dumps(selector)});
          if (!el) return JSON.stringify({{success:false,error:'action_button_missing'}});
          el.click();
          return JSON.stringify({{success:true,selector:{json.dumps(selector)}}});
        }})()
        """, timeout=10))
        if fallback.get("success"):
            return fallback
    return {"success": False, "error": "action_button_missing"}


def _wait_for_conversation(target_id: str, timeout: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    state: dict[str, Any] = {}
    while time.time() < deadline:
        state = _post_start_state(target_id)
        if state.get("imRoute") and (state.get("hasChatInput") or state.get("conversationRoute")):
            return state
        time.sleep(0.4)
    return state


def _fill_and_send_zhilian_message(target_id: str, message: str) -> dict[str, Any]:
    if not message.strip():
        return {"success": False, "error": "message_empty"}
    focused = parse_result(evaluate(target_id, """
    (() => {
      const input = document.querySelector('.im-sender__input');
      if (!input || !input.offsetWidth || !input.offsetHeight) return JSON.stringify({success:false,error:'message_input_missing'});
      input.focus();
      return JSON.stringify({success:true});
    })()
    """, timeout=10))
    if not focused.get("success"):
        return focused
    if not type_text(target_id, message, human=True):
        return {"success": False, "error": "message_input_fill_failed"}
    send = _click_zhilian_selector(target_id, ["button.im-sender__send-btn"])
    if not send.get("success"):
        return {"success": False, "error": "message_send_button_missing"}
    time.sleep(1.2)
    sent = parse_result(evaluate(target_id, f"""
    (() => JSON.stringify({{success:(document.body.innerText || '').includes({json.dumps(message, ensure_ascii=False)})}}))()
    """, timeout=10))
    return sent if sent.get("success") else {"success": False, "error": "message_sent_not_verified"}


class ZhilianDeliveryAdapter:
    platform = "zhilian"
    verified = True
    # 智联把首次联系状态按公司维度共享到该公司其他岗位。
    contact_scope = "company"

    def start_conversation(self, job: dict[str, Any], context: DeliveryContext) -> DeliveryResult:
        """Start Zhilian's platform-managed first contact.

        Zhilian sends the initial greeting itself.  This intentionally does not
        accept or generate message text.  A successful result means only that
        the platform confirmation was observed; it does not mean HR replied.
        """
        if context.dry_run:
            return dry_run_result(self.platform)
        target_id, failure = _open_zhilian_job(job)
        if failure:
            return DeliveryResult(False, platform=self.platform, error=failure["error"], history_detail=failure["history_detail"])
        try:
            state = inspect_page(target_id, self.platform)
            if state.get("login_required"):
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error="login_required", history_detail="智联招聘当前页面未确认登录")

            entry_state = _entry_state(target_id)
            mode = entry_state.get("mode")
            if mode == "unknown":
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error="conversation_entry_missing", history_detail="智联岗位页未找到可见的先聊聊或继续沟通入口", target_id=target_id)
            entry = _click_zhilian_selector(target_id, [
                "button.summary-planes__prechat",
                ".job-detail-summary__prechat",
            ])
            if not entry.get("success"):
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error="conversation_entry_missing", history_detail="智联岗位页入口不可点击", target_id=target_id)

            time.sleep(0.5)
            if mode == "existing_conversation":
                verification = _wait_for_conversation(target_id)
                time.sleep(0.8)
                stable_verification = _post_start_state(target_id)
                if verification.get("modalVisible") or not (
                    (verification.get("imRoute") and stable_verification.get("imRoute")) and
                    (verification.get("hasChatInput") and stable_verification.get("hasChatInput"))
                ):
                    close_tab(target_id)
                    return DeliveryResult(False, platform=self.platform, error="existing_conversation_not_verified", history_detail="智联继续沟通入口已点击，但未确认进入对应 HR 会话", target_id=target_id)
                return DeliveryResult(True, True, self.platform, None, "智联已进入已有 HR 会话；未发送新的首条消息。", target_id=target_id)

            before_confirm = _wait_for_default_greeting_modal(target_id)
            if not before_confirm.get("confirmation") or not (
                before_confirm.get("visible") or before_confirm.get("entry_mode") == "existing_conversation"
            ):
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error="default_greeting_modal_not_confirmed", history_detail="智联弹框未显示平台默认招呼语确认文案", target_id=target_id)
            confirmed = _click_zhilian_selector(
                target_id,
                ["button.deliver-greeting-modal__btn.deliver-greeting-modal__btn--primary"],
            )
            if not confirmed.get("success"):
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error="default_greeting_confirmation_missing", history_detail="智联默认招呼弹框未找到可见的继续沟通按钮", target_id=target_id)

            time.sleep(1.5)
            verification = _post_start_state(target_id)
            if verification.get("modalVisible"):
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error="default_greeting_not_verified", history_detail="已点击继续沟通，但弹框仍可见，未确认流程完成", target_id=target_id)
            return DeliveryResult(
                True,
                True,
                self.platform,
                None,
                "智联平台默认招呼已确认发送；这不代表 HR 已回复，后续需单独监测智联会话列表。",
                target_id=target_id,
            )
        except Exception as exc:
            close_tab(target_id)
            return DeliveryResult(False, platform=self.platform, error="adapter_exception", history_detail=f"智联默认沟通适配器异常：{exc}", target_id=target_id)

    def send_message(self, job: dict[str, Any], message: str, context: DeliveryContext) -> DeliveryResult:
        """Send a message only after the existing-conversation route is verified."""
        if context.dry_run:
            return dry_run_result(self.platform)
        target_id, failure = _open_zhilian_job(job)
        if failure:
            return DeliveryResult(False, platform=self.platform, error=failure["error"], history_detail=failure["history_detail"])
        try:
            if inspect_page(target_id, self.platform).get("login_required"):
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error="login_required", history_detail="智联招聘当前页面未确认登录")
            state = _entry_state(target_id)
            if state.get("mode") != "existing_conversation":
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error="first_contact_required", history_detail="该智联岗位尚未确认已有会话，发送消息前必须先走平台默认招呼流程", target_id=target_id)
            if not _click_zhilian_selector(target_id, ["button.summary-planes__prechat", ".job-detail-summary__prechat"]).get("success"):
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error="conversation_entry_missing", history_detail="智联岗位页未找到继续沟通入口", target_id=target_id)
            state = _wait_for_conversation(target_id)
            if not state.get("imRoute") or not state.get("hasChatInput"):
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error="existing_conversation_not_verified", history_detail="未确认进入智联 HR 会话输入框，未发送消息", target_id=target_id)
            sent = _fill_and_send_zhilian_message(target_id, message)
            if not sent.get("success"):
                close_tab(target_id)
                return DeliveryResult(False, platform=self.platform, error=sent.get("error", "message_send_failed"), history_detail="智联消息发送未完成或未验证", target_id=target_id)
            return DeliveryResult(True, True, self.platform, None, "智联 HR 会话消息已发送并在页面验证。", target_id=target_id)
        except Exception as exc:
            close_tab(target_id)
            return DeliveryResult(False, platform=self.platform, error="adapter_exception", history_detail=f"智联 HR 会话发送异常：{exc}", target_id=target_id)

    def send_greeting(self, job: dict[str, Any], greeting: str, context: DeliveryContext) -> DeliveryResult:
        # The generic greeting contract is intentionally fail-closed. Callers
        # must opt into start_conversation so AI text cannot be sent here.
        if context.dry_run:
            return dry_run_result(self.platform)
        return DeliveryResult(
            False,
            platform=self.platform,
            error="platform_managed_first_contact",
            history_detail="智联首次沟通由平台默认招呼流程负责，不接受 AI 首条消息；请调用 start_conversation。",
        )
