"""独立的智联招聘岗位沟通适配器。"""

import json
from typing import Any

import time

from bosshunter.browser import (
    click_at,
    close_tab,
    evaluate,
    get_page_info,
    get_page_targets,
    navigate,
    new_tab,
    type_text,
    wait_for_load,
)
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
      const hasChatInput = [...document.querySelectorAll(
        '.im-sender__input,.im-sender textarea,.im-sender [contenteditable="true"]'
      )].some(visible);
      const jobDetail = /\/jobdetail\//.test(location.pathname);
      const imRoute = location.hostname === 'i.zhaopin.com' && location.pathname === '/im';
      return JSON.stringify({success:true, url:location.href, modalVisible, jobDetail, hasChatInput,
        imRoute, conversationRoute:imRoute && /\u6d88\u606f|\u6c9f\u901a|\u4f1a\u8bdd/.test(text)});
    })()
    """, timeout=10))


def _conversation_message_snapshot(target_id: str) -> list[dict[str, str]]:
    """Read rendered chat messages only; composer text and page-wide text are excluded."""
    result = parse_result(evaluate(target_id, r"""
    (() => {
      const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
      const visible = el => {
        const rects = el.getClientRects(), style = getComputedStyle(el);
        return rects.length > 0 && style.display !== 'none' && style.visibility !== 'hidden';
      };
      const messages = [...document.querySelectorAll(
        '.im-message,.chat-message,.message-item'
      )]
        .filter(visible)
        .map(node => {
          const classes = [node, ...node.querySelectorAll('[class]')]
            .map(el => String(el.className || '').toLowerCase()).join(' ');
          const sender = /(^|[\s_-])(im-message__bubble--me|item-myself|message-self|msg-self|is-self|my-message|message-mine|from-me|outgoing)([\s_-]|$)/.test(classes)
            ? 'me' : 'unknown';
          const textNode = node.querySelector('.im-msg-text,.msg-text,.text,.message-text');
          return {sender, text:normalize(textNode ? textNode.innerText || textNode.textContent : node.innerText || node.textContent)};
        }).filter(item => item.text);
      return JSON.stringify({success:true,messages});
    })()
    """, timeout=10))
    messages = result.get("messages")
    return messages if isinstance(messages, list) else []


def _zhilian_im_targets() -> list[dict[str, Any]]:
    """Return existing Zhilian IM tabs without opening or navigating tabs."""
    targets: list[dict[str, Any]] = []
    try:
        raw_targets = get_page_targets()
    except Exception:
        raw_targets = []
    for target in raw_targets or []:
        url = str(target.get("url") or "")
        if "i.zhaopin.com" not in url or "/im" not in url:
            continue
        target_id = str(target.get("targetId") or target.get("id") or "").strip()
        if target_id:
            targets.append({"target_id": target_id, "url": url})
    return targets


def _zhilian_conversation_list_snapshot(target_id: str) -> dict[str, Any]:
    """Read the rendered Zhilian conversation list; never clicks or scrolls it."""
    result = parse_result(evaluate(target_id, r"""
    (() => {
      const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return !!(r.width && r.height && s.display !== 'none' && s.visibility !== 'hidden');
      };
      const rows = [...document.querySelectorAll('.im-session-item')]
        .filter(visible)
        .map((row, index) => {
          const text = selector => normalize(row.querySelector(selector)?.innerText || '');
          const item = {
            index,
            hr_name: text('.im-session-item__name'),
            company: text('.im-session-item__company-name'),
            title: text('.im-session-item__job'),
            preview: text('.im-session-item__preview'),
            time: text('.im-session-item__time'),
            unread: text('.im-session-item__badge'),
            active: row.classList.contains('is-active')
          };
          item.signature = [item.hr_name, item.company, item.title, item.preview, item.time].join('|');
          return item;
        });
      const panel = document.querySelector('.im-side-panel__list');
      return JSON.stringify({
        success: location.hostname === 'i.zhaopin.com' && location.pathname === '/im',
        rows,
        loaded_count: rows.length,
        scroll_height: panel ? panel.scrollHeight : 0,
        client_height: panel ? panel.clientHeight : 0
      });
    })()
    """, timeout=10))
    rows = result.get("rows")
    return {
        "success": bool(result.get("success")),
        "rows": rows if isinstance(rows, list) else [],
        "loaded_count": int(result.get("loaded_count") or 0),
        "scroll_height": int(result.get("scroll_height") or 0),
        "client_height": int(result.get("client_height") or 0),
    }


def _zhilian_text_equal(left: str, right: str) -> bool:
    compact = lambda value: "".join(str(value or "").split()).casefold()
    return compact(left) == compact(right)


def _zhilian_company_equal(left: str, right: str) -> bool:
    suffixes = ("有限公司", "有限责任公司", "股份有限公司", "集团有限公司")
    suffixes = ("\u6709\u9650\u516c\u53f8", "\u6709\u9650\u8d23\u4efb\u516c\u53f8", "\u80a1\u4efd\u6709\u9650\u516c\u53f8", "\u96c6\u56e2\u6709\u9650\u516c\u53f8")
    normalize = lambda value: "".join(str(value or "").split()).casefold()
    left_value = normalize(left)
    right_value = normalize(right)
    if left_value == right_value:
        return True
    for suffix in suffixes:
        compact_suffix = normalize(suffix)
        left_base = left_value.removesuffix(compact_suffix)
        right_base = right_value.removesuffix(compact_suffix)
        if left_base and left_base == right_base:
            return True
    return False


def _match_zhilian_conversation_row(row: dict[str, Any], job: dict[str, Any]) -> tuple[bool, str]:
    """Match by HR/company/title, with company-only as an explicitly weak fallback."""
    company = str(job.get("company") or "").strip()
    title = str(job.get("title") or "").strip()
    hr_name = str(job.get("hr_name") or "").strip()
    row_company = str(row.get("company") or "").strip()
    row_title = str(row.get("title") or "").strip()
    row_hr = str(row.get("hr_name") or "").strip()
    if not company or not row_company or not _zhilian_company_equal(company, row_company):
        return False, "none"
    compact_title = "".join(title.split()).casefold()
    compact_row_title = "".join(row_title.split()).casefold()
    title_match = bool(title and row_title and (
        _zhilian_text_equal(title, row_title)
        or compact_title in compact_row_title
        or compact_row_title in compact_title
    ))
    hr_match = bool(hr_name and row_hr and _zhilian_text_equal(hr_name, row_hr))
    if title_match and (not hr_name or hr_match):
        return True, "company_title_hr" if hr_match else "company_title"
    if hr_match:
        return True, "company_hr"
    return True, "company_only"


def _active_zhilian_conversation_snapshot(target_id: str) -> dict[str, Any]:
    """Read the currently rendered Zhilian chat header and message count."""
    result = parse_result(evaluate(target_id, r"""
    (() => {
      const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return !!(r.width && r.height && s.display !== 'none' && s.visibility !== 'hidden');
      };
      const chat = document.querySelector('.im-main-panel__chat');
      if (!chat || !visible(chat)) return JSON.stringify({success:false});
      const text = selector => normalize(chat.querySelector(selector)?.innerText || '');
      const messages = [...chat.querySelectorAll('.im-message,.chat-message,.message-item')]
        .filter(visible)
        .map(node => normalize(node.querySelector('.im-msg-text,.msg-text,.text,.message-text')?.innerText || node.innerText || node.textContent))
        .filter(Boolean);
      return JSON.stringify({success:true, hr_name:text('.im-chat-header__name'), company:text('.im-chat-header__meta-text'), title:text('.im-chat-header__job-title'), message_count:messages.length, messages});
    })()
    """, timeout=10))
    return result if isinstance(result, dict) else {"success": False}


def _reconcile_zhilian_conversation(
    job: dict[str, Any],
    baseline: dict[str, str] | None = None,
    timeout: float = 3.0,
) -> dict[str, Any]:
    """Find a matching rendered session after platform-managed first contact."""
    deadline = time.time() + timeout
    last: dict[str, Any] = {"status": "not_checked", "matched": False, "rows_loaded": 0}
    targets = _zhilian_im_targets()
    if not targets:
        return {"status": "im_unavailable", "matched": False, "rows_loaded": 0}
    while time.time() < deadline:
        for target in targets:
            try:
                snapshot = _zhilian_conversation_list_snapshot(target["target_id"])
            except Exception:
                continue
            rows = snapshot.get("rows") or []
            last = {
                "status": "checked",
                "matched": False,
                "rows_loaded": len(rows),
                "list_scroll_height": snapshot.get("scroll_height", 0),
                "list_client_height": snapshot.get("client_height", 0),
                "target_id": target["target_id"],
            }
            weak_row: tuple[dict[str, Any], str] | None = None
            for row in rows:
                matched, quality = _match_zhilian_conversation_row(row, job)
                if not matched:
                    continue
                if quality == "company_only":
                    weak_row = (row, quality)
                    continue
                signature = str(row.get("signature") or "")
                changed = not baseline or baseline.get(signature) != signature
                last.update({
                    "matched": True,
                    "list_matched": True,
                    "history_readable": False,
                    "match_quality": quality,
                    "changed_since_baseline": changed,
                    "row": row,
                    "status": "matched_changed" if changed else "matched_existing",
                })
                return last
            active = _active_zhilian_conversation_snapshot(target["target_id"])
            if active.get("success"):
                active_row = {
                    "hr_name": active.get("hr_name", ""),
                    "company": active.get("company", ""),
                    "title": active.get("title", ""),
                    "preview": "",
                    "time": "",
                    "message_count": active.get("message_count", 0),
                }
                matched, quality = _match_zhilian_conversation_row(active_row, job)
                if matched:
                    last.update({
                        "matched": True,
                        "list_matched": False,
                        "history_readable": bool(active.get("message_count")),
                        "match_quality": quality,
                        "status": "active_history_match",
                        "row": active_row,
                    })
                    return last
            if weak_row:
                last.update({
                    "status": "matched_company_only",
                    "matched": False,
                    "match_quality": weak_row[1],
                    "row": weak_row[0],
                })
        time.sleep(0.4)
    if last.get("status") == "not_checked":
        last["status"] = "im_unavailable"
    return last


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
    before_messages = _conversation_message_snapshot(target_id)
    before_count = sum(
        1 for item in before_messages
        if item.get("sender") == "me" and " ".join(str(item.get("text") or "").split()) == " ".join(message.split())
    )
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
    expected = " ".join(message.split())
    deadline = time.time() + 8
    first_verified_snapshot: list[dict[str, str]] | None = None
    while time.time() < deadline:
        current_messages = _conversation_message_snapshot(target_id)
        matching_outgoing = sum(
            1 for item in current_messages
            if item.get("sender") == "me" and " ".join(str(item.get("text") or "").split()) == expected
        )
        composer = parse_result(evaluate(target_id, """
        (() => {
          const input = document.querySelector('.im-sender__input,.im-sender textarea,.im-sender [contenteditable="true"]');
          return JSON.stringify({success:!!input, empty:!!input && !(input.value || input.innerText || input.textContent || '').trim()});
        })()
        """, timeout=10))
        if matching_outgoing > before_count and composer.get("empty"):
            if first_verified_snapshot is not None:
                return {"success": True, "verified": True, "verification": "new_outgoing_message_and_empty_composer"}
            first_verified_snapshot = current_messages
            time.sleep(0.8)
            continue
        first_verified_snapshot = None
        time.sleep(0.4)
    return {"success": False, "error": "message_sent_not_verified"}


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
        baseline: dict[str, str] = {}
        for im_target in _zhilian_im_targets():
            try:
                snapshot = _zhilian_conversation_list_snapshot(im_target["target_id"])
            except Exception:
                continue
            for row in snapshot.get("rows") or []:
                signature = str(row.get("signature") or "")
                if signature:
                    baseline[signature] = signature

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
                greeting = str(context.metadata.get("greeting") or "").strip()
                if not greeting:
                    close_tab(target_id)
                    return DeliveryResult(False, platform=self.platform, error="existing_conversation_greeting_missing", history_detail="智联已有 HR 会话已打开，但缺少可发送招呼语；未记为已发送", target_id=target_id)
                sent = _fill_and_send_zhilian_message(target_id, greeting)
                if not sent.get("success"):
                    close_tab(target_id)
                    return DeliveryResult(False, platform=self.platform, error=sent.get("error", "message_send_failed"), history_detail="智联已有 HR 会话的招呼语发送未完成或未验证", target_id=target_id)
                return DeliveryResult(True, True, self.platform, None, "智联已有 HR 会话中的招呼语已发送并在页面验证。", target_id=target_id, delivery_kind="custom_message")

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

            # The modal is Zhilian's authoritative first-contact signal. The
            # following list reconciliation is best-effort and must not turn a
            # confirmed platform send into a false failure when the list is
            # delayed or rendered in another already-open IM tab.
            reconciliation = _reconcile_zhilian_conversation(job, baseline=baseline)
            reconciliation_status = str(reconciliation.get("status") or "not_checked")
            if reconciliation.get("matched"):
                detail = "智联平台默认招呼已确认发送，会话列表已匹配目标 HR/公司/岗位。"
            elif reconciliation_status in {"im_unavailable", "not_checked"}:
                detail = "智联平台默认招呼已确认发送，会话列表暂未可读取，后续可继续同步核验。"
            else:
                detail = "智联平台默认招呼已确认发送，会话列表暂未匹配，不能据此判定发送失败。"
            return DeliveryResult(
                True,
                True,
                self.platform,
                None,
                detail,
                target_id=target_id,
                delivery_kind="platform_default_greeting",
                metadata={
                    "platform_confirmed": True,
                    "conversation_reconciled": bool(reconciliation.get("matched")),
                    "conversation_reconciliation": reconciliation,
                },
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
