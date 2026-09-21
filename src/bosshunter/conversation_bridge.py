"""Bridge platform-read conversation snapshots into the durable conversation store.

The bridge is intentionally read-only with respect to recruitment platforms:
it consumes an already extracted message list and only writes local SQLite
state. It never opens a page, clicks a button, or sends a message.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from bosshunter.conversations import ConversationRepository, IncomingMessage
from bosshunter.notification_service import process_hr_message


def _stable_conversation_id(job: dict[str, Any], conversation: dict[str, Any] | None, platform: str) -> str:
    conversation = conversation or {}
    external = str(conversation.get("external_conversation_id") or conversation.get("hr_external_id") or "").strip()
    identity = external or "|".join((str(job.get("id") or ""), str(conversation.get("hr_name") or job.get("hr_name") or ""), str(conversation.get("company") or job.get("company") or "")))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"{platform}:{digest}"


def sync_extracted_messages(
    conn,
    *,
    job: dict[str, Any],
    messages: list[dict[str, Any]],
    conversation: dict[str, Any] | None = None,
    platform: str = "boss",
    base_dir: Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one extracted snapshot and return the local conversation state."""
    conversation = conversation or {}
    repo = ConversationRepository(conn)
    conversation_id = _stable_conversation_id(job, conversation, platform)
    existing = repo.get_conversation(conversation_id)
    record = repo.upsert_conversation({
        "id": conversation_id,
        "user_id": "default",
        "platform": platform,
        "external_conversation_id": str(conversation.get("external_conversation_id") or ""),
        "hr_external_id": str(conversation.get("hr_external_id") or ""),
        "hr_name": str(conversation.get("hr_name") or job.get("hr_name") or ""),
        "hr_title": job.get("hr_title"),
        "job_id": str(job.get("id") or ""),
        "hr_profile_url": str(conversation.get("hr_profile_url") or job.get("url") or ""),
        "company_url": str(conversation.get("company_url") or job.get("url") or ""),
        "status": str((existing or {}).get("status") or "new"),
    })
    incoming: list[IncomingMessage] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        content = str(item.get("text") or item.get("content") or "").strip()
        if not content:
            continue
        sender = str(item.get("sender") or "system")
        sender_type = {"me": "user", "hr": "hr", "system": "system"}.get(sender, "system")
        incoming.append(IncomingMessage(
            sender_type=sender_type,
            content=content,
            message_time=item.get("message_time") or item.get("timestamp"),
            platform_message_id=item.get("message_id") or item.get("id"),
            source_url=str(conversation.get("source_url") or job.get("url") or ""),
            raw_payload=item,
            is_ai_generated=False,
            is_sent=sender == "me",
        ))
    inserted = repo.append_messages(conversation_id, incoming)
    cursor = hashlib.sha256("\x1e".join(f"{item.sender_type}:{item.content}" for item in incoming).encode("utf-8")).hexdigest()
    repo.save_cursor(conversation_id, cursor)

    notifications = []
    # Only classify messages inserted in this snapshot. Previously seen HR
    # messages must never be reprocessed on every polling cycle.
    for item in inserted:
        if item.get("sender_type") != "hr":
            continue
        result = process_hr_message(
            conn,
            conversation_id=conversation_id,
            message=str(item.get("content") or ""),
            message_id=item.get("id") or item.get("platform_message_id"),
            base_dir=base_dir or Path.cwd(),
            config=config or {},
        )
        if result.get("notification"):
            notifications.append(result["notification"])
        record = result.get("conversation") or record
    return {"conversation": record, "inserted": inserted, "notification": notifications[-1] if notifications else None, "notifications": notifications}
