"""Local AI token usage ledger and reporting helpers.

The ledger stores counts and estimates only.  It never stores prompts,
responses, API keys, or other model payload content.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _db_path() -> Path:
    return Path.cwd() / "data" / "bosshunter.db"


def init_token_usage_tables(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            purpose TEXT NOT NULL DEFAULT 'unspecified',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            estimated INTEGER NOT NULL DEFAULT 0,
            input_cost REAL NOT NULL DEFAULT 0,
            output_cost REAL NOT NULL DEFAULT 0,
            total_cost REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_token_usage_created ON ai_token_usage(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_token_usage_purpose ON ai_token_usage(purpose)")
    conn.commit()


def _number(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _usage_value(usage: Any, *names: str) -> int:
    for name in names:
        if isinstance(usage, dict) and name in usage:
            return _number(usage[name])
        value = getattr(usage, name, None)
        if value is not None:
            return _number(value)
    return 0


def record_token_usage(
    config: dict[str, Any],
    *,
    purpose: str | None,
    prompt: str,
    output: str,
    provider: str,
    model: str,
    usage: Any = None,
) -> None:
    """Record one successful model call without retaining content."""
    input_tokens = _usage_value(usage, "input_tokens", "prompt_tokens")
    output_tokens = _usage_value(usage, "output_tokens", "completion_tokens")
    estimated = 0
    if not input_tokens:
        input_tokens = max(1, len(prompt or "") // 4)
        estimated = 1
    if not output_tokens:
        output_tokens = max(1, len(output or "") // 4)
        estimated = 1
    total_tokens = _usage_value(usage, "total_tokens") or input_tokens + output_tokens
    ai_cfg = config.get("ai", {}) if isinstance(config, dict) else {}
    try:
        input_rate = float(ai_cfg.get("input_cost_per_million", 0) or 0)
        output_rate = float(ai_cfg.get("output_cost_per_million", 0) or 0)
    except (TypeError, ValueError):
        input_rate = output_rate = 0.0
    input_cost = input_tokens / 1_000_000 * input_rate
    output_cost = output_tokens / 1_000_000 * output_rate
    conn = sqlite3.connect(str(_db_path()))
    try:
        init_token_usage_tables(conn)
        conn.execute(
            "INSERT INTO ai_token_usage (provider, model, purpose, input_tokens, output_tokens, total_tokens, estimated, input_cost, output_cost, total_cost) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(provider or ""), str(model or ""), str(purpose or "unspecified"), input_tokens, output_tokens, total_tokens, estimated, input_cost, output_cost, input_cost + output_cost),
        )
        conn.commit()
    finally:
        conn.close()


def _bounds(start: str | None, end: str | None) -> tuple[str, str]:
    now = datetime.now()
    try:
        start_dt = datetime.fromisoformat(str(start)) if start else now - timedelta(days=7)
    except ValueError:
        start_dt = now - timedelta(days=7)
    try:
        end_dt = datetime.fromisoformat(str(end)) if end else now
    except ValueError:
        end_dt = now
    return start_dt.strftime("%Y-%m-%d %H:%M:%S"), end_dt.strftime("%Y-%m-%d %H:%M:%S")


def token_usage_report(conn: sqlite3.Connection, *, start: str | None = None, end: str | None = None, granularity: str = "day", offset: int = 0, limit: int = 15) -> dict[str, Any]:
    init_token_usage_tables(conn)
    start_value, end_value = _bounds(start, end)
    bucket = "strftime('%Y-%m-%d %H:00:00', created_at)" if granularity == "hour" else "strftime('%Y-%m-%d', created_at)"
    where = "created_at >= ? AND created_at <= ?"
    params = (start_value, end_value)
    summary = conn.execute(
        f"SELECT COUNT(*) calls, COALESCE(SUM(input_tokens),0) input_tokens, COALESCE(SUM(output_tokens),0) output_tokens, COALESCE(SUM(total_tokens),0) total_tokens, COALESCE(SUM(estimated),0) estimated_calls, COALESCE(SUM(total_cost),0) total_cost FROM ai_token_usage WHERE {where}",
        params,
    ).fetchone()
    by_purpose = conn.execute(
        f"SELECT purpose, COUNT(*) calls, SUM(total_tokens) total_tokens, SUM(total_cost) total_cost FROM ai_token_usage WHERE {where} GROUP BY purpose ORDER BY total_tokens DESC",
        params,
    ).fetchall()
    by_model = conn.execute(
        f"SELECT provider, model, COUNT(*) calls, SUM(total_tokens) total_tokens, SUM(total_cost) total_cost FROM ai_token_usage WHERE {where} GROUP BY provider, model ORDER BY total_tokens DESC",
        params,
    ).fetchall()
    series = conn.execute(
        f"SELECT {bucket} bucket, COUNT(*) calls, SUM(input_tokens) input_tokens, SUM(output_tokens) output_tokens, SUM(total_tokens) total_tokens, SUM(total_cost) total_cost FROM ai_token_usage WHERE {where} GROUP BY bucket ORDER BY bucket",
        params,
    ).fetchall()
    recent_total = conn.execute(f"SELECT COUNT(*) FROM ai_token_usage WHERE {where}", params).fetchone()[0]
    recent = conn.execute(
        f"SELECT id, provider, model, purpose, input_tokens, output_tokens, total_tokens, estimated, total_cost, created_at FROM ai_token_usage WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        (*params, max(1, min(int(limit), 100)), max(int(offset), 0)),
    ).fetchall()
    return {
        "start": start_value,
        "end": end_value,
        "granularity": granularity if granularity in {"day", "hour"} else "day",
        "summary": dict(summary),
        "by_purpose": [dict(row) for row in by_purpose],
        "by_model": [dict(row) for row in by_model],
        "series": [dict(row) for row in series],
        "recent_total": recent_total,
        "recent": [dict(row) for row in recent],
    }
