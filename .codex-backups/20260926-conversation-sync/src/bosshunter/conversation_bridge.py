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
    job_id = str(job.get("id") or conversation.get("job_id") or "").strip()
    # A local conversation represents a delivered job, not a platform contact.
    # External conversation IDs may appear only after the first greeting and
    # may be shared by several jobs handled by the same recruiter.
    if job_id and not job_id.startswith("sync:"):
        digest = hashlib.sha256(f"{platform}|delivery|{job_id}".encode("utf-8")).hexdigest()[:24]
        return f"{platform}:delivery:{digest}"
    external = str(conversation.get("external_conversation_id") or conversation.get("hr_external_id") or "").strip()
    hr_name = str(conversation.get("hr_name") or job.get("hr_name") or "").strip()
    company = str(conversation.get("company") or job.get("company") or "").strip()
    identity = external or "|".join((hr_name, company, job_id))
    digest = hashlib.sha256(f"{platform}|{identity}".encode("utf-8")).hexdigest()[:24]
    return f"{platform}:{digest}"


def _job_context(conn, job: dict[str, Any], conversation: dict[str, Any], platform: str) -> dict[str, Any]:
    """Resolve only an actually delivered job; never import arbitrary contacts."""
    job_id = str(job.get("id") or conversation.get("job_id") or "").strip()
    has_jobs = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
    ).fetchone())
    if not has_jobs:
        return {**job, "id": job_id, "_job_match_status": "not_available"}
    if job_id and not job_id.startswith("sync:"):
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND deleted_at IS NULL", (job_id,)
        ).fetchone()
        if row:
            row_data = dict(row)
            source_platform = str(row_data.get("source_platform") or "boss").strip().lower()
            sent = conn.execute(
                "SELECT 1 FROM history WHERE job_id = ? AND action = 'sent' LIMIT 1",
                (job_id,),
            ).fetchone()
            if source_platform == platform and sent:
                return {**job, **row_data, "id": job_id, "_job_match_status": "matched"}
            return {**job, **row_data, "id": "", "_job_match_status": "not_delivered"}

    hr_name = str(conversation.get("hr_name") or job.get("hr_name") or "").strip()
    company = str(conversation.get("company") or job.get("company") or "").strip()
    title = str(conversation.get("title") or conversation.get("job_title") or job.get("title") or "").strip()
    if not (hr_name and company):
        return {**job, "id": "", "_job_match_status": "unmatched"}
    has_history = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'history'"
    ).fetchone())
    conditions = [
        "deleted_at IS NULL",
        "source_platform = ?",
        "hr_name = ?",
        "company = ?",
    ]
    params: list[str] = [platform, hr_name, company]
    # The production database always has history, where 'sent' is the
    # authoritative delivery proof.  Small isolated bridge consumers/tests
    # may only provide a jobs table; keep those usable without weakening the
    # production gate.
    if has_history:
        conditions.append("EXISTS (SELECT 1 FROM history h WHERE h.job_id = jobs.id AND h.action = 'sent')")
    if title:
        conditions.append("title = ?")
        params.append(title)
    rows = conn.execute(
        f"""SELECT * FROM jobs
           WHERE {' AND '.join(conditions)}
           ORDER BY score DESC, updated_at DESC""",
        params,
    ).fetchall()
    if len(rows) == 1:
        return {**job, **dict(rows[0]), "id": str(rows[0]["id"]), "_job_match_status": "matched"}
    return {
        **job,
        "id": "",
        "_job_match_status": "ambiguous" if len(rows) > 1 else "unmatched",
        "_job_candidates": [str(row["id"]) for row in rows],
    }


