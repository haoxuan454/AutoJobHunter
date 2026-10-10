"""Invalidate automatic drafts when the verified platform thread has changed."""

from __future__ import annotations

from collections.abc import Callable


def _fingerprint(messages: object) -> tuple | None:
    if not isinstance(messages, list):
        return None
    result = []
    for message in messages:
        if not isinstance(message, dict):
            return None
        sender = message.get("sender")
        if sender not in {"hr", "me"}:
            continue
        text = str(message.get("text") or "").strip()
        if not text:
            return None
        result.append((sender, text, str(message.get("message_id") or message.get("id") or ""),
                       str(message.get("message_time") or message.get("timestamp") or "")))
    return tuple(result) if result else None


def guarded_chat_opener(expected: object, *, open_chat: Callable,
                        read_messages: Callable) -> Callable:
    """Keep manual adapters unchanged; check freshness after safe target selection.

    Read only DOM, never reload or send. Missing/malformed snapshots fail closed.
    System receipt changes do not invalidate a draft, authored messages do.
    """
    baseline = _fingerprint(expected)

    def open_verified(target_id: str, row: dict) -> dict:
        if baseline is None:
            return {"status": "automatic_snapshot_unreadable", "success": False}
        opened = open_chat(target_id, row)
        if opened.get("status") != "matched_chat_loaded":
            return opened
        current = _fingerprint(read_messages(target_id, opened))
        if current is None:
            return {"status": "automatic_snapshot_unreadable", "success": False}
        if current != baseline:
            return {"status": "platform_changed_during_generation", "success": False}
        return opened

    return open_verified
