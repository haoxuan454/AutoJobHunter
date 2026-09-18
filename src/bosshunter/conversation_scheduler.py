"""Single-worker conversation scheduling primitives.

The scheduler selects at most one eligible HR conversation per call. It does
not open a browser or send a message; the caller supplies the side-effecting
handler and must still enforce human approval before delivery.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from bosshunter.conversations import utc_now

ELIGIBLE_STATUSES = {"new", "active", "waiting_reply"}


def init_scheduler_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS conv_scheduler_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            running_conversation_id TEXT,
            lease_until TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT OR IGNORE INTO conv_scheduler_state (id) VALUES (1);
        """
    )
    conn.commit()


class SerialConversationScheduler:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        init_scheduler_tables(conn)

    def next_candidate(self, user_id: str = "default") -> dict[str, Any] | None:
        placeholders = ",".join("?" for _ in ELIGIBLE_STATUSES)
        row = self.conn.execute(
            f"SELECT * FROM conv_conversations WHERE user_id = ? AND status IN ({placeholders}) ORDER BY updated_at ASC, id ASC LIMIT 1",
            (user_id, *sorted(ELIGIBLE_STATUSES)),
        ).fetchone()
        return dict(row) if row else None

    def run_once(self, handler: Callable[[dict[str, Any]], Any], user_id: str = "default") -> dict[str, Any]:
        """Claim one conversation under a SQLite write lock, then release it."""
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            state = self.conn.execute(
                "SELECT running_conversation_id, lease_until FROM conv_scheduler_state WHERE id = 1"
            ).fetchone()
            now = utc_now()
            if state and state["running_conversation_id"] and str(state["lease_until"] or "") > now:
                self.conn.rollback()
                return {"status": "busy", "conversation": None}
            candidate = self.conn.execute(
                """SELECT * FROM conv_conversations
                   WHERE user_id = ? AND status IN ('new', 'active', 'waiting_reply')
                   ORDER BY updated_at ASC, id ASC LIMIT 1""",
                (user_id,),
            ).fetchone()
            if not candidate:
                self.conn.commit()
                return {"status": "idle", "conversation": None}
            candidate = dict(candidate)
            lease = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(timespec="seconds")
            self.conn.execute(
                "UPDATE conv_scheduler_state SET running_conversation_id = ?, lease_until = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (candidate["id"], lease),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        try:
            result = handler(candidate)
            return {"status": "processed", "conversation": candidate, "result": result}
        finally:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute(
                "UPDATE conv_scheduler_state SET running_conversation_id = NULL, lease_until = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = 1 AND running_conversation_id = ?",
                (candidate["id"],),
            )
            self.conn.commit()
