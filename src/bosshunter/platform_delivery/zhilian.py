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
      const nodes = [...document.querySelectorAll('.im-message,.chat-message,.message-item')]
        .filter(visible)
        .filter(node => {
          // Zhilian nests message elements. Only the outer message is a
          // message record; reading both levels duplicates every message.
          // `node.closest('.im-message') === node` is true for both the
          // outer and inner node, so inspect the parent instead.
          return !node.parentElement?.closest('.im-message');
        });
      const messages = nodes.map((node, index) => {
          const classes = [node, ...node.querySelectorAll('[class]')]
            .map(el => String(el.className || '').toLowerCase()).join(' ');
          // Interactive cards contain action labels ("同意/拒绝") in their
          // wrapper text. Persist the semantic card title, not those controls.
          const textNode = node.querySelector(
            '.im-msg-309__title,.im-wechat-exchange-card__title,.im-msg-text,.msg-text,.text,.message-text'
          );
          const isMe = /(^|[\s_-])im-message__bubble--me([\s_-]|$)/.test(classes)
            || /(^|[\s_-])(item-myself|message-self|msg-self|is-self|my-message|message-mine|from-me|outgoing)([\s_-]|$)/.test(classes);
          const isTip = /(^|[\s_-])im-message--tip([\s_-]|$)/.test(classes);
          const isZhilian = node.matches('.im-message') || !!node.querySelector('.im-message');
          const hasZhilianBubble = node.matches('.im-message__bubble') || !!node.querySelector('.im-message__bubble');
          const sender = isTip ? 'system' : (isMe ? 'me' : (isZhilian && hasZhilianBubble ? 'hr' : 'unknown'));
          const timeNode = node.querySelector('time,[datetime],.im-message__time,.message-time,.msg-time');
          const messageId = node.getAttribute('data-message-id') || node.getAttribute('data-msg-id') || node.getAttribute('data-id') || '';
          const text = normalize(textNode ? textNode.innerText || textNode.textContent : node.innerText || node.textContent);
          const messageTime = normalize(timeNode?.innerText || timeNode?.getAttribute('datetime') || '');
          return {sender, text, message_time:messageTime,
            message_id:messageId,
            message_id_is_native:!!messageId,
            // Older builds persisted DOM-position IDs. Keep the exact legacy
            // key briefly so the bridge can migrate those rows in place.
            legacy_message_id:`dom-${index}--${text}`};
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
          const panel = document.querySelector('.im-side-panel__list');
          const panelTop = panel ? panel.getBoundingClientRect().top : 0;
          const item = {
            index,
            position: panel ? Math.round(row.getBoundingClientRect().top - panelTop + panel.scrollTop) : null,
            hr_name: text('.im-session-item__name'),
            company: text('.im-session-item__company-name'),
            title: text('.im-session-item__job'),
            preview: text('.im-session-item__preview'),
            time: text('.im-session-item__time'),
             unread: text('.im-session-item__badge'),
             session_id: row.getAttribute('data-session-id')
               || row.dataset.sessionId
               || row.querySelector('a[href*="sessionId"]')?.href
                    ?.match(/[?&]sessionId=([^&#]+)/)?.[1]
               || '',
             active: row.classList.contains('is-active')
           };
           item.conversation_id = item.session_id || '';
           item.conversation_url = item.session_id
             ? `https://i.zhaopin.com/im?sessionId=${encodeURIComponent(item.session_id)}&refcode=4019`
             : '';
          item.signature = [item.hr_name, item.company, item.title, item.preview, item.time].join('|');
          return item;
        });
      const panel = document.querySelector('.im-side-panel__list');
      return JSON.stringify({
        success: location.hostname === 'i.zhaopin.com' && location.pathname === '/im',
        rows,
        loaded_count: rows.length,
        scroll_top: panel ? panel.scrollTop : 0,
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
        "scroll_top": int(result.get("scroll_top") or 0),
        "scroll_height": int(result.get("scroll_height") or 0),
        "client_height": int(result.get("client_height") or 0),
    }


def _zhilian_list_signature(snapshot: dict[str, Any]) -> tuple[Any, ...]:
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    row_signature = tuple(sorted(
        "|".join(str(row.get(key) or "") for key in (
            "session_id", "signature", "hr_name", "company", "title", "preview", "time",
        ))
        for row in rows if isinstance(row, dict)
    ))
    return (
        int(snapshot.get("scroll_height") or 0),
        int(snapshot.get("client_height") or 0),
        int(snapshot.get("scroll_top") or 0),
        row_signature,
    )


def _wait_for_zhilian_list_stability(
    target_id: str,
    initial: dict[str, Any],
    *,
    settle_seconds: float = 0.25,
    stable_rounds: int = 3,
    max_checks: int = 6,
) -> tuple[dict[str, Any], bool]:
    """Wait boundedly for asynchronous sidebar rows/heights to settle."""
    snapshot = initial
    previous = _zhilian_list_signature(initial)
    stable = 1
    for _ in range(max(0, max_checks)):
        if stable >= max(1, stable_rounds):
            return snapshot, True
        time.sleep(max(0.0, min(float(settle_seconds), 1.0)))
        current = _zhilian_conversation_list_snapshot(target_id)
        if not current.get("success"):
            return snapshot, False
        signature = _zhilian_list_signature(current)
        stable = stable + 1 if signature == previous else 1
        previous = signature
        snapshot = current
    return snapshot, stable >= max(1, stable_rounds)


def _scan_zhilian_conversation_list(
    target_id: str,
    *,
    max_scrolls: int = 8,
    settle_seconds: float = 0.25,
) -> dict[str, Any]:
    """Boundedly reveal lazy-loaded sidebar rows without opening any chat.

    The target platform virtualizes/loads older rows as the sidebar scrolls.
    A card sync therefore needs more than one passive DOM snapshot. Keep this
    scan capped, deduplicate snapshots, and restore the user's prior sidebar
    position before returning. A later caller may open only a uniquely
    matched row through ``_open_zhilian_conversation_row``.
    """
    first = _zhilian_conversation_list_snapshot(target_id)
    if not first.get("success"):
        return {"success": False, "rows": [], "complete": False, "scroll_rounds": 0}

    original_top = int(first.get("scroll_top") or 0)
    rows_by_key: dict[str, dict[str, Any]] = {}

    def collect(snapshot: dict[str, Any]) -> None:
        for row in snapshot.get("rows") or []:
            if not isinstance(row, dict):
                continue
            session_id = str(row.get("session_id") or "").strip()
            signature = str(row.get("signature") or "").strip()
            position = row.get("position")
            if session_id:
                key = f"session:{session_id}"
            elif signature and position is not None:
                key = f"signature:{signature}|position:{position}"
            else:
                key = f"signature:{signature}|index:{row.get('index', '')}"
            if key:
                rows_by_key[key] = row

    collect(first)
    snapshot = first
    rounds = 0
    complete = False
    for _ in range(max(0, min(int(max_scrolls), 12))):
        top = int(snapshot.get("scroll_top") or 0)
        height = int(snapshot.get("scroll_height") or 0)
        client = int(snapshot.get("client_height") or 0)
        max_top = max(0, height - client)
        if max_top <= top + 2:
            snapshot, complete = _wait_for_zhilian_list_stability(
                target_id, snapshot, settle_seconds=settle_seconds,
            )
            collect(snapshot)
            if complete:
                break
            new_max_top = max(
                0,
                int(snapshot.get("scroll_height") or 0) - int(snapshot.get("client_height") or 0),
            )
            if new_max_top > int(snapshot.get("scroll_top") or 0) + 2:
                continue
            break

        result = parse_result(evaluate(target_id, r"""
        (() => {
          const panel = document.querySelector('.im-side-panel__list');
          if (!panel) return JSON.stringify({success:false, status:'scroll_container_missing'});
          const before = panel.scrollTop;
          const step = Math.max(180, Math.floor(panel.clientHeight * 0.72));
          panel.scrollTop = Math.min(panel.scrollTop + step, panel.scrollHeight - panel.clientHeight);
          return JSON.stringify({success:true, before, scroll_top:panel.scrollTop,
            scroll_height:panel.scrollHeight, client_height:panel.clientHeight});
        })()
        """, timeout=10))
        if not result.get("success"):
            break
        rounds += 1
        time.sleep(max(0.0, min(float(settle_seconds), 1.0)))
        snapshot = _zhilian_conversation_list_snapshot(target_id)
        if not snapshot.get("success"):
            break
        collect(snapshot)
    else:
        top = int(snapshot.get("scroll_top") or 0)
        at_bottom = max(0, int(snapshot.get("scroll_height") or 0) - int(snapshot.get("client_height") or 0)) <= top + 2
        if at_bottom:
            snapshot, complete = _wait_for_zhilian_list_stability(
                target_id, snapshot, settle_seconds=settle_seconds,
            )
            collect(snapshot)

    # Scanning is observational; leave the sidebar where the user had it.
    if int(snapshot.get("scroll_top") or 0) != original_top:
        evaluate(target_id, f"""
        (() => {{
          const panel = document.querySelector('.im-side-panel__list');
          if (!panel) return JSON.stringify({{success:false}});
          panel.scrollTop = {original_top};
          return JSON.stringify({{success:true}});
        }})()
        """, timeout=10)

    signature_counts: dict[str, int] = {}
    for row in rows_by_key.values():
        if not row.get("session_id"):
            signature = str(row.get("signature") or "")
            signature_counts[signature] = signature_counts.get(signature, 0) + 1
    rows = []
    for row in rows_by_key.values():
        row = dict(row)
        if not row.get("session_id") and signature_counts.get(str(row.get("signature") or ""), 0) > 1:
            row["identity_ambiguous"] = True
        rows.append(row)

    return {
        "success": True,
        "rows": rows,
        "complete": complete,
        "scroll_rounds": rounds,
        "original_scroll_top": original_top,
        "loaded_count": len(rows_by_key),
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


def _match_zhilian_sync_identity(row: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, str]:
    """Require job-specific identity when opening a sidebar row for sync.

    Delivery/first-contact matching has separate company-scoped rules. This
    stricter helper is only for reading an existing conversation into a local
    job card, where a same-HR/same-company but different-title row is unsafe.
    """
    company = str(expected.get("company") or "").strip()
    actual_company = str(row.get("company") or "").strip()
    title = str(expected.get("title") or "").strip()
    actual_title = str(row.get("title") or "").strip()
    hr_name = str(expected.get("hr_name") or "").strip()
    actual_hr = str(row.get("hr_name") or "").strip()
    if not company or not actual_company or not _zhilian_company_equal(company, actual_company):
        return False, "none"
    if not title or not actual_title:
        return False, "job_title_missing"
    compact_title = "".join(title.split()).casefold()
    compact_actual_title = "".join(actual_title.split()).casefold()
    if not (
        _zhilian_text_equal(title, actual_title)
        or compact_title in compact_actual_title
        or compact_actual_title in compact_title
    ):
        return False, "job_title_mismatch"
    if hr_name and (not actual_hr or not _zhilian_text_equal(hr_name, actual_hr)):
        return False, "hr_mismatch"
    return True, "company_title_hr" if hr_name else "company_title"


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
      const nodes = [...chat.querySelectorAll('.im-message,.chat-message,.message-item')]
        .filter(visible)
        // The rendered Zhilian message has an outer `.im-message` wrapper
        // and an inner `.im-message` text node. Only retain the outer node.
        .filter(node => !node.parentElement?.closest('.im-message'));
      const messages = nodes.map((node, index) => {
        const classes = [node, ...node.querySelectorAll('[class]')]
          .map(el => String(el.className || '').toLowerCase()).join(' ');
        // Use the actual text/card title. Wrapper innerText also includes
        // consent buttons and caused old snapshots to produce several IDs
        // for the same rendered HR card.
        const textNode = node.querySelector(
          '.im-msg-309__title,.im-wechat-exchange-card__title,.im-msg-text,.msg-text,.text,.message-text'
        );
        const timeNode = node.querySelector('time,[datetime],.im-message__time,.message-time,.msg-time');
        const textValue = normalize(textNode?.innerText || textNode?.textContent || node.innerText || node.textContent);
        const messageTime = normalize(timeNode?.innerText || timeNode?.getAttribute('datetime') || '');
        const isMe = /(^|[\s_-])im-message__bubble--me([\s_-]|$)/.test(classes)
          || /(^|[\s_-])(item-myself|message-self|msg-self|is-self|my-message|message-mine|from-me|outgoing)([\s_-]|$)/.test(classes);
        const isTip = /(^|[\s_-])im-message--tip([\s_-]|$)/.test(classes);
        const isZhilian = node.matches('.im-message') || !!node.querySelector('.im-message');
        const hasZhilianBubble = node.matches('.im-message__bubble') || !!node.querySelector('.im-message__bubble');
        const sender = isTip ? 'system' : (isMe ? 'me' : (isZhilian && hasZhilianBubble ? 'hr' : 'unknown'));
        const nativeMessageId = node.getAttribute('data-message-id') || node.getAttribute('data-msg-id') || node.getAttribute('data-id') || '';
        return {sender, text:textValue, message_time:messageTime,
          message_id:nativeMessageId, message_id_is_native:!!nativeMessageId,
          legacy_message_id:`dom-${index}--${textValue}`};
      }).filter(item => item.text);
      const timeline = chat.querySelector('.im-main-panel__timeline');
      const historyEnding = !!chat.querySelector('.im-main-panel__history-tip.is-ending');
      const historyLabel = normalize(chat.querySelector('.im-main-panel__history-tip')?.innerText || '');
      const params = new URL(location.href).searchParams;
      const sessionId = params.get('sessionId') || '';
      return JSON.stringify({success:true, url:location.href, external_conversation_id:sessionId, session_id:sessionId, hr_name:text('.im-chat-header__name'), company:text('.im-chat-header__meta-text'), title:text('.im-chat-header__job-title'), message_count:messages.length, messages, history_complete:historyEnding, history_label:historyLabel, history_scroll_top:timeline?.scrollTop ?? null, history_scroll_height:timeline?.scrollHeight ?? null});
    })()
    """, timeout=10))
    return result if isinstance(result, dict) else {"success": False}


def _load_zhilian_chat_history(
    target_id: str,
    *,
    max_rounds: int = 10,
    stable_rounds: int = 2,
    interval: float = 0.35,
) -> dict[str, Any]:
    """Load rendered history up to the platform's visible history boundary.

    Zhilian lazily fetches older messages when the timeline is scrolled to its
    top. This is a bounded, read-only UI action: it never touches the composer
    or send controls. If the platform does not expose its ending marker, the
    result is explicitly marked incomplete instead of assuming completeness.
    """
    last: dict[str, Any] = {"success": False, "messages": [], "history_complete": False}
    previous_signature: tuple[Any, ...] | None = None
    stable = 0
    rounds = 0
    for rounds in range(1, max(1, max_rounds) + 1):
        evaluate(target_id, r"""
        (() => {
          const timeline = document.querySelector('.im-main-panel__timeline');
          if (timeline && timeline.scrollTop > 0) {
            timeline.scrollTop = 0;
            timeline.dispatchEvent(new Event('scroll', {bubbles:true}));
          }
          return JSON.stringify({success:!!timeline});
        })()
        """, timeout=10)
        if interval > 0:
            time.sleep(interval)
        last = _active_zhilian_conversation_snapshot(target_id)
        if not last.get("success"):
            continue
        messages = last.get("messages") if isinstance(last.get("messages"), list) else []
        signature = (
            last.get("session_id"),
            len(messages),
            last.get("history_scroll_height"),
            tuple(str(item.get("message_id") or "") for item in messages),
        )
        if last.get("history_complete"):
            break
        if signature == previous_signature and (last.get("history_scroll_top") in (0, 0.0, None)):
            stable += 1
        else:
            stable = 0
        if stable >= max(1, stable_rounds):
            break
        previous_signature = signature
    return {**last, "history_rounds": rounds}


def _open_zhilian_conversation_row(
    target_id: str,
    row: dict[str, Any],
    *,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Open one already-rendered Zhilian list row and verify its chat header.

    Rows can be outside the sidebar's visible scroll window even though they
    are already rendered. Locate by stable session id or a unique full-row
    signature, scroll that row into the sidebar viewport, then click it. Never
    fall back to a stale list index: a reordered list could open another HR.
    """
    if bool(row.get("active_chat")):
        expected_session = str(row.get("session_id") or row.get("conversation_id") or "").strip()
        active = _active_zhilian_conversation_snapshot(target_id)
        active_session = str(active.get("session_id") or active.get("external_conversation_id") or "").strip()
        expected = {"hr_name": row.get("expected_hr_name") or "", "company": row.get("expected_company") or "", "title": row.get("expected_title") or ""}
        actual = {"hr_name": active.get("hr_name") or "", "company": active.get("company") or "", "title": active.get("title") or ""}
        if not expected_session or active_session != expected_session:
            return {"status": "active_session_mismatch", "opened": False}
        if not all(str(expected.get(key) or "").strip() for key in ("hr_name", "company", "title")):
            return {"status": "identity_incomplete", "opened": False}
        if not active.get("success"):
            return {"status": "active_chat_unreadable", "opened": False}
        matched, quality = _match_zhilian_sync_identity(actual, expected)
        if not matched:
            return {"status": "active_identity_mismatch", "opened": False}
        return {**active, "status": "matched_chat_loaded", "success": True, "opened": False, "active_chat": True, "match_quality": quality}

    signature = str(row.get("signature") or "")
    session_id = str(row.get("session_id") or row.get("conversation_id") or "")
    if not session_id and bool(row.get("identity_ambiguous")):
        return {"status": "row_ambiguous", "opened": False, "reason": "missing_session_id_and_duplicate_identity"}
    if not session_id and not signature:
        return {"status": "row_identity_missing", "opened": False}
    locate_script = f"""
    (() => {{
      const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
      const visible = el => {{
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return !!(r.width && r.height && s.display !== 'none' && s.visibility !== 'hidden');
      }};
      const rows = [...document.querySelectorAll('.im-session-item')].filter(visible);
      const make = row => [
        row.querySelector('.im-session-item__name')?.innerText || '',
        row.querySelector('.im-session-item__company-name')?.innerText || '',
        row.querySelector('.im-session-item__job')?.innerText || '',
        row.querySelector('.im-session-item__preview')?.innerText || '',
        row.querySelector('.im-session-item__time')?.innerText || ''
      ].map(normalize).join('|');
      const wanted = {json.dumps(signature, ensure_ascii=False)};
      const wantedSession = {json.dumps(session_id, ensure_ascii=False)};
      let matches = wantedSession
        ? rows.filter(item => (item.getAttribute('data-session-id') || item.dataset.sessionId ||
            item.querySelector('a[href*="sessionId"]')?.href?.match(/[?&]sessionId=([^&#]+)/)?.[1] || '') === wantedSession)
        : [];
      if (!matches.length && wanted) matches = rows.filter(item => make(item) === wanted);
      if (!matches.length) return JSON.stringify({{success:false, status:'row_not_found'}});
      if (matches.length !== 1) return JSON.stringify({{success:false, status:'row_ambiguous', count:matches.length}});
      const row = matches[0];
      const panel = document.querySelector('.im-side-panel__list');
      if (!panel || !panel.contains(row)) return JSON.stringify({{success:false, status:'scroll_container_missing'}});
      const before = row.getBoundingClientRect();
      const panelRect = panel.getBoundingClientRect();
      if (before.top < panelRect.top + 8 || before.bottom > panelRect.bottom - 8) {{
        panel.scrollTop += before.top - panelRect.top - (panel.clientHeight - before.height) / 2;
      }}
      const rect = row.getBoundingClientRect();
      const visibleTop = Math.max(panel.getBoundingClientRect().top, 0);
      const visibleBottom = Math.min(panel.getBoundingClientRect().bottom, window.innerHeight);
      if (rect.bottom <= visibleTop || rect.top >= visibleBottom || rect.width <= 0 || rect.height <= 0)
        return JSON.stringify({{success:false, status:'row_not_visible'}});
      return JSON.stringify({{success:true, x:rect.left + rect.width / 2, y:rect.top + rect.height / 2,
        signature:make(row), session_id:wantedSession, scroll_top:panel.scrollTop}});
    }})()
    """
    located: dict[str, Any] = {}
    scroll_rounds = 0
    reset_to_top = False
    max_open_scrolls = 12
    for _ in range(max_open_scrolls + 1):
        located = parse_result(evaluate(target_id, locate_script, timeout=10))
        if located.get("success") or located.get("status") != "row_not_found":
            break
        sidebar = _zhilian_conversation_list_snapshot(target_id)
        top = int(sidebar.get("scroll_top") or 0)
        max_top = max(0, int(sidebar.get("scroll_height") or 0) - int(sidebar.get("client_height") or 0))
        if not sidebar.get("success"):
            break
        if top >= max_top - 2:
            if reset_to_top or top <= 2:
                break
            result = parse_result(evaluate(target_id, r"""
            (() => {
              const panel = document.querySelector('.im-side-panel__list');
              if (!panel) return JSON.stringify({success:false});
              panel.scrollTop = 0;
              panel.dispatchEvent(new Event('scroll', {bubbles:true}));
              return JSON.stringify({success:true});
            })()
            """, timeout=10))
            if not result.get("success"):
                break
            reset_to_top = True
        else:
            result = parse_result(evaluate(target_id, r"""
            (() => {
              const panel = document.querySelector('.im-side-panel__list');
              if (!panel) return JSON.stringify({success:false});
              const before = panel.scrollTop;
              panel.scrollTop = Math.min(before + Math.max(180, Math.floor(panel.clientHeight * 0.72)),
                panel.scrollHeight - panel.clientHeight);
              panel.dispatchEvent(new Event('scroll', {bubbles:true}));
              return JSON.stringify({success:panel.scrollTop > before});
            })()
            """, timeout=10))
            if not result.get("success"):
                break
            scroll_rounds += 1
        time.sleep(0.25)
    if not located.get("success"):
        status = str(located.get("status") or "row_not_found")
        if status == "row_not_found" and scroll_rounds >= max_open_scrolls:
            status = "row_scan_incomplete"
        return {"status": status, "opened": False, "scroll_rounds": scroll_rounds}
    clicked = click_at(target_id, f"{located.get('x')},{located.get('y')}")
    if not clicked:
        return {"status": "click_failed", "opened": False}
    deadline = time.time() + timeout
    last: dict[str, Any] = {"status": "chat_not_loaded", "opened": True}
    while time.time() < deadline:
        active = _active_zhilian_conversation_snapshot(target_id)
        if active.get("success"):
            active_row = {
                "hr_name": active.get("hr_name") or "",
                "company": active.get("company") or "",
                "title": active.get("title") or "",
            }
            expected_row = {
                "hr_name": row.get("hr_name") or "",
                "company": row.get("company") or "",
                "title": row.get("title") or "",
            }
            expected_session = str(row.get("session_id") or row.get("conversation_id") or "").strip()
            active_session = str(active.get("session_id") or "").strip()
            if expected_session and active_session != expected_session:
                last = {
                    **active,
                    "status": "active_session_mismatch" if active_session else "active_session_id_missing",
                    "opened": True,
                }
                time.sleep(0.25)
                continue
            # A row and active header must agree on the strongest available
            # identity. Do not persist a different active conversation.
            matched, quality = _match_zhilian_sync_identity(active_row, expected_row)
            last = {
                **active,
                "status": "active_identity_mismatch" if not matched else "chat_header_matched",
                "opened": True,
                "match_quality": quality,
            }
            if matched:
                history = _load_zhilian_chat_history(target_id)
                history_session_matches = (
                    history.get("session_id") == expected_session
                    if expected_session
                    else not (active_session and history.get("session_id") and active_session != history.get("session_id"))
                )
                if history.get("success") and history_session_matches:
                    history_row = {
                        "hr_name": history.get("hr_name") or "",
                        "company": history.get("company") or "",
                        "title": history.get("title") or "",
                    }
                    history_matches, history_quality = _match_zhilian_sync_identity(history_row, expected_row)
                    if history_matches:
                        return {"status": "matched_chat_loaded", **history, "opened": True, "match_quality": history_quality}
                last = {**history, "status": "history_identity_mismatch", "opened": True}
        time.sleep(0.25)
    return last


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


def _find_existing_zhilian_conversation(
    job: dict[str, Any],
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Find an existing Zhilian conversation without opening a job page."""
    deadline = time.time() + timeout
    last: dict[str, Any] = {"status": "not_found", "matched": False, "rows_loaded": 0}
    targets = _zhilian_im_targets()
    if not targets:
        return {"status": "im_unavailable", "matched": False, "rows_loaded": 0}
    while time.time() < deadline or timeout == 0:
        for target in targets:
            try:
                snapshot = _zhilian_conversation_list_snapshot(target["target_id"])
            except Exception:
                continue
            rows = snapshot.get("rows") or []
            strong_rows: list[tuple[dict[str, Any], str]] = []
            company_rows: list[dict[str, Any]] = []
            for row in rows:
                matched, quality = _match_zhilian_conversation_row(row, job)
                if not matched:
                    continue
                if quality == "company_only":
                    company_rows.append(row)
                else:
                    strong_rows.append((row, quality))
            last = {
                "status": "checked",
                "matched": False,
                "rows_loaded": len(rows),
                "list_scroll_height": snapshot.get("scroll_height", 0),
                "list_client_height": snapshot.get("client_height", 0),
                "target_id": target["target_id"],
            }
            if strong_rows:
                row, quality = strong_rows[0]
                return {
                    **last,
                    "status": "matched_existing",
                    "matched": True,
                    "match_quality": quality,
                    "row": row,
                    "conversation_url": (row.get("conversation_url") or ""),
                }
            if len(company_rows) == 1:
                return {
                    **last,
                    "status": "matched_existing",
                    "matched": True,
                    "match_quality": "company_only_unique",
                    "row": company_rows[0],
                    "conversation_url": (company_rows[0].get("conversation_url") or ""),
                }
            if len(company_rows) > 1:
                last.update({
                    "status": "ambiguous_company_only",
                    "match_quality": "company_only",
                    "candidate_count": len(company_rows),
                })
        if timeout == 0:
            break
        time.sleep(0.3)
    if last.get("status") == "checked":
        last["status"] = "not_found"
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
                return {"success": True, "verified": True, "action_started": True, "verification": "new_outgoing_message_and_empty_composer"}
            first_verified_snapshot = current_messages
            time.sleep(0.8)
            continue
        first_verified_snapshot = None
        time.sleep(0.4)
    return {"success": False, "error": "message_sent_not_verified", "action_started": True}


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
        # Zhilian contact state is company-scoped. Reconcile the rendered IM
        # list before opening the job page so an existing HR is not contacted
        # through the first-contact flow a second time.
        existing = _find_existing_zhilian_conversation(job)
        if existing.get("matched"):
            row = existing.get("row") or {}
            detail = "智联已有 HR 会话，已复用现有会话；本次未重复发送平台招呼语。"
            return DeliveryResult(
                True,
                True,
                self.platform,
                None,
                detail,
                delivery_kind="existing_conversation_reused",
                metadata={
                    "platform_confirmed": False,
                    "conversation_reconciled": True,
                    "existing_conversation": True,
                    "conversation_url": existing.get("conversation_url"),
                    "match_quality": existing.get("match_quality"),
                    "conversation_row": row,
                },
            )
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
