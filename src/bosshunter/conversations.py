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
from urllib.parse import parse_qs, urlsplit


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

_PLATFORM_EXTERNAL_HOSTS = {
    "boss": ("zhipin.com",),
    "zhilian": ("zhaopin.com",),
    "liepin": ("liepin.com",),
}
_LOCAL_EXTERNAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def normalize_platform_external_url(platform: str, url: Any, *, kind: str) -> str | None:
    """Return only a real, platform-specific external URL.

    Conversation and job links are intentionally validated separately. A
    platform home page, local dashboard URL, generic chat-list entry, or a job
    URL masquerading as a conversation URL must never become a clickable card
    action.
    """
    raw = str(url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not hostname or hostname in _LOCAL_EXTERNAL_HOSTS:
        return None
    allowed_hosts = _PLATFORM_EXTERNAL_HOSTS.get(str(platform or "").lower())
    if allowed_hosts and not any(hostname == allowed or hostname.endswith("." + allowed) for allowed in allowed_hosts):
        return None

    path = (parsed.path or "/").lower()
    query = parse_qs(parsed.query, keep_blank_values=False)
    platform_name = str(platform or "").lower()
    if kind == "conversation":
        if platform_name == "zhilian":
            # refcode=4019 is only the IM entry/list marker. A card requires
            # the concrete sessionId belonging to one HR conversation.
            if hostname != "i.zhaopin.com" or path != "/im" or not query.get("sessionId", [""])[0].strip():
                return None
        elif platform_name == "boss":
            if "chat" not in path and "chat" not in parsed.fragment.lower():
                return None
        elif platform_name == "liepin":
            if not any(marker in path for marker in ("/im", "/message", "/communicate", "/chat")):
                return None
        elif "/job" in path:
            return None
    elif kind == "job":
        if platform_name == "zhilian" and "/job" not in path:
            return None
        if platform_name == "liepin" and "/job/" not in path:
            return None
        if platform_name == "boss" and "/job" not in path:
            return None
    else:
        raise ValueError(f"unsupported external URL kind: {kind}")
    return parsed.geturl()


def _decorate_external_urls(row: dict[str, Any]) -> dict[str, Any]:
    """Expose validated links and explicit reasons to the frontend."""
    result = dict(row)
    platform = str(result.get("platform") or result.get("job_platform") or "").lower()
    raw_conversation_url = result.get("conversation_url")
    raw_job_url = result.get("job_url")
    conversation_url = normalize_platform_external_url(platform, raw_conversation_url, kind="conversation")
    job_url = normalize_platform_external_url(platform, raw_job_url, kind="job")
    result["conversation_url"] = conversation_url
    result["job_url"] = job_url
    result["conversation_url_available"] = bool(conversation_url)
    result["job_url_available"] = bool(job_url)
    result["conversation_url_reason"] = "可打开具体平台 HR 会话" if conversation_url else (
        "平台尚未返回具体 HR 会话地址" if raw_conversation_url else "尚未保存具体 HR 会话地址"
    )
    result["job_url_reason"] = "可打开平台岗位详情" if job_url else (
        "岗位详情地址不是对应招聘平台外链" if raw_job_url else "尚未保存平台岗位详情地址"
    )
    return result


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
            conversation_url TEXT,
            status TEXT NOT NULL DEFAULT 'new',
            pause_reason TEXT,
            interest_score INTEGER,
            last_message_at TEXT,
            last_sync_at TEXT,
            sync_cursor TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        -- A recruiter/platform conversation may be shared by several delivered
        -- jobs.  The local card identity is platform + job_id, so an external
        -- conversation id is a lookup field, not a unique card identity.
        DROP INDEX IF EXISTS uq_conv_external_identity;
        CREATE INDEX IF NOT EXISTS idx_conv_external_identity
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
        DROP INDEX IF EXISTS uq_conv_deleted_external_identity;
        CREATE INDEX IF NOT EXISTS idx_conv_deleted_external_identity
            ON conv_deleted_conversations(user_id, platform, external_conversation_id)
            WHERE external_conversation_id IS NOT NULL
              AND external_conversation_id != '';
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(conv_conversations)").fetchall()}
    if "conversation_url" not in columns:
        conn.execute("ALTER TABLE conv_conversations ADD COLUMN conversation_url TEXT")
    jobs_columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if {"source_platform", "hr_name", "company", "deleted_at"}.issubset(jobs_columns):
        candidates = conn.execute(
            """SELECT id, platform, hr_name, company_id
               FROM conv_conversations
               WHERE (job_id IS NULL OR job_id = '' OR job_id LIKE 'sync:%')
                 AND TRIM(hr_name) <> '' AND TRIM(COALESCE(company_id, '')) <> ''"""
        ).fetchall()
        for candidate in candidates:
            matches = conn.execute(
                """SELECT id FROM jobs
                   WHERE deleted_at IS NULL AND source_platform = ?
                     AND hr_name = ? AND company = ?
                   ORDER BY score DESC, updated_at DESC""",
                (candidate["platform"], candidate["hr_name"], candidate["company_id"]),
            ).fetchall()
            if len(matches) == 1:
                conn.execute(
                    "UPDATE conv_conversations SET job_id = ?, updated_at = ? WHERE id = ?",
                    (str(matches[0]["id"]), utc_now(), candidate["id"]),
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
        raw_conversation_url = conversation.get("conversation_url")
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
            "conversation_url": normalize_platform_external_url(
                platform, raw_conversation_url, kind="conversation"
            ),
            "status": status,
            "pause_reason": conversation.get("pause_reason"),
            "interest_score": conversation.get("interest_score"),
            "updated_at": now,
        }
        existing = self.conn.execute(
            "SELECT * FROM conv_conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if existing:
            # A partial platform snapshot must never erase trusted local/job context.
            preserve_if_empty = {
                "external_conversation_id", "hr_external_id", "hr_name", "hr_title",
                "hr_avatar_url", "company_id", "job_id", "hr_profile_url", "company_url",
                "conversation_url", "pause_reason", "interest_score",
            }
            for key in preserve_if_empty:
                value = fields.get(key)
                if value is None or (isinstance(value, str) and not value.strip()):
                    fields[key] = existing[key]
            # An explicitly supplied invalid URL must clear the stale value;
            # only an omitted/empty snapshot is allowed to preserve it.
            if raw_conversation_url is not None and str(raw_conversation_url).strip():
                fields["conversation_url"] = normalize_platform_external_url(
                    platform, raw_conversation_url, kind="conversation"
                )
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

    def _has_jobs_table(self) -> bool:
        return bool(self.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'").fetchone())

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        if not self._has_jobs_table():
            row = self.conn.execute(
                "SELECT * FROM conv_conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        else:
            row = self.conn.execute(
                """SELECT c.*, j.title AS job_title, j.company AS job_company,
                          j.hr_title AS job_hr_title, j.url AS job_url,
                          j.source_platform AS job_platform, j.score AS job_score,
                          j.score_reason AS job_score_reason, j.status AS job_status
                   FROM conv_conversations c
                   LEFT JOIN jobs j ON j.id = c.job_id
                   WHERE c.id = ?""",
                (conversation_id,),
            ).fetchone()
        return _decorate_external_urls(dict(row)) if row else None

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
        return [_decorate_external_urls(dict(row)) for row in rows]

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
        if self._has_jobs_table():
            job_select = "j.title AS job_title, j.company AS job_company, j.hr_title AS job_hr_title, j.url AS job_url, j.source_platform AS job_platform, j.score AS job_score, j.status AS job_status"
            job_join = "LEFT JOIN jobs j ON j.id = c.job_id"
        else:
            job_select = "NULL AS job_title, NULL AS job_company, NULL AS job_hr_title, NULL AS job_url, NULL AS job_platform, NULL AS job_score, NULL AS job_status"
            job_join = ""
        rows = self.conn.execute(
            f"""SELECT c.*, {job_select},
                       COUNT(m.id) AS message_count,
                       SUM(CASE WHEN m.sender_type = 'hr' THEN 1 ELSE 0 END) AS hr_message_count,
                       SUM(CASE WHEN m.sender_type IN ('user', 'ai') THEN 1 ELSE 0 END) AS user_message_count,
                       SUM(CASE WHEN m.sender_type = 'hr' THEN 1 ELSE 0 END) AS round_count,
                       (SELECT m2.content FROM conv_messages m2
                          WHERE m2.conversation_id = c.id
                          ORDER BY COALESCE(m2.message_time, m2.created_at) DESC, m2.id DESC LIMIT 1) AS last_message_preview
                FROM conv_conversations c
                {job_join}
                LEFT JOIN conv_messages m ON m.conversation_id = c.id
                WHERE c.user_id = ?
                  AND (
                    (c.platform = 'assistant_lab' AND c.id = 'assistant-lab:assistant-lab:default')
                    OR (c.job_id IS NOT NULL AND TRIM(c.job_id) <> '' AND c.job_id NOT LIKE 'sync:%')
                  )
                  AND NOT (c.platform = 'assistant_lab' AND c.id <> 'assistant-lab:assistant-lab:default')
                GROUP BY c.id
                ORDER BY {order_by}""",
            (user_id,),
        ).fetchall()
        return [_decorate_external_urls(dict(row)) for row in rows]

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