def reconcile_verified_deliveries(conn, *, user_id: str = "default") -> dict[str, int]:
    """Idempotently project locally verified sends into the conversation store.

    This function reads only SQLite. It deliberately does not open Chrome or
    infer a sent message body from job.greeting/history.detail.
    """
    has_jobs = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
    ).fetchone())
    has_history = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'history'"
    ).fetchone())
    if not (has_jobs and has_history):
        return {"created": 0, "events_inserted": 0, "skipped_deleted": 0}

    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if not {"id", "status", "source_platform", "deleted_at"}.issubset(columns):
        return {"created": 0, "events_inserted": 0, "skipped_deleted": 0}

    repo = ConversationRepository(conn)
    rows = conn.execute(
        """SELECT j.* FROM jobs j
           WHERE j.deleted_at IS NULL
             AND j.status IN ('sent','replied','resume_sent','needs_resume','follow_up_sent')
             AND EXISTS (SELECT 1 FROM history h WHERE h.job_id=j.id AND h.action='sent')
           ORDER BY j.updated_at, j.id"""
    ).fetchall()
    created = events_inserted = skipped_deleted = 0
    for raw in rows:
        job = dict(raw)
        platform = str(job.get("source_platform") or "boss").strip().lower()
        if platform not in {"boss", "zhilian", "liepin", "51job"}:
            continue
        conversation_id = _stable_conversation_id(job, {}, platform)
        tombstone = conn.execute(
            "SELECT 1 FROM conv_deleted_conversations WHERE user_id=? AND platform=? AND job_id=? LIMIT 1",
            (user_id, platform, str(job["id"])),
        ).fetchone()
        if tombstone or repo.is_deleted(conversation_id):
            skipped_deleted += 1
            continue
        existing = repo.get_conversation(conversation_id)
        if existing is None:
            # Preserve a legacy per-job card ID if it already exists. This
            # avoids duplicating older deliveries during the identity change.
            existing = conn.execute(
                "SELECT id FROM conv_conversations WHERE user_id=? AND platform=? AND job_id=? ORDER BY created_at LIMIT 1",
                (user_id, platform, str(job["id"])),
            ).fetchone()
            if existing:
                conversation_id = str(existing["id"])
        record = repo.upsert_conversation({
            "id": conversation_id,
            "user_id": user_id,
            "platform": platform,
            "hr_name": str(job.get("hr_name") or ""),
            "hr_title": str(job.get("hr_title") or job.get("title") or "") or None,
            "company_id": str(job.get("company") or "") or None,
            "job_id": str(job["id"]),
            "status": str((existing or {}).get("status") or "active"),
        })
        if not existing:
            created += 1
        event_id = f"history-sent:{job['id']}"
        inserted = repo.append_messages(conversation_id, [IncomingMessage(
            sender_type="system",
            content="历史记录确认已投递；原始招呼正文未保存",
            platform_message_id=event_id,
            source_url=str(job.get("url") or ""),
            raw_payload={"source": "local_delivery_reconciliation", "action": "sent"},
            is_sent=False,
        )])
        events_inserted += len(inserted)
    return {"created": created, "events_inserted": events_inserted, "skipped_deleted": skipped_deleted}


