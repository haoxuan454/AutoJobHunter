"""Adopt authoritative BOSS message IDs without re-triggering legacy HR text."""

from __future__ import annotations

from bosshunter.platform_delivery.reply.boss import normalize_reconciliation_text


def adopt_legacy_message_ids(conn, conversation_id: str, messages: list[dict]) -> None:
    """Match old no-ID rows one-to-one, only inside the verified conversation.

    Do not merge distinct platform IDs, delete history, or rewrite generated
    reply keys. Legacy direction and authored text must agree; old unknown
    timestamps may be filled from the platform, but known unequal times cannot.
    """
    legacy = conn.execute(
        """SELECT id, sender_type, content, message_time FROM conv_messages
           WHERE conversation_id = ? AND COALESCE(platform_message_id, '') = ''
           ORDER BY id""", (conversation_id,),
    ).fetchall()
    consumed: set[int] = set()
    for item in messages:
        native_id = str(item.get("message_id") or item.get("id") or "").strip()
        if not native_id or conn.execute(
            "SELECT 1 FROM conv_messages WHERE conversation_id = ? AND platform_message_id = ?",
            (conversation_id, native_id),
        ).fetchone():
            continue
        role = {"me": "user", "hr": "hr", "system": "system"}.get(item.get("sender"))
        content = str(item.get("text") or "").strip()
        stamp = item.get("message_time") or item.get("timestamp")
        for old in legacy:
            if old["id"] in consumed or old["sender_type"] != role:
                continue
            old_text = (normalize_reconciliation_text(old["content"])
                        if role == "user" else str(old["content"]).strip())
            if old_text != content or (old["message_time"] and old["message_time"] != stamp):
                continue
            conn.execute(
                """UPDATE conv_messages SET platform_message_id = ?,
                   message_time = COALESCE(message_time, ?) WHERE id = ? AND conversation_id = ?""",
                (native_id, stamp, old["id"], conversation_id),
            )
            consumed.add(old["id"])
            break
