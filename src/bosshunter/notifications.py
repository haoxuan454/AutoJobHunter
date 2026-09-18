"""Local notification outbox and opt-in SMTP delivery for human handoff alerts.

This module never sends anything to a recruitment platform. Salary alerts are
written to an idempotent local outbox first; SMTP delivery is only attempted
when the user explicitly enables ``auto_send`` in local settings.
"""

from __future__ import annotations

import json
import smtplib
import sqlite3
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable

import yaml

from bosshunter.config import save_config


def init_notification_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notification_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at TEXT,
            UNIQUE(conversation_id, kind, subject)
        );
        CREATE INDEX IF NOT EXISTS idx_notification_outbox_status
            ON notification_outbox(status, created_at);
        """
    )
    conn.commit()


def _email_section(config: dict[str, Any] | None) -> dict[str, Any]:
    value = ((config or {}).get("notifications") or {}).get("email")
    return dict(value) if isinstance(value, dict) else {}


def load_email_settings(base_dir: Path, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load public email settings and the password from a local ignored file."""
    public = _email_section(config)
    credential_path = Path(base_dir) / "data" / ".email_credentials.yaml"
    private: dict[str, Any] = {}
    if credential_path.exists():
        try:
            parsed = yaml.safe_load(credential_path.read_text(encoding="utf-8")) or {}
            if isinstance(parsed, dict):
                private = parsed
        except (OSError, yaml.YAMLError):
            private = {}
    result = {
        "enabled": bool(public.get("enabled", False)),
        "auto_send": bool(public.get("auto_send", False)),
        "smtp_host": str(public.get("smtp_host") or "smtp.qq.com"),
        "smtp_port": int(public.get("smtp_port") or 465),
        "use_tls": bool(public.get("use_tls", True)),
        "username": str(public.get("username") or ""),
        "from_email": str(public.get("from_email") or ""),
        "to_email": str(public.get("to_email") or ""),
        "password": str(private.get("password") or ""),
    }
    result["password_set"] = bool(result["password"])
    return result


def validate_email_settings(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"enabled", "auto_send", "smtp_host", "smtp_port", "use_tls", "username", "from_email", "to_email", "password"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unsupported email settings: {sorted(unknown)}")
    result = {
        "enabled": bool(value.get("enabled", False)),
        "auto_send": bool(value.get("auto_send", False)),
        "smtp_host": str(value.get("smtp_host") or "").strip(),
        "smtp_port": int(value.get("smtp_port") or 465),
        "use_tls": bool(value.get("use_tls", True)),
        "username": str(value.get("username") or "").strip(),
        "from_email": str(value.get("from_email") or "").strip(),
        "to_email": str(value.get("to_email") or "").strip(),
    }
    if not 1 <= result["smtp_port"] <= 65535:
        raise ValueError("smtp_port must be between 1 and 65535")
    if result["enabled"] and (not result["smtp_host"] or not result["to_email"]):
        raise ValueError("enabled email notifications require smtp_host and to_email")
    return result


def save_email_settings(base_dir: Path, config: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    validated = validate_email_settings(value)
    password = str(value.get("password") or "")
    old = load_email_settings(base_dir, config)
    if not password:
        password = old.get("password", "")
    public_config = dict(config)
    notifications = dict(public_config.get("notifications") or {})
    notifications["email"] = validated
    public_config["notifications"] = notifications
    save_config(public_config, Path(base_dir) / "config.yaml")
    credential_path = Path(base_dir) / "data" / ".email_credentials.yaml"
    credential_path.parent.mkdir(parents=True, exist_ok=True)
    if password:
        credential_path.write_text(yaml.safe_dump({"password": password}, allow_unicode=True), encoding="utf-8")
    elif credential_path.exists():
        credential_path.unlink()
    return load_email_settings(base_dir, public_config)


def enqueue_alert(conn: sqlite3.Connection, *, conversation_id: str, recipient: str, subject: str, body: str, kind: str = "salary") -> dict[str, Any]:
    init_notification_tables(conn)
    conn.execute(
        """INSERT INTO notification_outbox
           (conversation_id, kind, recipient, subject, body)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(conversation_id, kind, subject) DO NOTHING""",
        (conversation_id, kind, recipient, subject, body),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM notification_outbox WHERE conversation_id = ? AND kind = ? AND subject = ?",
        (conversation_id, kind, subject),
    ).fetchone()
    return dict(row)


def list_outbox(conn: sqlite3.Connection, status: str | None = None) -> list[dict[str, Any]]:
    init_notification_tables(conn)
    if status:
        rows = conn.execute("SELECT * FROM notification_outbox WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM notification_outbox ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def send_outbox_item(conn: sqlite3.Connection, item_id: int, settings: dict[str, Any], *, smtp_factory: Callable[..., Any] | None = None) -> dict[str, Any]:
    init_notification_tables(conn)
    row = conn.execute("SELECT * FROM notification_outbox WHERE id = ?", (int(item_id),)).fetchone()
    if not row:
        raise ValueError("notification does not exist")
    if row["status"] == "sent":
        return dict(row)
    password = str(settings.get("password") or "")
    if not settings.get("enabled") or not settings.get("smtp_host") or not settings.get("to_email"):
        raise ValueError("email notification is not fully configured")
    message = EmailMessage()
    message["From"] = settings.get("from_email") or settings.get("username") or settings["to_email"]
    message["To"] = row["recipient"]
    message["Subject"] = row["subject"]
    message.set_content(row["body"])
    factory = smtp_factory or smtplib.SMTP_SSL
    try:
        with factory(settings["smtp_host"], int(settings.get("smtp_port") or 465), timeout=15) as smtp:
            if settings.get("username"):
                smtp.login(settings["username"], password)
            smtp.send_message(message)
    except Exception as exc:
        conn.execute("UPDATE notification_outbox SET status = 'failed', attempts = attempts + 1, last_error = ? WHERE id = ?", (str(exc), item_id))
        conn.commit()
        raise
    conn.execute("UPDATE notification_outbox SET status = 'sent', attempts = attempts + 1, last_error = NULL, sent_at = CURRENT_TIMESTAMP WHERE id = ?", (item_id,))
    conn.commit()
    return dict(conn.execute("SELECT * FROM notification_outbox WHERE id = ?", (item_id,)).fetchone())
