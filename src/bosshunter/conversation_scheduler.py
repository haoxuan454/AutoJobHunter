"""Single-worker conversation scheduling primitives.

The scheduler selects at most one eligible HR conversation per call. It does
not open a browser or send a message; the caller supplies the side-effecting
handler and must still enforce human approval before delivery.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from bosshunter.conversations import CONVERSATION_STATUSES

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
        candidate = self.next_candidate(user_id)
        if not candidate:
            return {"status": "idle", "conversation": None}
        # The caller gets exactly one conversation. No parallel work is started here.
        result = handler(candidate)
        return {"status": "processed", "conversation": candidate, "result": result}