def _message_snapshot_items(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        content = str(item.get("text") or item.get("content") or "").strip()
        if not content:
            continue
        sender = str(item.get("sender") or item.get("sender_type") or "system").lower()
        sender = {"me": "me", "user": "me", "hr": "hr", "other": "hr", "ai": "ai", "system": "system"}.get(sender, "system")
        normalized.append({**item, "text": content, "sender": sender})
    return normalized
def record_verified_delivery(
    conn,
    *,
    job: dict[str, Any],
    platform: str,
    greeting: str = "",
    delivery_kind: str = "custom_message",
    metadata: dict[str, Any] | None = None,
    message_id: str | None = None,
) -> dict[str, Any]:
    """Create/update a local conversation after a platform delivery was verified."""
    metadata = metadata or {}
    conversation = metadata.get("conversation") or metadata.get("conversation_row") or {}
    if not isinstance(conversation, dict):
        conversation = {}
    external_id = str(
        metadata.get("external_conversation_id")
        or conversation.get("external_conversation_id")
        or conversation.get("contact_id")
        or ""
    ).strip()
    hr_external_id = str(metadata.get("hr_external_id") or conversation.get("hr_external_id") or "").strip()
    normalized = {**conversation, "external_conversation_id": external_id, "hr_external_id": hr_external_id}
    conversation_id = _stable_conversation_id(job, normalized, platform)
    repo = ConversationRepository(conn)
    if repo.is_deleted(conversation_id):
        return {"conversation": None, "inserted": [], "deleted": True}

    record = repo.upsert_conversation({
        "id": conversation_id,
        "user_id": "default",
        "platform": platform,
        "external_conversation_id": external_id,
        "hr_external_id": hr_external_id,
        "hr_name": str(normalized.get("hr_name") or job.get("hr_name") or ""),
        "hr_title": str(normalized.get("hr_title") or job.get("title") or "") or None,
        "company_id": str(normalized.get("company") or job.get("company") or "") or None,
        "job_id": str(job.get("id") or "") or None,
        "hr_profile_url": str(normalized.get("hr_profile_url") or "") or None,
        "company_url": str(normalized.get("company_url") or "") or None,
        # A job/source URL is not a conversation URL.  If the platform did
        # not return a concrete HR-chat URL, leave this field empty so the UI
        # can show an honest disabled action instead of a misleading link.
        "conversation_url": str(normalized.get("conversation_url") or "") or None,
        "interest_score": job.get("score"),
        "status": "active",
    })
    content = str(greeting or "").strip()
    sender_type = "user"
    if delivery_kind == "platform_default_greeting" and not content:
        sender_type = "system"
        content = "平台默认招呼已确认"
    if content:
        source_key = str(message_id or f"send:{job.get('id') or conversation_id}:{delivery_kind}")
        inserted = repo.append_messages(conversation_id, [IncomingMessage(
            sender_type=sender_type,
            content=content,
            platform_message_id=source_key,
            source_url=str(normalized.get("source_url") or job.get("url") or ""),
            raw_payload={"source": "verified_delivery", "delivery_kind": delivery_kind},
            is_sent=sender_type == "user",
        )])
    else:
        inserted = []
    return {"conversation": record, "inserted": inserted, "deleted": False}


def sync_extracted_messages(
    conn,
    *,
    job: dict[str, Any],
    messages: list[dict[str, Any]],
    conversation: dict[str, Any] | None = None,
    platform: str = "boss",
    base_dir: Path | None = None,
    config: dict[str, Any] | None = None,
    local_conversation_id: str | None = None,
) -> dict[str, Any]:
    """Persist one extracted snapshot and return the local conversation state."""
    conversation = conversation or {}
    job = _job_context(conn, job, conversation, platform)
    if job.get("_job_match_status") in {"unmatched", "ambiguous"}:
        return {
            "conversation": None,
            "inserted": [],
            "notification": None,
            "notifications": [],
            "status": job["_job_match_status"],
            "job_candidates": job.get("_job_candidates", []),
        }
    messages = _message_snapshot_items(messages)
    if not messages:
        return {
            "conversation": None,
            "inserted": [],
            "notification": None,
            "notifications": [],
            "status": "empty_messages",
        }
    repo = ConversationRepository(conn)
    # Single-card sync must update that card.  Falling back to the stable
    # platform+job identity keeps direct ingestion and first delivery
    # idempotent while preventing a late external id from creating a second
    # local card.
    conversation_id = str(local_conversation_id or _stable_conversation_id(job, conversation, platform)).strip()
    if repo.is_deleted(conversation_id):
        return {"conversation": None, "inserted": [], "notification": None, "notifications": [], "deleted": True}
    existing = repo.get_conversation(conversation_id)
    record = repo.upsert_conversation({
        "id": conversation_id,
        "user_id": "default",
        "platform": platform,
        "external_conversation_id": str(conversation.get("external_conversation_id") or ""),
        "hr_external_id": str(conversation.get("hr_external_id") or ""),
        "hr_name": str(conversation.get("hr_name") or job.get("hr_name") or ""),
        "hr_title": conversation.get("hr_title") or job.get("hr_title"),
        "job_id": str(job.get("id") or "") or None,
        "hr_profile_url": str(conversation.get("hr_profile_url") or "") or None,
        "company_url": str(conversation.get("company_url") or "") or None,
        "conversation_url": str(conversation.get("conversation_url") or "") or None,
        "interest_score": job.get("score"),
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
    if not incoming:
        return {"conversation": record, "inserted": inserted, "notification": None, "notifications": []}
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
    return {"conversation": record, "inserted": inserted, "notification": notifications[-1] if notifications else None, "notifications": notifications, "status": "synced"}
