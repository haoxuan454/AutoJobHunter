"""Daily local activity summary and idempotent email generation."""

from __future__ import annotations

import html
import sqlite3
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bosshunter.config import save_config
from bosshunter.conversations import ConversationRepository
from bosshunter.notifications import enqueue_alert, init_notification_tables, load_email_settings, send_outbox_item


DEFAULT_SUMMARY_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "auto_send": False,
    "send_time": "20:00",
    "timezone": "Asia/Shanghai",
    "top_jobs_limit": 3,
    "include_job_count": True,
    "include_conversation_count": True,
    "include_interested_hr": True,
    "include_top_jobs": True,
    "detail_level": "compact",
}


def resolve_timezone(name: str | None) -> tzinfo:
    """Resolve a configured timezone on platforms with or without tzdata.

    Windows installations often do not ship the IANA timezone database that
    ``zoneinfo`` expects. The product default is China Standard Time, whose
    fixed UTC+8 offset is unambiguous, so it has a small local fallback. Other
    names still fail closed and are reported as invalid configuration.
    """
    timezone_name = str(name or "Asia/Shanghai")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name="Asia/Shanghai")
        raise


def _summary_section(config: dict[str, Any] | None) -> dict[str, Any]:
    value = ((config or {}).get("notifications") or {}).get("daily_summary")
    return dict(value) if isinstance(value, dict) else {}


