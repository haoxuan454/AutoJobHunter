"""HR conversation persistence primitives.

This module is deliberately separate from the legacy job ``history`` table.
It provides an SQLite-compatible local repository for the first development
phase and keeps the data contract aligned with the MySQL schema shipped in
``docs/mysql_conversation_schema.sql``.

No browser or platform calls are made here. Message ingestion is idempotent
and only advances a sync cursor after the caller has successfully committed
the corresponding messages.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


CONVERSATION_STATUSES = {
    "new",
    "active",
    "waiting_reply",
    "waiting_human",
    "paused_salary",
    "paused_risk",
    "paused_manual",
    "closed",
    "failed",
}


@dataclass(frozen=True)
class IncomingMessage:
    """A normalized message received from a platform adapter."""

    sender_type: str
    content: str
    message_time: str | None = None
    platform_message_id: str | None = None
    source_url: str = ""
    raw_payload: dict[str, Any] | None = None
    is_ai_generated: bool = False
    is_sent: bool = False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def message_content_hash(message: IncomingMessage) -> str:
    """Return a stable content hash for platforms without message IDs."""
    payload = "\x1f".join(
        (
            str(message.sender_type or "").strip(),
            str(message.message_time or "").strip(),
            str(message.content or "").strip(),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def init_conversation_tables(conn: sqlite3.Connection) -> None:
    """Create only the new conversation tables on an existing SQLite DB."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS conv_conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default',
            platform TEXT NOT NULL,
            external_conversation_id TEXT,
            hr_external_id TEXT,
            hr_name TEXT NOT NULL DEFAULT '',
            hr_title TEXT,
            hr_avatar_url TEXT,
            company_id TEXT,
            job_id TEXT,
            hr_profile_url TEXT,
            company_url TEXT,
            status TEXT NOT NULL DEFAULT 'new',
            pause_reason TEXT,
            interest_score INTEGER,
            last_message_at TEXT,
            last_sync_at TEXT,
            sync_cursor TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_conv_external_identity
            ON conv_conversations(user_id, platform, external_conversation_id)
            WHERE external_conversation_id IS NOT NULL
              AND external_conversation_id != '';
        CREATE INDEX IF NOT EXISTS idx_conv_status
            ON conv_conversations(user_id, status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_conv_job
            ON conv_conversations(job_id, updated_at);

        CREATE TABLE IF NOT EXISTS conv_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            platform_message_id TEXT,
            sender_type TEXT NOT NULL,
            content TEXT NOT NULL,
            message_time TEXT,
            content_hash TEXT NOT NULL,
            source_url TEXT,
            raw_payload_json TEXT NOT NULL DEFAULT '{}',
            is_ai_generated INTEGER NOT NULL DEFAULT 0,
            is_sent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conv_conversations(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_conv_platform_message
            ON conv_messages(conversation_id, platform_message_id)
            WHERE platform_message_id IS NOT NULL
              AND platform_message_id != '';
        -- Keep content fallback identity for legacy rows without a platform
        -- ID. Rows with an authoritative platform ID may legitimately share
        -- timestamp and content with another message.
        DROP INDEX IF EXISTS uq_conv_fallback_message;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_conv_fallback_message
            ON conv_messages(conversation_id, sender_type, message_time, content_hash)
            WHERE platform_message_id IS NULL OR platform_message_id = '';
        CREATE INDEX IF NOT EXISTS idx_conv_messages_time
            ON conv_messages(conversation_id, message_time, id);

        CREATE TABLE IF NOT EXISTS conv_sync_cursors (
            conversation_id TEXT PRIMARY KEY,
            cursor_value TEXT,
            last_synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conv_conversations(id)
        );

        CREATE TABLE IF NOT EXISTS conv_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            trigger_message_id INTEGER,
            draft_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'waiting_approval',
            fact_check_status TEXT NOT NULL DEFAULT 'passed',
            prompt_version TEXT NOT NULL DEFAULT 'local-evidence-v1',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conv_conversations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_conv_drafts_conversation
            ON conv_drafts(conversation_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS conv_deleted_conversations (
            conversation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default',
            platform TEXT NOT NULL,
            external_conversation_id TEXT,
            hr_external_id TEXT,
            company_id TEXT,
            job_id TEXT,
            deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_conv_deleted_external_identity
            ON conv_deleted_conversations(user_id, platform, external_conversation_id)
            WHERE external_conversation_id IS NOT NULL
              AND external_conversation_id != '';
        """
    )
    conn.commit()


def _json_payload(payload: dict[str, Any] | None) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"), default=str)


class ConversationRepository:
    """Idempotent repository for the local conversation foundation."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        init_conversation_tables(conn)

    def upsert_conversation(self, conversation: dict[str, Any]) -> dict[str, Any]:
        conversation_id = str(conversation.get("id") or "").strip()
        if not conversation_id:
            raise ValueError("conversation id is required")
        platform = str(conversation.get("platform") or "").strip()
        if not platform:
            raise ValueError("conversation platform is required")
        status = str(conversation.get("status") or "new").strip()
        if status not in CONVERSATION_STATUSES:
            raise ValueError(f"unsupported conversation status: {status}")
        now = utc_now()
        fields = {
            "user_id": str(conversation.get("user_id") or "default"),
            "platform": platform,
            "external_conversation_id": str(conversation.get("external_conversation_id") or ""),
            "hr_external_id": str(conversation.get("hr_external_id") or ""),
            "hr_name": str(conversation.get("hr_name") or ""),
            "hr_title": conversation.get("hr_title"),
            "hr_avatar_url": conversation.get("hr_avatar_url"),
            "company_id": conversation.get("company_id"),
            "job_id": conversation.get("job_id"),
            "hr_profile_url": conversation.get("hr_profile_url"),
            "company_url": conversation.get("company_url"),
            "status": status,
            "pause_reason": conversation.get("pause_reason"),
            "interest_score": conversation.get("interest_score"),
            "updated_at": now,
        }
        existing = self.conn.execute(
            "SELECT id FROM conv_conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if existing:
            assignments = ", ".join(f"{key} = ?" for key in fields)
            self.conn.execute(
                f"UPDATE conv_conversations SET {assignments} WHERE id = ?",
                (*fields.values(), conversation_id),
            )
        else:
            columns = ", ".join(("id", *fields.keys()))
            placeholders = ", ".join("?" for _ in range(len(fields) + 1))
            self.conn.execute(
                f"INSERT INTO conv_conversations ({columns}) VALUES ({placeholders})",
                (conversation_id, *fields.values()),
            )
        self.conn.commit()
        return self.get_conversation(conversation_id) or {}

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM conv_conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return dict(row) if row else None

    def is_deleted(self, conversation_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM conv_deleted_conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return bool(row)

    def append_messages(self, conversation_id: str, messages: Iterable[IncomingMessage]) -> list[dict[str, Any]]:
        if not self.get_conversation(conversation_id):
            raise ValueError(f"conversation does not exist: {conversation_id}")
        inserted: list[dict[str, Any]] = []
        for message in messages:
            content = str(message.content or "").strip()
            sender = str(message.sender_type or "").strip()
            if not content:
                raise ValueError("message content is required")
            if sender not in {"hr", "user", "ai", "system"}:
                raise ValueError(f"unsupported sender type: {sender}")
            msg_hash = message_content_hash(message)
            existing = None
            if message.platform_message_id:
                existing = self.conn.execute(
                    "SELECT * FROM conv_messages WHERE conversation_id = ? AND platform_message_id = ?",
                    (conversation_id, message.platform_message_id),
                ).fetchone()
            # A platform message ID is the authoritative identity. Content-based
            # fallback deduplication is only for legacy messages that have no
            # platform ID; otherwise two legitimate identical replies in one
            # conversation can be collapsed into one row.
            if existing is None and not message.platform_message_id:
                existing = self.conn.execute(
                    """SELECT * FROM conv_messages
                       WHERE conversation_id = ? AND sender_type = ?
                         AND message_time IS ? AND content_hash = ?""",
                    (conversation_id, sender, message.message_time, msg_hash),
                ).fetchone()
            if existing:
                continue
            created_at = utc_now()
            self.conn.execute(
                """INSERT INTO conv_messages (
                    conversation_id, platform_message_id, sender_type, content,
                    message_time, content_hash, source_url, raw_payload_json,
                    is_ai_generated, is_sent, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    conversation_id,
                    message.platform_message_id,
                    sender,
                    content,
                    message.message_time,
                    msg_hash,
                    message.source_url,
                    _json_payload(message.raw_payload),
                    int(message.is_ai_generated),
                    int(message.is_sent),
                    created_at,
                ),
            )
            row = self.conn.execute("SELECT * FROM conv_messages WHERE id = last_insert_rowid()").fetchone()
            inserted.append(dict(row))
        if inserted:
            last_time = max((row["message_time"] or row["created_at"] for row in inserted), default=utc_now())
            self.conn.execute(
                "UPDATE conv_conversations SET last_message_at = ?, updated_at = ? WHERE id = ?",
                (last_time, utc_now(), conversation_id),
            )
        self.conn.commit()
        return inserted

    def get_cursor(self, conversation_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT cursor_value FROM conv_sync_cursors WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()
        return row["cursor_value"] if row else None

    def save_cursor(self, conversation_id: str, cursor_value: str | None) -> None:
        if not self.get_conversation(conversation_id):
            raise ValueError(f"conversation does not exist: {conversation_id}")
        self.conn.execute(
            """INSERT INTO conv_sync_cursors (conversation_id, cursor_value, last_synced_at)
               VALUES (?, ?, ?)
               ON CONFLICT(conversation_id) DO UPDATE SET
                 cursor_value = excluded.cursor_value,
                 last_synced_at = excluded.last_synced_at""",
            (conversation_id, cursor_value, utc_now()),
        )
        self.conn.execute(
            "UPDATE conv_conversations SET sync_cursor = ?, last_sync_at = ?, updated_at = ? WHERE id = ?",
            (cursor_value, utc_now(), utc_now(), conversation_id),
        )
        self.conn.commit()

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM conv_messages WHERE conversation_id = ? ORDER BY message_time, id",
            (conversation_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_drafts(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM conv_drafts WHERE conversation_id = ? ORDER BY created_at DESC, id DESC",
            (conversation_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_conversations(self, user_id: str = "default", sort: str = "recent") -> list[dict[str, Any]]:
        if sort not in {"recent", "frequency", "created"}:
            raise ValueError("unsupported conversation sort")
        order_by = {
            "recent": "COALESCE(c.last_message_at, c.updated_at) DESC, c.id DESC",
            "frequency": "round_count DESC, COALESCE(c.last_message_at, c.updated_at) DESC, c.id DESC",
            "created": "c.created_at DESC, c.id DESC",
        }[sort]
        rows = self.conn.execute(
            f"""SELECT c.*,
                       COUNT(m.id) AS message_count,
                       SUM(CASE WHEN m.sender_type = 'hr' THEN 1 ELSE 0 END) AS hr_message_count,
                       SUM(CASE WHEN m.sender_type IN ('user', 'ai') THEN 1 ELSE 0 END) AS user_message_count,
                       SUM(CASE WHEN m.sender_type = 'hr' THEN 1 ELSE 0 END) AS round_count,
                       (SELECT m2.content FROM conv_messages m2
                          WHERE m2.conversation_id = c.id
                          ORDER BY COALESCE(m2.message_time, m2.created_at) DESC, m2.id DESC LIMIT 1) AS last_message_preview
                FROM conv_conversations c
                LEFT JOIN conv_messages m ON m.conversation_id = c.id
                WHERE c.user_id = ?
                  AND NOT (c.platform = 'assistant_lab' AND c.id <> 'assistant-lab:assistant-lab:default')
                GROUP BY c.id
                ORDER BY {order_by}""",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def update_status(self, conversation_id: str, status: str, reason: str = "") -> dict[str, Any]:
        if status not in CONVERSATION_STATUSES:
            raise ValueError(f"unsupported conversation status: {status}")
        self.conn.execute(
            "UPDATE conv_conversations SET status = ?, pause_reason = ?, updated_at = ? WHERE id = ?",
            (status, reason, utc_now(), conversation_id),
        )
        self.conn.commit()
        row = self.get_conversation(conversation_id)
        if not row:
            raise ValueError(f"conversation does not exist: {conversation_id}")
        return row

    def delete_conversation(self, conversation_id: str, user_id: str = "default") -> dict[str, Any]:
        """Delete local records and retain a tombstone so sync cannot recreate them."""
        row = self.get_conversation(conversation_id)
        if not row or row.get("user_id") != user_id:
            raise ValueError("conversation does not exist")
        self.conn.execute("BEGIN")
        try:
            self.conn.execute(
                """INSERT OR REPLACE INTO conv_deleted_conversations
                   (conversation_id, user_id, platform, external_conversation_id,
                    hr_external_id, company_id, job_id, deleted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["id"], row["user_id"], row["platform"], row.get("external_conversation_id"),
                    row.get("hr_external_id"), row.get("company_id"), row.get("job_id"), utc_now(),
                ),
            )
            self.conn.execute("DELETE FROM conv_drafts WHERE conversation_id = ?", (conversation_id,))
            self.conn.execute("DELETE FROM conv_messages WHERE conversation_id = ?", (conversation_id,))
            self.conn.execute("DELETE FROM conv_sync_cursors WHERE conversation_id = ?", (conversation_id,))
            self.conn.execute("DELETE FROM conv_conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"conversation_id": conversation_id, "deleted": True, "platform_untouched": True}

    def save_draft(self, conversation_id: str, draft_text: str, trigger_message_id: int | None = None) -> dict[str, Any]:
        if not self.get_conversation(conversation_id):
            raise ValueError(f"conversation does not exist: {conversation_id}")
        if not str(draft_text or "").strip():
            raise ValueError("draft text is required")
        cursor = self.conn.execute(
            """INSERT INTO conv_drafts
               (conversation_id, trigger_message_id, draft_text)
               VALUES (?, ?, ?)""",
            (conversation_id, trigger_message_id, str(draft_text).strip()),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM conv_drafts WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)
