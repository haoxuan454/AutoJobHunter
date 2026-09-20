"""Local-only, round-based AI interview practice.

This module never opens Chrome and never writes to the production conversation
tables.  Job/company information is copied into a session snapshot so later
changes cannot mix one employer into another practice session.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from bosshunter.ai.credentials import AIRequestError, call_anthropic_text, get_ai_api_key
from bosshunter.knowledge import search_confirmed_facts


def _init(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS interview_sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT 'AI 面试练习',
            job_snapshot_json TEXT NOT NULL DEFAULT '{}',
            company_snapshot_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS interview_rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            round_number INTEGER NOT NULL,
            question TEXT NOT NULL,
            question_type TEXT NOT NULL DEFAULT 'project',
            user_answer TEXT NOT NULL DEFAULT '',
            evaluation_json TEXT NOT NULL DEFAULT '{}',
            optimized_answer TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(session_id, round_number),
            FOREIGN KEY(session_id) REFERENCES interview_sessions(id)
        );
        CREATE INDEX IF NOT EXISTS idx_interview_rounds_session ON interview_rounds(session_id, round_number);
    """)
    conn.commit()


def open_practice(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    _init(conn)
    return conn


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def _payload(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    session = _row(conn.execute("SELECT * FROM interview_sessions WHERE id = ?", (session_id,)).fetchone())
    rounds = [_row(row) for row in conn.execute("SELECT * FROM interview_rounds WHERE session_id = ? ORDER BY round_number", (session_id,)).fetchall()]
    for item in rounds:
        item["evaluation"] = json.loads(item.pop("evaluation_json") or "{}")
    if session:
        session["job_snapshot"] = json.loads(session.pop("job_snapshot_json") or "{}")
        session["company_snapshot"] = json.loads(session.pop("company_snapshot_json") or "{}")
    return {"session": session, "rounds": rounds}


def create_session(conn: sqlite3.Connection, job: dict[str, Any] | None = None) -> dict[str, Any]:
    _init(conn)
    job = dict(job or {})
    session_id = str(uuid4())
    company = {key: job.get(key) for key in ("company", "company_industry", "company_size") if job.get(key)}
    conn.execute("INSERT INTO interview_sessions (id, title, job_snapshot_json, company_snapshot_json) VALUES (?, ?, ?, ?)", (session_id, f"{job.get('company') or '通用岗位'} · AI 面试练习", json.dumps(job, ensure_ascii=False), json.dumps(company, ensure_ascii=False)))
    conn.commit()
    return _payload(conn, session_id)


def list_sessions(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    """Return historical practice sessions, newest first."""
    _init(conn)
    rows = conn.execute(
        "SELECT s.id, s.title, s.status, s.created_at, s.updated_at, s.job_snapshot_json, "
        "(SELECT COUNT(*) FROM interview_rounds r WHERE r.session_id = s.id) AS round_count "
        "FROM interview_sessions s ORDER BY s.updated_at DESC, s.created_at DESC LIMIT ?",
        (max(1, min(int(limit), 200)),),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["job_snapshot"] = json.loads(item.pop("job_snapshot_json") or "{}")
        result.append(item)
    return result


def _fallback_question(job: dict[str, Any], round_number: int, asked: list[str]) -> tuple[str, str]:
    title = str(job.get("title") or "目标岗位")
    jd = str(job.get("jd") or "")[:600]
    templates = [
        ("项目真实性", f"结合你应聘的{title}，请挑一个你实际参与过的 Python 项目，说明你负责的模块、关键技术选择，以及最终怎么验证效果。"),
        ("困难与解决", "在这个项目中途遇到过最棘手的问题是什么？你是怎么定位原因、做取舍并把它落地解决的？"),
        ("技术深度", "如果让你把这个项目重新做一遍，你会在哪个环节做技术改进？请结合实际场景说明原因。"),
        ("岗位匹配", f"这个岗位的工作重点是{jd or '业务系统的稳定开发与交付'}。你过去哪段经历最能证明自己可以快速承担这类工作？"),
    ]
    for kind, question in templates:
        if question not in asked:
            return kind, question
    return "追问", "你刚才提到的方案中，哪个决定最影响最终结果？如果条件变化，你会怎样调整？"


def generate_question(conn: sqlite3.Connection, knowledge_conn: sqlite3.Connection, config: dict[str, Any], session_id: str) -> dict[str, Any]:
    _init(conn)
    session = conn.execute("SELECT * FROM interview_sessions WHERE id = ?", (session_id,)).fetchone()
    if not session:
        raise ValueError("面试练习会话不存在")
    job = json.loads(session["job_snapshot_json"] or "{}")
    asked = [str(row["question"]) for row in conn.execute("SELECT question FROM interview_rounds WHERE session_id = ?", (session_id,)).fetchall()]
    next_number = len(asked) + 1
    facts = search_confirmed_facts(knowledge_conn, str(job.get("title") or "岗位") + " " + str(job.get("jd") or ""), limit=5)
    question_type, question = _fallback_question(job, next_number, asked)
    mode = "local_practice_rules"
    if get_ai_api_key(config):
        prompt = (
            "你是严格但友好的真实技术面试官。只输出 JSON，不要 Markdown。\n"
            "字段必须是 question_type 和 question。问题必须贴近岗位 JD、公司业务和候选人实际经历，优先问项目真实性、技术取舍、困难解决、落地和协作；避免空泛鸡汤问题；不要编造候选人没提供的事实。"
            f"\n岗位快照：{json.dumps(job, ensure_ascii=False)}\n可用个人事实：{json.dumps(facts, ensure_ascii=False)}\n已经问过：{json.dumps(asked[-8:], ensure_ascii=False)}\n"
        )
        try:
            raw = call_anthropic_text(prompt, config, 600, purpose="interview_question") or ""
            parsed = json.loads(raw)
            if str(parsed.get("question") or "").strip() and str(parsed["question"]) not in asked:
                question_type, question, mode = str(parsed.get("question_type") or "岗位匹配"), str(parsed["question"]).strip()[:1200], "configured_model"
        except (AIRequestError, ValueError, TypeError, json.JSONDecodeError):
            pass
    conn.execute("INSERT INTO interview_rounds (session_id, round_number, question, question_type) VALUES (?, ?, ?, ?)", (session_id, next_number, question, question_type))
    conn.execute("UPDATE interview_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,))
    conn.commit()
    result = _payload(conn, session_id)
    result.update({"round": result["rounds"][-1], "retrieved_facts": facts, "generation_mode": mode})
    return result


def evaluate_round(conn: sqlite3.Connection, knowledge_conn: sqlite3.Connection, config: dict[str, Any], session_id: str, round_id: int, user_answer: str) -> dict[str, Any]:
    _init(conn)
    user_answer = str(user_answer or "").strip()
    if not user_answer or len(user_answer) > 6000:
        raise ValueError("回答不能为空且不能超过 6000 字")
    row = conn.execute("SELECT * FROM interview_rounds WHERE id = ? AND session_id = ?", (int(round_id), session_id)).fetchone()
    session = conn.execute("SELECT * FROM interview_sessions WHERE id = ?", (session_id,)).fetchone()
    if not row or not session:
        raise ValueError("面试题目不存在")
    job = json.loads(session["job_snapshot_json"] or "{}")
    facts = search_confirmed_facts(knowledge_conn, row["question"] + " " + user_answer, limit=5)
    evaluation = {"score": 72, "strengths": ["回答愿意结合具体场景展开"], "gaps": ["可以补充你的具体职责、排查过程和结果"], "risk_points": [], "follow_up_question": "当时你如何验证这个方案确实有效？"}
    optimized = f"可以这样表达：我在相关项目中负责过与{job.get('title') or '目标岗位'}相近的工作。遇到这类问题时，我会先明确现象和边界，再结合日志、复现和数据定位原因，最后通过测试和线上指标验证方案。结合我的实际经历，具体可以展开说明我负责的模块、取舍和结果。"
    if get_ai_api_key(config):
        prompt = (
            "你是求职面试教练。只输出 JSON：score(0-100整数)、strengths数组、gaps数组、risk_points数组、follow_up_question字符串、optimized_answer字符串。"
            "评价要帮助用户变得更自信，不能贬低、不能说没做过/只是听过/比较基础，不能编造具体数字和公司事实；可以把相近经历迁移为诚实积极的表达。优化答案必须像真实候选人口吻。"
            f"\n岗位：{json.dumps(job, ensure_ascii=False)}\n问题：{row['question']}\n用户回答：{user_answer}\n已确认经历：{json.dumps(facts, ensure_ascii=False)}"
        )
        try:
            parsed = json.loads(call_anthropic_text(prompt, config, 1000, purpose="interview_evaluation") or "")
            if parsed.get("optimized_answer"):
                evaluation = {**evaluation, **parsed}
                optimized = str(parsed["optimized_answer"]).strip()[:3000]
        except (AIRequestError, ValueError, TypeError, json.JSONDecodeError):
            pass
    conn.execute("UPDATE interview_rounds SET user_answer = ?, evaluation_json = ?, optimized_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (user_answer, json.dumps(evaluation, ensure_ascii=False), optimized, int(round_id)))
    conn.commit()
    result = _payload(conn, session_id)
    result["round"] = next(item for item in result["rounds"] if item["id"] == int(round_id))
    return result