def load_daily_summary_settings(config: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = dict(DEFAULT_SUMMARY_SETTINGS)
    settings.update(_summary_section(config))
    return settings


def validate_daily_summary_settings(value: dict[str, Any]) -> dict[str, Any]:
    allowed = set(DEFAULT_SUMMARY_SETTINGS)
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unsupported daily summary settings: {sorted(unknown)}")
    result = dict(DEFAULT_SUMMARY_SETTINGS)
    result.update(value)
    try:
        result["top_jobs_limit"] = int(result["top_jobs_limit"])
    except (TypeError, ValueError) as exc:
        raise ValueError("top_jobs_limit must be an integer") from exc
    if not 1 <= result["top_jobs_limit"] <= 20:
        raise ValueError("top_jobs_limit must be between 1 and 20")
    if not isinstance(result["send_time"], str) or not __import__("re").fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", result["send_time"]):
        raise ValueError("send_time must use HH:MM")
    try:
        resolve_timezone(str(result["timezone"]))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone is invalid") from exc
    if result["detail_level"] not in {"compact", "detailed"}:
        raise ValueError("detail_level must be compact or detailed")
    for key in ("enabled", "auto_send", "include_job_count", "include_conversation_count", "include_interested_hr", "include_top_jobs"):
        result[key] = bool(result[key])
    return result


def save_daily_summary_settings(base_dir: Path, config: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    validated = validate_daily_summary_settings(value)
    public = dict(config)
    notifications = dict(public.get("notifications") or {})
    notifications["daily_summary"] = validated
    public["notifications"] = notifications
    save_config(public, Path(base_dir) / "config.yaml")
    return load_daily_summary_settings(public)


def _target_date(value: str | date | None, tz: tzinfo) -> date:
    if value is None or value == "":
        return datetime.now(tz).date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD") from exc


def _utc_bounds(day: date, tz: tzinfo) -> tuple[str, str]:
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def _query_one(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0)


def build_daily_summary(conn: sqlite3.Connection, day: date, settings: dict[str, Any]) -> dict[str, Any]:
    # A fresh local database may not have received any conversation or
    # notification traffic yet. Initialise those additive tables before the
    # read-only aggregation queries.
    ConversationRepository(conn)
    init_notification_tables(conn)
    tz = resolve_timezone(str(settings.get("timezone") or "Asia/Shanghai"))
    start, end = _utc_bounds(day, tz)
    jobs = _query_one(conn, "SELECT COUNT(*) FROM jobs WHERE deleted_at IS NULL AND created_at >= ? AND created_at < ?", (start, end))
    conversations = _query_one(conn, """SELECT COUNT(DISTINCT conversation_id) FROM conv_messages
        WHERE sender_type = 'hr' AND created_at >= ? AND created_at < ?""", (start, end))
    notifications = _query_one(conn, "SELECT COUNT(*) FROM notification_outbox WHERE created_at >= ? AND created_at < ?", (start, end))
    interested = [dict(row) for row in conn.execute("""SELECT hr_name, company_id, interest_score, updated_at
        FROM conv_conversations WHERE interest_score IS NOT NULL AND interest_score > 0
        AND updated_at >= ? AND updated_at < ? ORDER BY interest_score DESC, updated_at DESC LIMIT 20""", (start, end)).fetchall()]
    limit = int(settings.get("top_jobs_limit") or 3)
    top_jobs = [dict(row) for row in conn.execute("""SELECT id, title, company, score, status, url
        FROM jobs WHERE deleted_at IS NULL AND created_at >= ? AND created_at < ?
        ORDER BY score DESC, created_at DESC LIMIT ?""", (start, end, limit)).fetchall()]
    return {
        "date": day.isoformat(),
        "timezone": str(settings.get("timezone") or "Asia/Shanghai"),
        "job_count": jobs,
        "conversation_count": conversations,
        "notification_count": notifications,
        "interested_hr": interested,
        "top_jobs": top_jobs,
    }


def _plain_summary(summary: dict[str, Any], settings: dict[str, Any]) -> str:
    lines = [f"AutoJobHunter · 每日求职汇总 · {summary['date']}", ""]
    if settings.get("include_job_count"):
        lines.append(f"今日新增岗位：{summary['job_count']}")
    if settings.get("include_conversation_count"):
        lines.append(f"今日有 HR 消息的会话：{summary['conversation_count']}")
    lines.append(f"今日人工接管提醒：{summary['notification_count']}")
    if settings.get("include_interested_hr"):
        lines.append("\n表达兴趣的 HR：")
        lines.extend(f"- {row.get('hr_name') or '未命名 HR'} · {row.get('company_id') or '未记录'} · 评分 {row.get('interest_score') or 0}" for row in summary["interested_hr"][:10])
        if not summary["interested_hr"]:
            lines.append("- 暂无")
    if settings.get("include_top_jobs"):
        lines.append("\n岗位评分前列：")
        lines.extend(f"- {row.get('company') or '未记录'} · {row.get('title') or '未命名岗位'} · {row.get('score') or 0} 分" for row in summary["top_jobs"])
        if not summary["top_jobs"]:
            lines.append("- 暂无")
    return "\n".join(lines)


def _html_summary(summary: dict[str, Any], settings: dict[str, Any]) -> str:
    esc = lambda value: html.escape(str(value or ""))
    cards = []
    for label, key in (("新增岗位", "job_count"), ("HR 会话", "conversation_count"), ("人工提醒", "notification_count")):
        if key == "job_count" and not settings.get("include_job_count"):
            continue
        if key == "conversation_count" and not settings.get("include_conversation_count"):
            continue
        cards.append(f'<div style="flex:1;min-width:150px;background:#fff7f0;border-radius:14px;padding:16px"><div style="color:#64748b;font-size:12px">{label}</div><div style="margin-top:6px;font-size:26px;font-weight:700;color:#c2410c">{summary[key]}</div></div>')
    jobs = "".join(f'<li style="margin:8px 0">{esc(row.get("company"))} · {esc(row.get("title"))} · {row.get("score") or 0} 分</li>' for row in summary["top_jobs"])
    interest = "".join(f'<li style="margin:8px 0">{esc(row.get("hr_name") or "未命名 HR")} · {esc(row.get("company_id") or "未记录")}</li>' for row in summary["interested_hr"][:10]) or "<li>暂无</li>"
    return f'''<!doctype html><html><body style="margin:0;background:#f7f8fb;color:#1f2937;font-family:Segoe UI,Microsoft YaHei,sans-serif"><div style="max-width:680px;margin:24px auto;padding:0 16px"><div style="background:#111827;color:#fff;padding:22px 24px;border-radius:18px 18px 0 0"><div style="font-size:20px;font-weight:700">AutoJobHunter · 每日求职汇总</div><div style="margin-top:6px;color:#cbd5e1;font-size:13px">{esc(summary['date'])} · {esc(summary['timezone'])}</div></div><div style="background:#fff;padding:24px;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 18px 18px"><div style="display:flex;gap:12px;flex-wrap:wrap">{"".join(cards)}</div>{f'<h3>表达兴趣的 HR</h3><ul>{interest}</ul>' if settings.get('include_interested_hr') else ''}{f'<h3>岗位评分前列</h3><ol>{jobs or "<li>暂无</li>"}</ol>' if settings.get('include_top_jobs') else ''}<p style="color:#64748b;font-size:12px">本汇总仅来自本地 AutoJobHunter 数据库。</p></div></div></body></html>'''


def generate_daily_summary(conn: sqlite3.Connection, *, base_dir: Path, config: dict[str, Any], day: str | date | None = None, allow_send: bool = False) -> dict[str, Any]:
    settings = load_daily_summary_settings(config)
    tz = resolve_timezone(str(settings.get("timezone") or "Asia/Shanghai"))
    target = _target_date(day, tz)
    summary = build_daily_summary(conn, target, settings)
    email = load_email_settings(base_dir, config)
    recipient = email.get("to_email")
    if not recipient:
        raise ValueError("请先配置 QQ 收件邮箱")
    conversation_id = f"__daily_summary__:{target.isoformat()}"
    subject = f"AutoJobHunter 每日求职汇总 · {target.isoformat()}"
    item = enqueue_alert(conn, conversation_id=conversation_id, kind="daily_summary", recipient=recipient, subject=subject, body=_plain_summary(summary, settings), html_body=_html_summary(summary, settings), source="daily_summary", metadata={"summary": summary}, confidence=1.0)
    if allow_send and email.get("enabled") and (email.get("auto_send") or allow_send) and item.get("status") != "sent":
        item = send_outbox_item(conn, item["id"], email)
    return {"summary": summary, "notification": item, "settings": settings}
