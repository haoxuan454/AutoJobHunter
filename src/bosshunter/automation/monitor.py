"""Deterministic automatic conversation-monitoring cycle.

The browser/platform adapters stay outside this module.  This boundary only
decides which locally delivered conversations are eligible, invokes one sync
callback per card, generates a reply from that card's messages, and stops on
an unsafe send result.  Keeping the policy pure makes the most dangerous
parts of the automatic workflow testable without touching a real platform.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
from datetime import datetime
from threading import Event
from typing import Any

from bosshunter.automation.scope import (
    DeliveryScopeError,
    SUPPORTED_PLATFORMS,
    normalize_delivery_scope,
    scope_keys,
)


SKIPPED_STATUSES = frozenset({
    "closed",
    "failed",
    "paused",
    "paused_manual",
    "paused_risk",
    "paused_salary",
    "waiting_human",
})
UNSAFE_SEND_STATUSES = frozenset({
    "ambiguous",
    "captcha",
    "login_required",
    "not_loaded",
    "risk",
    "send_not_verified",
    "send_unknown",
    "blocked",
    "rate_limit",
})


def automatic_reply_allowed(config: dict[str, Any] | None) -> bool:
    """Return whether configuration explicitly permits AI platform replies.

    Synchronization is safe to run with automatic replies disabled.  Sending
    requires both an explicit opt-in and the human-confirmation safety gate to
    be off; missing values remain fail-closed.
    """

    monitor = config.get("monitor") if isinstance(config, dict) else None
    if not isinstance(monitor, dict):
        return False
    return (
        monitor.get("auto_reply_hr_questions") is True
        and monitor.get("require_human_confirmation") is not True
    )


def automatic_full_run_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Build an isolated policy config for the explicitly automatic workflow."""

    run_config = deepcopy(config) if isinstance(config, dict) else {}
    monitor = run_config.get("monitor")
    if not isinstance(monitor, dict):
        monitor = {}
    run_config["monitor"] = {
        **monitor,
        "auto_reply_hr_questions": True,
        "require_human_confirmation": False,
    }
    return run_config


