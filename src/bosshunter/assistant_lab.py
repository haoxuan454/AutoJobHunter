"""Local-only AI reply rehearsal storage and orchestration.

This module deliberately has no browser, CDP, platform URL, or sender import.
It writes only to the sandbox database supplied by the web server.
"""

from __future__ import annotations

import sqlite3
import re
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
        return "这个方向我有接触和实践思路，通常会结合具体项目场景来推进。您更想了解我做过的项目，还是具体的落地方式？"
    titles = "、".join(str(item.get("title") or "相关项目")[:32] for item in facts[:2])
    if any(token in question.lower() for token in ("python", "java", "框架", "技术", "项目")):
        return f"我之前在「{titles}」里接触过相关技术，主要负责把需求拆解、完成接口和业务逻辑，并处理联调及异常问题。您如果想了解具体项目，我可以结合其中一个展开说。"
    return f"我之前在「{titles}」里做过相关实践，主要是把需求拆解后落到具体实现，并跟进联调、异常处理和交付。您可以继续问我具体负责的部分。"


def _is_self_deprecating(text: str) -> bool:
    forbidden = ("没做过", "没有做过", "只是听过", "仅仅听过", "比较基础", "没有经历", "不了解", "换个问题", "无法回答")
    return any(phrase in str(text or "") for phrase in forbidden)


def _is_coaching_meta(text: str) -> bool:
    """Reject tutor/editor commentary that must never reach an HR chat."""
    markers = (
        "我先直接说结论", "我先说结论", "这样讲既", "面试官听到的是",
        "这样回答", "参考回复", "优化话术", "下面是", "作为教练",
        "建议你", "我来帮你", "这段回复", "这个回答",
    )
    return any(marker in str(text or "") for marker in markers)


def _conversation_context(conn: sqlite3.Connection, session_id: str, *, max_messages: int = 12, max_chars: int = 6000) -> str:
    """Return only the bounded history belonging to this rehearsal session."""
    rows = conn.execute(
        "SELECT sender_type, content FROM lab_messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, max_messages),
    ).fetchall()
    lines = []
    for row in reversed(rows):
        speaker = "HR" if row[0] == "hr" else "求职者"
        content = str(row[1] or "").strip()
        if content:
            lines.append(f"{speaker}：{content[:1200]}")
    return "\n".join(lines)[-max_chars:] or "（这是本轮会话的第一条消息）"


def _fact_context(facts: list[dict[str, Any]], *, max_chars: int = 3600) -> str:
    """Expose short, question-oriented evidence instead of dumping documents."""
    chunks = []
    for item in facts[:5]:
        title = str(item.get("title") or "相关经历").strip()[:80]
        content = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()
        chunks.append(f"- {title}：{content[:360]}")
    return "\n".join(chunks)[:max_chars] or "（没有检索到直接相关的已确认资料）"


def _is_document_dump(text: str, facts: list[dict[str, Any]]) -> bool:
    """Reject a candidate that copies a long source passage to the HR."""
    candidate = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(candidate) > 1200:
        return True
    for item in facts:
        source = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()
        if len(source) >= 24 and candidate.count(source) >= 2:
            return True
        compact_source = re.sub(r"[\s，。；、,.!?！？:：；（）()\"'“”‘’]", "", source)
        compact_candidate = re.sub(r"[\s，。；、,.!?！？:：；（）()\"'“”‘’]", "", candidate)
        if len(compact_source) >= 16 and compact_source[:16] in compact_candidate:
            return True
        for size in (100, 80, 60):
            if len(source) >= size and source[:size] in candidate:
                return True
    return False


def send_message(conn: sqlite3.Connection, knowledge_conn: sqlite3.Connection, config: dict, session_id: str | None, question: str) -> dict[str, Any]:
    question = str(question or "").strip()
    if not question or len(question) > 4000:
        raise ValueError("模拟 HR 问题不能为空且不能超过 4000 字")
    session = ensure_session(conn, session_id)
    facts = search_confirmed_facts(knowledge_conn, question, limit=5)
    history = _conversation_context(conn, session["id"])
    draft = _local_draft(question, facts)
    mode = "local_evidence"
    model_error = None
    if get_ai_api_key(config):
        prompt = (
            "你现在就是求职者本人，正在和 HR 聊天。请直接输出一条可以原样发送给 HR 的最终聊天消息。"
            "你不是教练、编辑、旁白或评审，禁止解释你为什么这样回答，禁止输出任何回复策略分析。\n"
            "先判断 HR 当前这一句真正想了解什么，只回答当前问题；必须承接下面同一个会话的历史，不能把无关资料当答案。\n"
            "输出硬规则：只能使用第一人称‘我’，像真人求职者自然聊天；不要出现‘我先直接说结论’、‘这样讲既体现’、"
            "‘面试官听到的是’、‘参考回复’、‘优化话术’、‘建议你’、‘下面是’等 AI 或教练话术；不要使用 Markdown 标题、引号或前后说明。\n"
            "不能贬低或否认求职者，禁止‘没做过’‘只是听过’‘比较基础’‘不了解’‘没有经历’‘换个问题’等表达；"
            "禁止提及 AI，禁止编造公司、客户、薪资、数字、上线结果或资料中没有的确定事实。\n"
            "请把已确认经历转成积极、诚实、口语化的求职者表达；可将相近项目经验迁移到当前问题，强调负责内容、技术动作、排查思路和落地方式。"
            "资料不足时，用‘我接触过/我在相关项目中采用过/我会结合场景落地’表达，不要把不足暴露成自我否定。"
            f"\n同一个 HR 会话的历史（只能使用这一段，不得跨会话）：\n{history}\n"
            f"\nHR 当前问题：{question}\n与当前问题相关的已确认资料短摘录：\n{_fact_context(facts)}\n"
        )
        try:
            candidate = call_anthropic_text(prompt, config, 500, purpose="assistant_lab_reply")
            if str(candidate or "").strip() and not _is_self_deprecating(candidate) and not _is_coaching_meta(candidate) and not _is_document_dump(candidate, facts):
                draft, mode = str(candidate).strip()[:2000], "configured_model"
            elif str(candidate or "").strip():
                model_error = "unsafe_or_irrelevant_output_rejected"
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
