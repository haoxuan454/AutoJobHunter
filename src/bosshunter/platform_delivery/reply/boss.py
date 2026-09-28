"""BOSS-only reply snapshot and verification logic."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

JS_COUNT_OUTGOING_REPLY = r"""
((expectedText) => {
  const normalize = value => String(value || '')
    .replace(/[\u200b-\u200f\ufeff]/g, '').replace(/\s+/g, ' ').trim();
  const expected = normalize(expectedText);
  const chat = document.querySelector('.chat-record');
  if (!chat) return JSON.stringify({success:false, error:'chat_record_missing'});
  const textOf = node => {
    const authored = node.querySelector('.text-content');
    if (authored) return normalize(authored.innerText || authored.textContent);
    const content = node.querySelector(
      '.message-content,.msg-content,.text,.content,.message-text,[class*="message-content"],[class*="msg-content"]'
    );
    return normalize(content ? (content.innerText || content.textContent) : (node.innerText || node.textContent));
  };
  const outgoing = [...chat.querySelectorAll(
    '.message-item.item-myself,.item-myself,.message-item.item-self,[class*="item-my"]'
  )];
  const matches = outgoing.filter(node => {
    const text = textOf(node);
    return text === expected || text.includes(expected);
  }).map(node => {
    const message = node.__vue__ && node.__vue__.$props ? node.__vue__.$props.message : null;
    const rawTime = message && (message.time || message.createdAt || message.createTime);
    const numericTime = Number(rawTime);
    return {
      mid: node.getAttribute('data-mid') || (message && (message.mid || message.id)) || '',
      time: Number.isFinite(numericTime) ? numericTime : null,
      text: textOf(node),
    };
  });
  const domCount = matches.length;
  const vue = chat.__vue__;
  const records = vue && Array.isArray(vue.list$) ? vue.list$ : null;
  const dataCount = records ? records.filter(item => {
    if (!item || !item.isSelf) return false;
    const text = normalize(item.text || item.lastText || item.content || item.message || item.body || '');
    return text === expected || text.includes(expected);
  }).length : 0;
  return JSON.stringify({success:true, chatFound:true, count:Math.max(domCount, dataCount), domCount, dataCount, matches});
})(__EXPECTED_TEXT__)
"""


def snapshot_expression(expected_text: str) -> str:
    """Build the BOSS-specific read-only DOM probe for one reply text."""
    return JS_COUNT_OUTGOING_REPLY.replace("__EXPECTED_TEXT__", json.dumps(expected_text, ensure_ascii=False))


def outgoing_count(snapshot: Any) -> int | None:
    """Return the exact outgoing-message count, or None when the chat is unreadable."""
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(snapshot, dict) or not snapshot.get("success") or not snapshot.get("chatFound"):
        return None
    try:
        return max(int(snapshot.get("count", 0)), 0)
    except (TypeError, ValueError):
        return None


def outgoing_matches(snapshot: Any) -> list[dict[str, Any]]:
    """Return DOM-backed outgoing matches with stable IDs and timestamps."""
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(snapshot, dict) or not snapshot.get("success") or not snapshot.get("chatFound"):
        return []
    matches = snapshot.get("matches")
    if not isinstance(matches, list):
        return []
    return [item for item in matches if isinstance(item, dict)]


def normalize_reconciliation_text(value: Any) -> str:
    """Normalize text used to reconcile a previously uncertain BOSS reply.

    BOSS conversation sync may prepend the platform delivery marker ``送达``
    to an outgoing message.  That marker is metadata, not user-authored text.
    No other prefix is stripped, so a real message cannot be silently changed
    during reconciliation.
    """
    text = re.sub(r"[\u200b-\u200f\ufeff]", "", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^(?:送达|已送达)\s*", "", text, count=1).strip()


def local_message_matches_hash(content: Any, message_hash: str) -> bool:
    """Return whether a locally persisted outgoing message matches an attempt."""
    import hashlib

    expected_hash = str(message_hash or "").strip()
    if not expected_hash:
        return False
    normalized = normalize_reconciliation_text(content)
    return bool(normalized) and hashlib.sha256(normalized.encode("utf-8")).hexdigest() == expected_hash


def send_and_verify(
    target_id: str,
    message: str,
    *,
    read_snapshot: Callable[[str, str], Any],
    send: Callable[[str, str], bool],
    attempts: int = 8,
    interval: float = 0.35,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Send once only after a readable baseline and verify a new outgoing DOM row."""
    expected = " ".join(str(message or "").split())
    if not expected:
        return {"success": False, "verified": False, "error": "message_empty", "action_started": False}
    try:
        before = outgoing_count(read_snapshot(target_id, expected))
    except Exception:
        before = None
    if before is None:
        return {
            "success": False,
            "verified": False,
            "error": "pre_send_chat_snapshot_unavailable",
            "verification": "boss_pre_send_snapshot",
            "action_started": False,
        }
    # Exactly one send attempt; uncertainty afterwards must never trigger retry.
    try:
        action_started = bool(send(target_id, message))
    except Exception as exc:
        # A post-click exception is indistinguishable from a failed click.
        # Conservatively mark it as possibly sent so idempotency blocks retry.
        return {
            "success": False,
            "verified": False,
            "error": "send_action_exception",
            "detail": str(exc)[:200],
            "verification": "boss_new_outgoing_message",
            "action_started": True,
        }
    if not action_started:
        return {"success": False, "verified": False, "error": "send_action_not_started", "action_started": False}
    for attempt in range(max(int(attempts), 1)):
        try:
            after = outgoing_count(read_snapshot(target_id, expected))
        except Exception:
            after = None
        if after is not None and after > before:
            return {
                "success": True,
                "verified": True,
                "verification": "boss_new_outgoing_message",
                "action_started": True,
            }
        if attempt + 1 < attempts:
            sleep(interval)
    return {
        "success": True,
        "verified": False,
        "error": "message_sent_not_verified",
        "verification": "boss_new_outgoing_message",
        "action_started": True,
    }


def send_conversation_reply(
    target_id: str,
    row: dict[str, Any],
    message: str,
    *,
    open_chat: Callable[[str, dict[str, Any]], dict[str, Any]],
    read_snapshot: Callable[[str, str], Any],
    send: Callable[[str, str], bool],
) -> dict[str, Any]:
    try:
        opened = open_chat(target_id, row)
    except Exception as exc:
        return {"success": False, "verified": False, "action_started": False,
                "error": "conversation_open_exception", "detail": str(exc)[:200]}
    if opened.get("status") != "matched_chat_loaded":
        return {"success": False, "verified": False, "action_started": False,
                "error": str(opened.get("status") or "conversation_not_loaded")}
    return send_and_verify(target_id, message, read_snapshot=read_snapshot, send=send)