def run_monitor_cycle(
    conversations: Iterable[dict[str, Any]],
    *,
    sync_one: Callable[[dict[str, Any]], dict[str, Any]],
    generate_reply: Callable[[dict[str, Any], list[dict[str, Any]]], str | None],
    send_reply: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any] | bool],
    handle_new_hr_message: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None] | None = None,
    auto_reply_enabled: bool = False,
    delivery_scope: Iterable[Any] | None = None,
    stop_event: Event | None = None,
    max_conversations: int | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run one low-frequency, serial automatic reply cycle.

    ``sync_one`` must return a dict containing ``status`` and, on success,
    ``inserted`` plus the current full ``messages`` snapshot.  ``send_reply``
    receives the sync payload so the platform adapter can reuse the verified
    chat target opened during sync instead of rescanning the platform.
    """

    result: dict[str, Any] = {
        "processed": 0,
        "skipped": 0,
        "new_hr_messages": 0,
        "handed_off": 0,
        "replied": 0,
        "failed": 0,
        "stop_reason": None,
        "scope_valid": False,
        "scope_error": None,
        "details": [],
    }
    try:
        normalized_scope = normalize_delivery_scope(delivery_scope)
    except DeliveryScopeError as exc:
        result["stop_reason"] = "delivery_scope_invalid"
        result["scope_error"] = str(exc)
        _detail(result, "", "", "scope_invalid", error=str(exc))
        return result

    result["scope_valid"] = True
    result["delivery_scope"] = normalized_scope
    allowed_scope = scope_keys(normalized_scope)
    event = stop_event or Event()
    ordered = sorted(
        (dict(item) for item in conversations if isinstance(item, dict)),
        key=_activity_sort_key,
        reverse=True,
    )
    if max_conversations is not None:
        try:
            limit = int(max_conversations)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_conversations must be a positive integer") from exc
        if isinstance(max_conversations, bool) or limit < 1:
            raise ValueError("max_conversations must be a positive integer")
        ordered = ordered[:limit]

    for conversation in ordered:
        if event.is_set():
            result["stop_reason"] = "user_stopped"
            break
        conversation_id = str(conversation.get("id") or "").strip()
        platform = str(conversation.get("platform") or "").strip().lower()
        skip_reason = _skip_reason(
            conversation,
            platform=platform,
            allowed_scope=allowed_scope,
        )
        if skip_reason:
            result["skipped"] += 1
            _detail(result, conversation_id, platform, "skipped", reason=skip_reason)
            continue

        result["processed"] += 1
        _log(log, f"automatic conversation monitor: syncing {platform}:{conversation_id}")
        try:
            synced = sync_one(conversation)
        except Exception as exc:  # adapter boundary: one card must not corrupt the cycle
            result["failed"] += 1
            _detail(result, conversation_id, platform, "sync_error", error=str(exc))
            continue
        if not isinstance(synced, dict):
            result["failed"] += 1
            _detail(result, conversation_id, platform, "sync_error", error="sync callback returned a non-dict")
            continue

        status = str(synced.get("status") or "error").strip().lower()
        if status != "synced":
            result["failed"] += 1
            _detail(result, conversation_id, platform, status, error=str(synced.get("error") or ""))
            if status in UNSAFE_SEND_STATUSES:
                result["stop_reason"] = f"sync_{status}"
                break
            continue

        inserted = _inserted_messages(synced)
        new_hr = [item for item in inserted if _sender_type(item) == "hr"]
        result["new_hr_messages"] += len(new_hr)
        messages = [item for item in (synced.get("messages") or []) if isinstance(item, dict)]
        _detail(
            result,
            conversation_id,
            platform,
            "synced",
            inserted=len(inserted),
            new_hr_messages=len(new_hr),
        )
        if not new_hr:
            continue
        handoff: dict[str, Any] | None = None
        if handle_new_hr_message is not None:
            try:
                for message in new_hr:
                    decision = handle_new_hr_message(conversation, message)
                    if isinstance(decision, dict) and decision.get("matched") is True:
                        handoff = decision
                        break
            except Exception as exc:
                result["failed"] += 1
                _detail(
                    result,
                    conversation_id,
                    platform,
                    "handoff_classification_error",
                    error=str(exc),
                )
                continue
        if handoff is not None:
            result["handed_off"] += 1
            _detail(
                result,
                conversation_id,
                platform,
                "human_handoff",
                category=str(handoff.get("category") or "custom"),
                reason=str(handoff.get("summary") or "sensitive topic requires human review"),
            )
            continue
        if not auto_reply_enabled:
            _detail(
                result,
                conversation_id,
                platform,
                "auto_reply_disabled",
                new_hr_messages=len(new_hr),
            )
            continue

        try:
            reply = generate_reply(conversation, messages)
        except Exception as exc:
            result["failed"] += 1
            _detail(result, conversation_id, platform, "reply_generation_error", error=str(exc))
            continue
        reply_text = str(reply or "").strip()
        if not reply_text:
            result["failed"] += 1
            _detail(result, conversation_id, platform, "reply_empty")
            continue

        try:
            send_result = send_reply(conversation, reply_text, synced)
        except Exception as exc:
            result["failed"] += 1
            _detail(result, conversation_id, platform, "send_error", error=str(exc))
            result["stop_reason"] = "send_exception"
            break
        safe = _safe_send(send_result)
        if not safe:
            result["failed"] += 1
            send_status = _send_status(send_result)
            _detail(result, conversation_id, platform, send_status, error=_send_error(send_result))
            result["stop_reason"] = f"send_{send_status}"
            break
        result["replied"] += 1
        _detail(result, conversation_id, platform, "replied")

    return result


def _skip_reason(
    conversation: dict[str, Any],
    *,
    platform: str,
    allowed_scope: set[tuple[str, str]],
) -> str | None:
    if not str(conversation.get("id") or "").strip():
        return "conversation_id_missing"
    if platform not in SUPPORTED_PLATFORMS:
        return "unsupported_platform"
    job_id = str(conversation.get("job_id") or "").strip()
    if not job_id:
        return "job_id_missing"
    if job_id.startswith("sync:"):
        return "legacy_sync_card"
    if (platform, job_id) not in allowed_scope:
        return "outside_automatic_delivery_scope"
    status = str(conversation.get("status") or "active").strip().lower()
    if status in SKIPPED_STATUSES:
        return f"status_{status}"
    if conversation.get("automatic_monitoring_enabled") is False:
        return "automatic_monitoring_disabled"
    return None


def _inserted_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    inserted = payload.get("inserted")
    if inserted is None and isinstance(payload.get("synced"), dict):
        inserted = payload["synced"].get("inserted")
    return [item for item in (inserted or []) if isinstance(item, dict)]


def _sender_type(message: dict[str, Any]) -> str:
    return str(message.get("sender_type") or message.get("sender") or "").strip().lower()


def _safe_send(payload: dict[str, Any] | bool) -> bool:
    if isinstance(payload, bool):
        return payload
    return bool(payload.get("success") and payload.get("verified"))


def _send_status(payload: dict[str, Any] | bool) -> str:
    if isinstance(payload, bool):
        return "unverified" if not payload else "sent"
    return str(payload.get("status") or "unverified").strip().lower()


def _send_error(payload: dict[str, Any] | bool) -> str:
    if isinstance(payload, bool):
        return "platform send was not safely verified" if not payload else ""
    return str(payload.get("error") or "platform send was not safely verified")


def _activity_sort_key(conversation: dict[str, Any]) -> tuple[float, str]:
    candidates = (
        conversation.get("last_activity_at"),
        conversation.get("last_message_at"),
        conversation.get("last_hr_message_at"),
        conversation.get("updated_at"),
        conversation.get("created_at"),
    )
    for value in candidates:
        parsed = _parse_timestamp(value)
        if parsed is not None:
            return parsed, str(conversation.get("id") or "")
    return 0.0, str(conversation.get("id") or "")


def _parse_timestamp(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _detail(result: dict[str, Any], conversation_id: str, platform: str, status: str, **extra: Any) -> None:
    result["details"].append({
        "conversation_id": conversation_id,
        "platform": platform,
        "status": status,
        **extra,
    })


def _log(callback: Callable[[str], None] | None, message: str) -> None:
    if callback:
        callback(message)
