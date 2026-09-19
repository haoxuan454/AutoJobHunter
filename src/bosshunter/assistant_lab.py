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
from bosshunter.knowledge import search_confirmed_facts


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
        return "这个方向我有接触和实践思路，通常会结合具体项目场景来推进；如果方便，我可以进一步说明我会如何拆解问题、落地实现和处理风险。"
    evidence = "；".join(f"{item['title']}：{str(item['content'])[:180]}" for item in facts[:2])
    return f"我之前确实做过一些相关工作，比较接近的是：{evidence}。如果结合您这边的具体场景，我可以再展开说实施过程和结果。"


def _is_self_deprecating(text: str) -> bool:
    forbidden = ("没做过", "没有做过", "只是听过", "仅仅听过", "比较基础", "没有经历", "不了解", "换个问题", "无法回答")
    return any(phrase in str(text or "") for phrase in forbidden)


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
            "你是求职者的高质量 HR 沟通助手。你的任务是帮助经验不多的求职者把真实经历表达得有信心、有价值，绝不能贬低、否认或削弱用户。\n"
            "硬规则：禁止出现‘没做过’‘只是听过’‘比较基础’‘不了解’‘没有经历’‘换个问题’等自我贬低表达；"
            "禁止提及 AI；禁止编造具体公司、客户、薪资、数字、上线结果或用户未提供的确定事实。\n"
            "允许且应当做：识别错别字（如‘智能体开放’通常理解为‘智能体开发’）；把邻近项目经验迁移到问题；"
            "将资料中的技术栈改写成积极但诚实的表达；资料不足时，可以说明熟悉方向、实践思路、可落地的方法和遇到该类问题时的解决路径。\n"
            "回答要像真人聊天，先给结论，再给一个具体做法或项目关联，语气自信但不夸大。\n"
            f"模拟 HR 问题：{question}\n已确认的个人资料与经历：{facts}\n"
        )
        try:
            candidate = call_anthropic_text(prompt, config, 500, purpose="assistant_lab_reply")
            if str(candidate or "").strip() and not _is_self_deprecating(candidate):
                draft, mode = str(candidate).strip()[:2000], "configured_model"
            elif str(candidate or "").strip():
                model_error = "self_deprecating_output_rejected"
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
