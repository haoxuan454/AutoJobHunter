"""Independent Liepin delivery adapter.

This module intentionally contains only Liepin selectors and success signals.
It does not reuse BOSS or Zhilian DOM logic.
"""

from __future__ import annotations

import json
import time
from typing import Any

from bosshunter.browser import (
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
from .browser_helpers import parse_result


LIEPIN_IM_HOSTS = ("www.liepin.com", "c.liepin.com", "wow.liepin.com")
LIEPIN_IM_PATH_MARKERS = ("/im", "/message", "/communicate", "/chat")
LIEPIN_JOB_ENTRY_SELECTORS = ("a.btn-main", "a.btn-chat", "button.btn-main", "button.btn-chat")
LIEPIN_MESSAGE_INPUT_SELECTORS = (
    "textarea.im-ui-textarea",
    "textarea[placeholder*='Enter']",
    "textarea[placeholder*='消息']",
    "textarea[placeholder*='输入']",
    ".chat-input textarea",
    ".im-input textarea",
    "[contenteditable='true']",
)
LIEPIN_SEND_SELECTORS = (
    "button.im-ui-basic-send-btn",
    "button[class*='send']",
    "button[class*='Send']",
    ".chat-send",
    ".im-send",
)


def _visible_expression() -> str:
    return """const visible = el => {
      const r = el.getBoundingClientRect(), s = getComputedStyle(el);
      return !!(r.width && r.height && s.display !== 'none' && s.visibility !== 'hidden' && s.pointerEvents !== 'none');
    };"""


def _open_liepin_job(job: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    target_id = new_tab(str(job.get("url") or ""), background=True)
    if not target_id:
        return None, {"error": "open_page_failed", "history_detail": "无法打开猎聘岗位页面"}
    info = get_page_info(target_id) or {}
    if str(info.get("url") or "") in {"", "about:blank"}:
        url = str(job.get("url") or "")
        if not url or not navigate(target_id, url):
            close_tab(target_id)
            return None, {"error": "open_page_failed", "history_detail": "猎聘岗位页面未完成导航"}
    if not wait_for_load(target_id, timeout=15):
        close_tab(target_id)
        return None, {"error": "page_load_timeout", "history_detail": "猎聘岗位页面加载超时"}
    return target_id, None


def _liepin_job_snapshot(target_id: str) -> dict[str, Any]:
    result = parse_result(evaluate(target_id, f"""
    (() => {{
      {_visible_expression()}
      const text = e => (e?.innerText || e?.textContent || '').replace(/\\s+/g, ' ').trim();
      const entry = [...document.querySelectorAll({json.dumps(','.join(LIEPIN_JOB_ENTRY_SELECTORS))})].find(visible);
      const title = document.querySelector('.job-title-box .ellipsis-1,h1');
      const company = document.querySelector(".company-info-container .ellipsis-1,div[data-nick='job-detail-company-info'] .ellipsis-1");
      const hr = document.querySelector('.job-card-right-box,.job-recruiter-info,.job-detail-company-box');
      return JSON.stringify({{
        success: location.hostname.endsWith('liepin.com') && /\\/job\\//.test(location.pathname),
        title: text(title), company: text(company), hr_name: text(hr),
        entry_text: text(entry), entry_class: entry ? String(entry.className || '') : '',
        entry_visible: !!entry, body: text(document.body).slice(0, 1200)
      }});
    }})()
    """, timeout=10))
    return result


def _liepin_chat_snapshot(target_id: str) -> dict[str, Any]:
    result = parse_result(evaluate(target_id, f"""
    (() => {{
      {_visible_expression()}
      const text = e => (e?.innerText || e?.textContent || '').replace(/\\s+/g, ' ').trim();
      const inputs = {json.dumps(list(LIEPIN_MESSAGE_INPUT_SELECTORS), ensure_ascii=False)};
      const sends = {json.dumps(list(LIEPIN_SEND_SELECTORS), ensure_ascii=False)};
      const input = inputs.flatMap(s => [...document.querySelectorAll(s)]).find(visible);
      const send = sends.flatMap(s => [...document.querySelectorAll(s)]).find(visible);
      const messages = [...document.querySelectorAll('.im-ui-message-item .im-ui-txt-content,.im-ui-message-item .im-ui-system-tip,.chat-message,.message-item,.im-message,[class*="message"]')]
        .filter(visible)
        .map(node => text(node.querySelector('.message-text,.msg-text,.text') || node))
        .filter(Boolean);
      return JSON.stringify({{success:true, url:location.href, has_input:!!input, has_send:!!send, messages}});
    }})()
    """, timeout=10))
    return result


def _click_liepin_entry(target_id: str) -> dict[str, Any]:
    return parse_result(evaluate(target_id, f"""
    (() => {{
      {_visible_expression()}
      const selectors = {json.dumps(list(LIEPIN_JOB_ENTRY_SELECTORS), ensure_ascii=False)};
      const candidates = selectors.flatMap(s => [...document.querySelectorAll(s)]).filter(visible);
      const target = candidates.find(el => /继续聊|聊一聊|沟通/.test((el.innerText || el.textContent || '').replace(/\\s+/g, '')));
      if (!target) return JSON.stringify({{success:false,error:'chat_entry_missing'}});
      target.scrollIntoView({{block:'center'}});
      target.click();
      return JSON.stringify({{success:true,text:(target.innerText || target.textContent || '').trim(),class_name:String(target.className || '')}});
    }})()
    """, timeout=10))


def _wait_for_liepin_chat(target_id: str, timeout: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    state: dict[str, Any] = {}
    while time.time() < deadline:
        state = _liepin_chat_snapshot(target_id)
        if state.get("has_input") and state.get("has_send"):
            return state
        time.sleep(0.4)
    return state


def _send_liepin_message(target_id: str, message: str) -> dict[str, Any]:
    if not message.strip():
        return {"success": False, "error": "message_empty"}
    before = _liepin_chat_snapshot(target_id).get("messages") or []
    focused = parse_result(evaluate(target_id, f"""
    (() => {{
      {_visible_expression()}
      const selectors = {json.dumps(list(LIEPIN_MESSAGE_INPUT_SELECTORS), ensure_ascii=False)};
      const input = selectors.flatMap(s => [...document.querySelectorAll(s)]).find(visible);
      if (!input) return JSON.stringify({{success:false,error:'message_input_missing'}});
      input.focus();
      return JSON.stringify({{success:true}});
    }})()
    """, timeout=10))
    if not focused.get("success") or not type_text(target_id, message, human=True):
        return {"success": False, "error": "message_input_fill_failed"}
    clicked = parse_result(evaluate(target_id, f"""
    (() => {{
      {_visible_expression()}
      const selectors = {json.dumps(list(LIEPIN_SEND_SELECTORS), ensure_ascii=False)};
      const button = selectors.flatMap(s => [...document.querySelectorAll(s)]).find(visible);
      if (!button) return JSON.stringify({{success:false,error:'message_send_button_missing'}});
      button.click();
      return JSON.stringify({{success:true}});
    }})()
    """, timeout=10))
    if not clicked.get("success"):
        return clicked
    expected = " ".join(message.split())
    deadline = time.time() + 8
    while time.time() < deadline:
        current = _liepin_chat_snapshot(target_id).get("messages") or []
        normalized = [" ".join(str(item).split()) for item in current]
        if expected in normalized and len(current) > len(before):
            return {"success": True, "verified": True}
        time.sleep(0.5)
    return {"success": False, "error": "message_sent_not_verified"}


def _liepin_im_targets() -> list[dict[str, Any]]:
    targets = []
    for target in get_page_targets() or []:
        url = str(target.get("url") or "")
        target_id = str(target.get("targetId") or target.get("id") or "").strip()
        if target_id and any(host in url for host in LIEPIN_IM_HOSTS) and (
            any(marker in url for marker in LIEPIN_IM_PATH_MARKERS) or "c.liepin.com" in url
        ):
            targets.append({"target_id": target_id, "url": url})
    return targets


def _liepin_conversation_list_snapshot(target_id: str) -> dict[str, Any]:
    return parse_result(evaluate(target_id, f"""
    (() => {{
      {_visible_expression()}
      const text = e => (e?.innerText || e?.textContent || '').replace(/\\s+/g, ' ').trim();
      const contactRows = [...document.querySelectorAll('.im-ui-contact-info')];
      const fallbackRows = [...document.querySelectorAll('.im-ui-contact-list-item,.conversation-item,.session-item,.message-list-item,[class*="conversation"],[class*="session"]')]
        .filter(row => !row.querySelector('.im-ui-contact-info'))
        .filter((row, index, items) => items.indexOf(row) === index);
      // Loaded contact rows can live in a transformed hidden layer while the
      // drawer is closed; DOM text is the reliable loaded-state signal.
      const rows = (contactRows.length ? contactRows : fallbackRows).filter(row => text(row));
      const normalizedRows = rows.map((row,index) => ({{
          index,
          text:text(row).slice(0,300),
          class_name:String(row.className || ''),
          hr_name:text(row.querySelector('.im-ui-contact-title-name,.contact-name,.user-name')),
          company_role:text(row.querySelector('.im-ui-contact-title-sub,.contact-company,.company-name')),
          last_message:text(row.querySelector('.im-ui-last-message,.last-message,.message-preview')),
          unread:!!row.querySelector('.im-ui-unread,.ant-badge-count,[class*="unread"]'),
          contact_id:row.querySelector('.im-ui-contact-list-item')?.getAttribute('data-tlg-ext') || null
        }})).filter(row => row.text);
      return JSON.stringify({{success:true,url:location.href,rows:normalizedRows,loaded_count:normalizedRows.length}});
    }})()
    """, timeout=10))


class LiepinDeliveryAdapter:
    platform = "liepin"
    verified = True

    def list_conversations(self) -> list[dict[str, Any]]:
        """Read only the currently loaded Liepin contact DOM.

        Liepin keeps the contact drawer in the user's existing browser page;
        this method deliberately does not navigate, click, or send. Callers
        must treat an empty result as "not currently loaded", not as proof
        that the account has no conversations.
        """
        rows: list[dict[str, Any]] = []
        for target in _liepin_im_targets():
            snapshot = _liepin_conversation_list_snapshot(target["target_id"])
            for row in snapshot.get("rows") or []:
                if isinstance(row, dict):
                    rows.append({**row, "target_id": target["target_id"], "source_url": target["url"]})
        return rows

    def send_greeting(self, job: dict[str, Any], greeting: str, context: DeliveryContext) -> DeliveryResult:
        if context.dry_run:
            return dry_run_result(self.platform)
        target_id, failure = _open_liepin_job(job)
        if failure:
            return DeliveryResult(False, platform=self.platform, error=failure["error"], history_detail=failure["history_detail"])
        try:
            page = _liepin_job_snapshot(target_id)
            if not page.get("success"):
                return DeliveryResult(False, platform=self.platform, error="job_page_unverified", history_detail="猎聘岗位详情页未验证")
            entry = _click_liepin_entry(target_id)
            if not entry.get("success"):
                return DeliveryResult(False, platform=self.platform, error=entry.get("error", "chat_entry_missing"), history_detail="猎聘岗位页未找到可用的聊一聊入口")
            chat = _wait_for_liepin_chat(target_id)
            if not chat.get("has_input") or not chat.get("has_send"):
                return DeliveryResult(False, platform=self.platform, error="chat_input_missing", history_detail="猎聘聊一聊入口已点击，但未找到聊天输入框或发送按钮")
            sent = _send_liepin_message(target_id, greeting)
            if not sent.get("success"):
                return DeliveryResult(False, platform=self.platform, error=sent.get("error", "message_send_failed"), history_detail="猎聘 HR 消息发送未完成或未验证")
            return DeliveryResult(True, True, self.platform, None, "猎聘 HR 招呼语已发送并在页面聊天记录中验证。", target_id=target_id, delivery_kind="custom_message", metadata={"message_sent": True})
        except Exception as exc:
            return DeliveryResult(False, platform=self.platform, error="adapter_exception", history_detail=f"猎聘发送适配器异常：{exc}", target_id=target_id)
        finally:
            close_tab(target_id)
