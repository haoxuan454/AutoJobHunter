"""智联专用的聊天快照、单次发送和发送后验证。"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any


JS_COUNT_OUTGOING_REPLY = r"""
((expectedText) => {
  const normalize = value => String(value || '').replace(/[\u200b-\u200f\ufeff]/g, '').replace(/\s+/g, ' ').trim();
  const chat = document.querySelector('.im-main-panel__chat,.im-message-list,.im-chat-record,.im-chat__content,.im-conversation');
  if (!chat) return JSON.stringify({success:false,chatFound:false,error:'chat_messages_missing'});
  const nodes = [...chat.querySelectorAll('.im-message')].filter(node => !node.parentElement?.closest('.im-message'));
  if (!nodes.length) return JSON.stringify({success:true,chatFound:true,count:0});
  const count = nodes.filter(node => {
    const classes = [node, ...node.querySelectorAll('[class]')].map(el => String(el.className || '').toLowerCase()).join(' ');
    const outgoing = /(^|[\s_-])im-message__bubble--me([\s_-]|$)/.test(classes)
      || /(^|[\s_-])(item-myself|message-self|is-self|my-message|message-mine|outgoing)([\s_-]|$)/.test(classes);
    const body = node.querySelector('.im-msg-text,.msg-text,.text,.message-text') || node;
    return outgoing && normalize(body.innerText || body.textContent).includes(normalize(expectedText));
  }).length;
  return JSON.stringify({success:true,chatFound:true,count});
})(__EXPECTED_TEXT__)
"""


def snapshot_expression(expected_text: str) -> str:
    return JS_COUNT_OUTGOING_REPLY.replace("__EXPECTED_TEXT__", json.dumps(expected_text, ensure_ascii=False))


def outgoing_count(snapshot: Any) -> int | None:
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(snapshot, dict) or not snapshot.get("success") or not snapshot.get("chatFound"):
        return None
    try:
        return max(0, int(snapshot.get("count", 0)))
    except (TypeError, ValueError):
        return None


def send_and_verify(
    target_id: str,
    message: str,
    *,
    read_snapshot: Callable[[str, str], Any],
    send: Callable[[str, str], Any],
    attempts: int = 8,
    interval: float = 0.35,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Require a readable pre-send chat and only ever invoke send once."""
    expected = " ".join(str(message or "").split())
    if not expected:
        return {"success": False, "verified": False, "error": "message_empty", "action_started": False}
    try:
        before = outgoing_count(read_snapshot(target_id, expected))
    except Exception:
        before = None
    if before is None:
        return {
            "success": False, "verified": False,
            "error": "pre_send_chat_snapshot_unavailable",
            "verification": "zhilian_pre_send_snapshot", "action_started": False,
        }
    try:
        result = send(target_id, message)
    except Exception as exc:
        # The callback may raise after the platform accepted the click. Once
        # invoked with a readable pre-send snapshot, conservatively prevent
        # an automatic retry unless the callback explicitly reported no action.
        return {
            "success": False, "verified": False,
            "error": "send_action_exception", "detail": str(exc)[:200], "action_started": True,
        }
    if isinstance(result, dict):
        action_started = bool(result.get("action_started", result.get("success")))
        if not action_started:
            return {**result, "success": False, "verified": False, "action_started": False}
    else:
        action_started = bool(result)
        if not action_started:
            return {"success": False, "verified": False, "error": "send_action_not_started", "action_started": False}

    for attempt in range(max(int(attempts), 1)):
        try:
            after = outgoing_count(read_snapshot(target_id, expected))
        except Exception:
            after = None
        if after is not None and after > before:
            return {
                "success": True, "verified": True, "action_started": True,
                "verification": "zhilian_new_outgoing_message",
            }
        if attempt + 1 < attempts:
            sleep(interval)
    return {
        "success": True, "verified": False, "action_started": True,
        "error": "message_sent_not_verified", "verification": "zhilian_new_outgoing_message",
    }


def send_conversation_reply(
    target_id: str,
    row: dict[str, Any],
    message: str,
    *,
    open_chat: Callable[[str, dict[str, Any]], dict[str, Any]],
    read_snapshot: Callable[[str, str], Any],
    send: Callable[[str, str], Any],
) -> dict[str, Any]:
    try:
        opened = open_chat(target_id, row)
    except Exception as exc:
        return {"success": False, "verified": False, "action_started": False,
                "error": "conversation_open_exception", "detail": str(exc)[:200]}
    if opened.get("status") != "matched_chat_loaded" or not opened.get("success"):
        return {"success": False, "verified": False, "action_started": False,
                "error": str(opened.get("status") or "conversation_not_loaded")}
    return send_and_verify(target_id, message, read_snapshot=read_snapshot, send=send)
