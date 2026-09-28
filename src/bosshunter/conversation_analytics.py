"""Read-only analytics queries for persisted, job-linked HR conversations."""

from __future__ import annotations

import sqlite3
from typing import Any


VISIBLE = """c.job_id IS NOT NULL
    AND TRIM(c.job_id) <> ''
    AND c.job_id NOT LIKE 'sync:%'
    AND c.platform IN ('boss', 'zhilian', 'liepin', '51job')
    AND c.user_id = ?"""


def _rows(
    conn: sqlite3.Connection,
    query: str,
    parameters: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query, parameters).fetchall()]


def build_conversation_analytics(
    conn: sqlite3.Connection,
    user_id: str = "default",
) -> dict[str, Any]:
    """Build dashboard values from local persisted data only."""
    parameters = (str(user_id or "default"),)
    by_status = _rows(conn, f"""SELECT c.status, COUNT(*) AS count
        FROM conv_conversations c WHERE {VISIBLE}
        GROUP BY c.status ORDER BY count DESC""", parameters)
    messages_by_sender = _rows(conn, f"""SELECT m.sender_type, COUNT(*) AS count
        FROM conv_messages m JOIN conv_conversations c ON c.id = m.conversation_id
        WHERE {VISIBLE} GROUP BY m.sender_type ORDER BY count DESC""", parameters)
    by_platform = _rows(conn, f"""SELECT c.platform, COUNT(*) AS count
        FROM conv_conversations c WHERE {VISIBLE}
        GROUP BY c.platform ORDER BY count DESC""", parameters)
    platform_metrics = _rows(conn, f"""SELECT c.platform,
        COUNT(DISTINCT c.id) AS conversations,
        COUNT(DISTINCT CASE WHEN m.sender_type = 'hr' THEN c.id END) AS replied_conversations,
        ROUND(100.0 * COUNT(DISTINCT CASE WHEN m.sender_type = 'hr' THEN c.id END)
            / NULLIF(COUNT(DISTINCT c.id), 0), 1) AS reply_rate
        FROM conv_conversations c LEFT JOIN conv_messages m ON m.conversation_id = c.id
        WHERE {VISIBLE} GROUP BY c.platform ORDER BY conversations DESC""", parameters)
    daily_trend = _rows(conn, f"""WITH scoped_messages AS (
            SELECT m.conversation_id, m.sender_type, m.content,
                   substr(COALESCE(m.message_time, m.created_at), 1, 10) AS day
            FROM conv_messages m JOIN conv_conversations c ON c.id = m.conversation_id
            WHERE {VISIBLE}
        ), first_events AS (
            SELECT conversation_id,
                   MIN(CASE WHEN sender_type = 'user'
                         OR (sender_type = 'system' AND content IN (
                             '平台默认招呼已确认',
                             '历史记录确认已投递；原始招呼正文未保存'
                         )) THEN day END) AS delivery_day,
                   MIN(CASE WHEN sender_type = 'hr' THEN day END) AS reply_day
            FROM scoped_messages GROUP BY conversation_id
        ), message_counts AS (
            SELECT day,
                   SUM(CASE WHEN sender_type = 'user' THEN 1 ELSE 0 END) AS outgoing_messages,
                   SUM(CASE WHEN sender_type = 'hr' THEN 1 ELSE 0 END) AS incoming_messages
            FROM scoped_messages GROUP BY day
        ), all_days AS (
            SELECT day FROM message_counts
            UNION SELECT delivery_day AS day FROM first_events WHERE delivery_day IS NOT NULL
            UNION SELECT reply_day AS day FROM first_events WHERE reply_day IS NOT NULL
        )
        SELECT all_days.day,
               COUNT(DISTINCT CASE WHEN first_events.delivery_day = all_days.day
                   THEN first_events.conversation_id END) AS deliveries,
               COUNT(DISTINCT CASE WHEN first_events.reply_day = all_days.day
                   THEN first_events.conversation_id END) AS replied_conversations,
               COALESCE(message_counts.outgoing_messages, 0) AS outgoing_messages,
               COALESCE(message_counts.incoming_messages, 0) AS incoming_messages
        FROM all_days
        LEFT JOIN message_counts ON message_counts.day = all_days.day
        LEFT JOIN first_events ON first_events.delivery_day = all_days.day
            OR first_events.reply_day = all_days.day
        GROUP BY all_days.day, message_counts.outgoing_messages, message_counts.incoming_messages
        ORDER BY all_days.day""", parameters)

    has_jobs = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
    ).fetchone() is not None
    if has_jobs:
        job_directions = _rows(conn, f"""SELECT
            COALESCE(NULLIF(TRIM(j.title), ''), '未关联岗位') AS label,
            COUNT(DISTINCT c.id) AS conversations,
            COUNT(DISTINCT CASE WHEN m.sender_type = 'hr' THEN c.id END) AS replied_conversations,
            COUNT(CASE WHEN m.sender_type = 'hr' THEN 1 END) AS hr_messages,
            ROUND(100.0 * COUNT(DISTINCT CASE WHEN m.sender_type = 'hr' THEN c.id END)
                / NULLIF(COUNT(DISTINCT c.id), 0), 1) AS reply_rate
            FROM conv_conversations c LEFT JOIN jobs j ON j.id = c.job_id
            LEFT JOIN conv_messages m ON m.conversation_id = c.id
            WHERE {VISIBLE}
            GROUP BY label ORDER BY reply_rate DESC, conversations DESC, label LIMIT 30""", parameters)
    else:
        job_directions = []

    hr_question_keywords = _rows(conn, f"""SELECT m.content, COUNT(*) AS count
        FROM conv_messages m JOIN conv_conversations c ON c.id = m.conversation_id
        WHERE m.sender_type = 'hr' AND TRIM(m.content) <> '' AND {VISIBLE}
        GROUP BY m.content ORDER BY count DESC, m.content LIMIT 20""", parameters)
    has_facts = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='know_facts'"
    ).fetchone() is not None
    confirmed_facts = 0
    if has_facts:
        confirmed_facts = conn.execute(
            "SELECT COUNT(*) FROM know_facts WHERE user_id = ? AND fact_status = 'confirmed' AND public_allowed = 1",
            parameters,
        ).fetchone()[0]

    return {
        "conversations_total": conn.execute(
            f"SELECT COUNT(*) FROM conv_conversations c WHERE {VISIBLE}",
            parameters,
        ).fetchone()[0],
        "messages_total": conn.execute(
            f"SELECT COUNT(*) FROM conv_messages m JOIN conv_conversations c ON c.id = m.conversation_id WHERE {VISIBLE}",
            parameters,
        ).fetchone()[0],
        "confirmed_public_facts": confirmed_facts,
        "salary_paused": conn.execute(
            f"SELECT COUNT(*) FROM conv_conversations c WHERE {VISIBLE} AND c.status = 'paused_salary'",
            parameters,
        ).fetchone()[0],
        "by_status": by_status,
        "messages_by_sender": messages_by_sender,
        "by_platform": by_platform,
        "platform_metrics": platform_metrics,
        "daily_trend": daily_trend,
        "job_directions": job_directions,
        "hr_question_keywords": hr_question_keywords,
    }
