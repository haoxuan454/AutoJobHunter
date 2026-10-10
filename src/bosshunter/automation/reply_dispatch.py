"""Low-frequency automatic replies using the manual flow's verified adapters.

An AI result is only a draft. Recheck local state after the interruptible delay,
claim a durable send key, then let the platform adapter reopen and verify the
exact conversation. Uncertain sends stay blocked rather than being retried.
"""

from __future__ import annotations

import hashlib
import random
from threading import Event
from collections.abc import Callable

from bosshunter.conversations import IncomingMessage
from bosshunter.automation.monitor import SKIPPED_STATUSES
from bosshunter.automation.runner import _delivery_delay


def _authored(messages: list[dict]) -> list[tuple]:
    return [(m.get("id"), m.get("sender_type"), m.get("content"))
            for m in messages if m.get("sender_type") in {"hr", "user", "ai"}]


def dispatch_automatic_reply(
    repo, card: dict, reply: str, synced: dict, *, config: dict,
    stop_event: Event, send: Callable[[dict, str], dict],
    risk_locked: Callable[[], bool],
) -> dict:
    """Send at most once for this HR snapshot; never send a stale AI draft."""
    minimum, maximum = _delivery_delay(config)
    if stop_event.wait(random.uniform(minimum, maximum)):
        return {"status": "skipped", "reason": "user_stopped"}
    cid = str(card.get("id") or "")
    fresh = repo.get_conversation(cid)
    if not fresh or fresh.get("automatic_monitoring_enabled") is False:
        return {"status": "skipped", "reason": "automatic_monitoring_disabled"}
    if str(fresh.get("status") or "active") in SKIPPED_STATUSES:
        return {"status": "skipped", "reason": "conversation_paused"}
    if any(str(fresh.get(key) or "") != str(card.get(key) or "")
           for key in ("id", "platform", "job_id", "user_id")):
        return {"status": "ambiguous", "error": "local conversation identity changed"}
    if str(synced.get("conversation_id") or cid) != cid:
        return {"status": "ambiguous", "error": "sync resolved another conversation"}
    messages = synced.get("messages") or []
    if _authored(repo.list_messages(cid)) != _authored(messages):
        return {"status": "skipped", "reason": "conversation_changed_during_generation"}
    hr = [m for m in messages if m.get("sender_type") == "hr"]
    if not hr:
        return {"status": "blocked", "error": "missing HR reply trigger"}
    if stop_event.is_set() or risk_locked():
        return {"status": "blocked", "error": "automatic send stopped by safety gate"}
    trigger = hr[-1].get("platform_message_id") or hr[-1].get("id") or hr[-1].get("content")
    key = "auto-reply:" + hashlib.sha256(f"{cid}:{trigger}".encode()).hexdigest()
    user_id = str(fresh.get("user_id") or "")
    attempt, claimed = repo.claim_send_attempt(
        user_id=user_id, conversation_id=cid, idempotency_key=key,
        message_hash=hashlib.sha256(reply.encode()).hexdigest(), platform=card["platform"],
        replace_unsent_hash=True,
    )
    if not claimed:
        if attempt.get("status") == "sent" and attempt.get("idempotency_key") == key:
            return {"status": "skipped", "reason": "already_replied"}
        return {"status": "send_unknown", "error": "a prior reply is unresolved; do not retry"}

    def finish(status: str, payload: dict) -> dict:
        repo.update_send_attempt(user_id=user_id, conversation_id=cid,
                                 idempotency_key=key, status=status, response=payload)
        return payload

    try:
        result = send(fresh, reply)
    except Exception:
        return finish("unknown", {"status": "send_unknown", "error": "adapter exception; verify platform before retry"})
    if not isinstance(result, dict):
        return finish("unknown", {"status": "send_unknown", "error": "invalid adapter result"})
    if not result.get("verified"):
        if (result.get("error") == "platform_changed_during_generation"
                and result.get("action_started") is False):
            return finish("not_sent", {**result, "status": "skipped",
                                      "reason": "platform_changed_during_generation"})
        state = "unknown" if result.get("action_started") else "not_sent"
        return finish(state, {**result, "status": "send_unknown" if state == "unknown" else "send_not_verified"})
    try:
        repo.append_messages(cid, [IncomingMessage(
            sender_type="ai", content=reply, message_time=None,
            platform_message_id=key, source_url=str(synced.get("conversation_url") or ""),
            raw_payload={"source": "automatic_conversation_monitor", "platform": card["platform"]},
            is_ai_generated=True, is_sent=True,
        )])
    except Exception:
        return finish("unknown", {"status": "send_unknown", "error": "platform verified but local persistence failed"})
    return finish("sent", {**result, "success": True, "verified": True, "status": "sent"})
