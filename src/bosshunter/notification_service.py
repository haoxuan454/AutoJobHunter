"""Single local notification workflow for real and rehearsal HR messages."""

from __future__ import annotations

import html
import json
import sqlite3
from pathlib import Path
from typing import Any

from bosshunter.conversations import ConversationRepository
from bosshunter.notification_classifier import CATEGORY_LABELS, classify_hr_message
from bosshunter.notifications import enqueue_alert, load_email_settings, send_outbox_item


def _email_html(*, category: str, confidence: float, summary: str, conversation: dict[str, Any], message: str, source: str) -> str:
    esc = lambda value: html.escape(str(value or ""))
    source_label = "AI 回复演练" if source == "assistant_lab" else "真实 HR 会话"
    local_url = f"http://127.0.0.1:8686/conversations/{esc(conversation.get('id'))}"
    platform_url = conversation.get("hr_profile_url") or conversation.get("company_url") or ""
    link = f'<a href="{esc(platform_url)}">打开招聘平台页面</a>' if platform_url else "未提供招聘平台链接"
    return f"""<!doctype html>
<html><body style="margin:0;background:#f7f8fb;color:#1f2937;font-family:Segoe UI,Microsoft YaHei,sans-serif">
<div style="max-width:680px;margin:24px auto;padding:0 16px">
  <div style="background:#111827;color:#fff;padding:20px 24px;border-radius:18px 18px 0 0">
    <div style="font-size:20px;font-weight:700">AutoJobHunter · 人工接管提醒</div>
    <div style="margin-top:6px;color:#cbd5e1;font-size:13px">来源：{esc(source_label)}</div>
  </div>
  <div style="background:#fff;padding:24px;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 18px 18px">
    <div style="display:inline-block;padding:6px 10px;background:#fff1e6;color:#c2410c;border-radius:999px;font-size:12px;font-weight:700">{esc(CATEGORY_LABELS.get(category, category))}</div>
    <h2 style="margin:18px 0 8px;font-size:21px">{esc(summary or 'HR 会话需要你关注')}</h2>
    <p style="margin:0 0 18px;color:#64748b;font-size:13px">语义置信度：{confidence:.0%}</p>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <tr><td style="padding:8px 0;color:#64748b;width:90px">HR</td><td style="padding:8px 0;font-weight:600">{esc(conversation.get('hr_name') or '未命名 HR')}</td></tr>
      <tr><td style="padding:8px 0;color:#64748b">公司</td><td style="padding:8px 0">{esc(conversation.get('company_id') or '未记录')}</td></tr>
      <tr><td style="padding:8px 0;color:#64748b">岗位</td><td style="padding:8px 0">{esc(conversation.get('hr_title') or conversation.get('job_id') or '未记录')}</td></tr>
    </table>
    <div style="margin-top:18px;padding:14px 16px;background:#f8fafc;border-radius:12px;white-space:pre-wrap;line-height:1.7">{esc(message)}</div>
    <div style="margin-top:20px;display:flex;gap:18px;flex-wrap:wrap;font-size:13px"><a href="{local_url}">查看本地会话</a><span>{link}</span></div>
    <p style="margin:20px 0 0;color:#64748b;font-size:12px">该会话已按策略暂停自动推进，请先人工确认。邮件由本地 AutoJobHunter 生成。</p>
  </div>
</div></body></html>"""


def _plain_body(*, category: str, confidence: float, summary: str, conversation: dict[str, Any], message: str, source: str) -> str:
    platform_url = conversation.get("hr_profile_url") or conversation.get("company_url") or "未提供"
    return (
        "AutoJobHunter · 人工接管提醒\n"
        f"来源：{'AI 回复演练' if source == 'assistant_lab' else '真实 HR 会话'}\n"
        f"类型：{CATEGORY_LABELS.get(category, category)}\n"
        f"置信度：{confidence:.0%}\n"
        f"摘要：{summary}\n\n"
        f"HR：{conversation.get('hr_name') or '未命名 HR'}\n"
        f"公司：{conversation.get('company_id') or '未记录'}\n"
        f"岗位：{conversation.get('hr_title') or conversation.get('job_id') or '未记录'}\n"
        f"招聘平台链接：{platform_url}\n"
        f"本地会话：http://127.0.0.1:8686/conversations/{conversation.get('id') or ''}\n\n"
        f"HR 最新消息：\n{message}\n\n"
        "该会话已暂停自动推进，请人工确认后再继续。"
    )


def process_hr_message(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    message: str,
    base_dir: Path,
    config: dict[str, Any],
    source: str = "conversation",
    message_id: str | int | None = None,
    allow_send: bool = True,
    force_model: bool = False,
) -> dict[str, Any]:
    """Classify one newly inserted HR message and optionally deliver an alert."""
    repo = ConversationRepository(conn)
    conversation = repo.get_conversation(conversation_id)
    if not conversation:
        raise ValueError("conversation does not exist")
    classification = classify_hr_message(message, config, force_model=force_model)
    notification = None
    if classification["matched"]:
        reason = f"检测到{CATEGORY_LABELS.get(classification['category'], classification['category'])}话题，等待人工处理"
        conversation = repo.update_status(conversation_id, "paused_salary" if classification["category"] == "salary" else "paused_manual", reason)
        settings = load_email_settings(base_dir, config)
        recipient = settings.get("to_email")
        if recipient:
            suffix = str(message_id or classification.get("evidence") or message)[:120]
            subject = f"AutoJobHunter 人工接管提醒：{conversation.get('hr_name') or 'HR'} · {CATEGORY_LABELS.get(classification['category'], classification['category'])} · {suffix}"
            metadata = {"classification": classification, "message_id": message_id, "source": source}
            notification = enqueue_alert(
                conn,
                conversation_id=conversation_id,
                recipient=recipient,
                subject=subject,
                body=_plain_body(category=classification["category"], confidence=classification["confidence"], summary=classification["summary"], conversation=conversation, message=message, source=source),
                html_body=_email_html(category=classification["category"], confidence=classification["confidence"], summary=classification["summary"], conversation=conversation, message=message, source=source),
                kind=classification["category"],
                confidence=classification["confidence"],
                source=source,
                metadata=metadata,
            )
            if allow_send and settings.get("enabled") and settings.get("auto_send") and notification.get("status") != "sent":
                try:
                    notification = send_outbox_item(conn, notification["id"], settings)
                except Exception as exc:
                    notification = dict(notification)
                    notification["delivery_error"] = str(exc)
    return {"classification": classification, "notification": notification, "conversation": conversation}


def process_lab_message(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    message: str,
    base_dir: Path,
    config: dict[str, Any],
    allow_send: bool = False,
) -> dict[str, Any]:
    """Use a synthetic conversation for explicit Assistant Lab notification tests."""
    conversation_id = f"assistant-lab:{session_id}"
    repo = ConversationRepository(conn)
    repo.upsert_conversation({
        "id": conversation_id,
        "platform": "assistant_lab",
        "external_conversation_id": conversation_id,
        "hr_name": "AI 回复演练 HR",
        "hr_title": "演练岗位",
        "company_id": "AI 回复演练",
        "hr_profile_url": "http://127.0.0.1:8686/assistant-lab",
        "status": "active",
    })
    return process_hr_message(conn, conversation_id=conversation_id, message=message, base_dir=base_dir, config=config, source="assistant_lab", allow_send=allow_send)
