"""Local-only AI reply rehearsal storage and orchestration.

This module deliberately has no browser, CDP, platform URL, or sender import.
It writes only to the sandbox database supplied by the web server.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from bosshunter.ai.credentials import AIRequestError, call_anthropic_text, get_ai_api_key
from bosshunter.knowledge import init_knowledge_tables, search_confirmed_facts


def _init(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS lab_sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '模拟 HR 会话',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS lab_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            sender_type TEXT NOT NULL,
            content TEXT NOT NULL,
            retrieved_fact_ids TEXT NOT NULL DEFAULT '',
            generation_mode TEXT NOT NULL DEFAULT 'local_evidence',
            sent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES lab_sessions(id)
        );
        CREATE INDEX IF NOT EXISTS idx_lab_messages_session ON lab_messages(session_id, id);
    """)
    conn.commit()


def open_sandbox(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    _init(conn)
    return conn


def ensure_session(conn: sqlite3.Connection, session_id: str | None = None) -> dict[str, Any]:
    _init(conn)
    session_id = str(session_id or "").strip() or str(uuid4())
    row = conn.execute("SELECT * FROM lab_sessions WHERE id = ?", (session_id,)).fetchone()
    if row:
        return dict(row)
    conn.execute("INSERT INTO lab_sessions (id) VALUES (?)", (session_id,))
    conn.commit()
    return dict(conn.execute("SELECT * FROM lab_sessions WHERE id = ?", (session_id,)).fetchone())


def _local_draft(question: str, facts: list[dict[str, Any]]) -> str:
    if not facts:
        return "这个问题我先结合实际经历确认一下，避免把没有做过的内容说得过于绝对。"
    evidence = "；".join(f"{item['title']}：{str(item['content'])[:180]}" for item in facts[:2])
    return f"我之前确实做过一些相关工作，比较接近的是：{evidence}。如果结合您这边的具体场景，我可以再展开说实施过程和结果。"


def send_message(conn: sqlite3.Connection, knowledge_conn: sqlite3.Connection, config: dict, session_id: str | None, question: str) -> dict[str, Any]:
    question = str(question or "").strip()
    if not question or len(question) > 4000:
        raise ValueError("模拟 HR 问题不能为空且不能超过 4000 字")
    session = ensure_session(conn, session_id)
    facts = search_confirmed_facts(knowledge_conn, question, limit=5)
    draft = _local_draft(question, facts)
    mode = "local_evidence"
    model_error = None
    if get_ai_api_key(config):
        prompt = (
            "你是求职者的本地回复演练助手。只使用给出的个人真实经历，禁止编造公司、数字、薪资或项目结果；"
            "不要提及AI，不要发送消息，只输出自然简短的中文回复。\n"
            f"模拟HR问题：{question}\n个人已确认经历：{facts}\n"
        )
        try:
            candidate = call_anthropic_text(prompt, config, 500, purpose="assistant_lab_reply")
            if str(candidate or "").strip():
                draft, mode = str(candidate).strip()[:2000], "configured_model"
        except AIRequestError as exc:
            model_error = exc.kind
        except Exception:
            model_error = "request_failed"
    conn.execute("INSERT INTO lab_messages (session_id, sender_type, content) VALUES (?, 'hr', ?)", (session["id"], question))
    fact_ids = ",".join(str(item["id"]) for item in facts)
    conn.execute("INSERT INTO lab_messages (session_id, sender_type, content, retrieved_fact_ids, generation_mode, sent) VALUES (?, 'ai', ?, ?, ?, 0)", (session["id"], draft, fact_ids, mode))
    conn.execute("UPDATE lab_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (session["id"],))
    conn.commit()
    return {"session": ensure_session(conn, session["id"]), "messages": list_messages(conn, session["id"]), "retrieved_facts": facts, "sent": False, "generation_mode": mode, "model_error": model_error}


def list_messages(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    _init(conn)
    return [dict(row) for row in conn.execute("SELECT * FROM lab_messages WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()]


def session_payload(conn: sqlite3.Connection, session_id: str | None = None) -> dict[str, Any]:
    session = ensure_session(conn, session_id)
    return {"session": session, "messages": list_messages(conn, session["id"]), "sent": False}


def reset(conn: sqlite3.Connection) -> dict[str, Any]:
    _init(conn)
    conn.execute("DELETE FROM lab_messages")
    conn.execute("DELETE FROM lab_sessions")
    conn.commit()
    return session_payload(conn)
