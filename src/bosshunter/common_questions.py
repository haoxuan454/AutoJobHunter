"""De-identified, reusable HR question-and-answer patterns."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from typing import Any

FORBIDDEN_PHRASES = (
    "没做过", "没有做过", "只是听过", "仅仅听过", "比较基础", "没有经历", "没有相关经历",
    "没有相关", "不了解", "换个问题", "无法回答", "不太匹配", "没法生成回复", "还没有给我",
)


def init_common_question_tables(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS common_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_key TEXT NOT NULL UNIQUE,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            source_kind TEXT NOT NULL DEFAULT 'daily_increment',
            occurrence_count INTEGER NOT NULL DEFAULT 1,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_common_questions_updated ON common_questions(updated_at DESC);
        CREATE TABLE IF NOT EXISTS common_question_sources (
            source_key TEXT PRIMARY KEY,
            question_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(question_id) REFERENCES common_questions(id) ON DELETE CASCADE
        );
    """)
    for phrase in FORBIDDEN_PHRASES:
        conn.execute("DELETE FROM common_questions WHERE answer LIKE ?", (f"%{phrase}%",))
    conn.commit()


def _normalize_question(value: str) -> str:
    text = re.sub(r"https?://\S+", "", str(value or "").lower())
    text = re.sub(r"[\u4e00-\u9fff]{1,4}(?:公司|科技|集团|有限公司)", "某公司", text)
    text = re.sub(r"(?:[李王张刘陈赵黄周吴徐孙][\u4e00-\u9fff]{0,2})(?:hr|老板|经理)", "hr", text)
    text = re.sub(r"\d+(?:k|万|元|薪)?", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" ?？。！!")


def _key(question: str) -> str:
    return hashlib.sha256(_normalize_question(question).encode("utf-8")).hexdigest()


def list_common_questions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    init_common_question_tables(conn)
    return [dict(row) for row in conn.execute("SELECT * FROM common_questions ORDER BY updated_at DESC, id DESC").fetchall()]


def upsert_common_question(conn: sqlite3.Connection, question: str, answer: str, source_key: str | None = None) -> dict[str, Any] | None:
    question = str(question or "").strip()
    answer = str(answer or "").strip()
    if not _normalize_question(question) or not answer or any(phrase in answer for phrase in FORBIDDEN_PHRASES):
        return None
    clean_question = _normalize_question(question)
    init_common_question_tables(conn)
    key = _key(clean_question)
    if source_key and conn.execute("SELECT 1 FROM common_question_sources WHERE source_key = ?", (source_key,)).fetchone():
        return None
    row = conn.execute("SELECT * FROM common_questions WHERE question_key = ?", (key,)).fetchone()
    if row:
        conn.execute("UPDATE common_questions SET answer = ?, occurrence_count = occurrence_count + 1, last_seen_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (answer, row["id"]))
    else:
        conn.execute("INSERT INTO common_questions (question_key, question, answer) VALUES (?, ?, ?)", (key, clean_question, answer))
    if source_key:
        question_id = conn.execute("SELECT id FROM common_questions WHERE question_key = ?", (key,)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO common_question_sources (source_key, question_id) VALUES (?, ?)", (source_key, question_id))
    conn.commit()
    return dict(conn.execute("SELECT * FROM common_questions WHERE question_key = ?", (key,)).fetchone())


def delete_common_question(conn: sqlite3.Connection, question_id: int) -> bool:
    init_common_question_tables(conn)
    cur = conn.execute("DELETE FROM common_questions WHERE id = ?", (int(question_id),))
    conn.commit()
    return cur.rowcount > 0


def update_common_question(conn: sqlite3.Connection, question_id: int, question: str, answer: str) -> dict[str, Any]:
    """Edit one reusable pair and persist it in SQLite.

    The reusable bank is intentionally de-identified.  Re-normalising the
    question on edit keeps the same deduplication rules used by ingestion and
    prevents two records from acquiring the same key.
    """
    question = str(question or "").strip()
    answer = str(answer or "").strip()
    clean_question = _normalize_question(question)
    if not clean_question or not answer:
        raise ValueError("问题和参考回复都不能为空")
    if any(phrase in answer for phrase in FORBIDDEN_PHRASES):
        raise ValueError("参考回复包含不允许的自我贬低表达")
    key = _key(clean_question)
    init_common_question_tables(conn)
    current = conn.execute("SELECT id FROM common_questions WHERE id = ?", (int(question_id),)).fetchone()
    if not current:
        raise ValueError("共性问题不存在")
    conflict = conn.execute(
        "SELECT id FROM common_questions WHERE question_key = ? AND id <> ?",
        (key, int(question_id)),
    ).fetchone()
    if conflict:
        raise ValueError("修改后的问题与已有共性问题重复")
    conn.execute(
        "UPDATE common_questions SET question_key = ?, question = ?, answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (key, clean_question, answer, int(question_id)),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM common_questions WHERE id = ?", (int(question_id),)).fetchone()
    return dict(row)
