"""Semantic classification for HR handoff notifications.

The classifier receives only the newly arrived HR text.  It deliberately does
not receive company, salary, or another conversation's context, which keeps
notification decisions isolated per HR conversation.
"""

from __future__ import annotations

import json
import re
from typing import Any

from bosshunter.ai.credentials import call_anthropic_text, get_ai_api_key


CATEGORY_LABELS = {
    "salary": "薪资与待遇",
    "interview": "面试安排",
    "offer": "终面、Offer 或入职推进",
    "wechat": "添加微信或转移沟通",
    "contract": "合同、背调或入职材料",
    "interest": "HR 明确表达兴趣",
    "custom": "自定义提醒",
}

_LOCAL_PATTERNS: dict[str, tuple[str, ...]] = {
    "salary": ("薪资", "工资", "薪酬", "薪金", "待遇", "月薪", "年薪", "几k", "几 K", "薪资范围", "薪酬结构", "期望薪资"),
    "interview": ("面试", "约面", "到面", "线上面", "线下面", "视频面", "面谈", "面试时间"),
    "offer": ("offer", "录用", "入职", "终面", "最后一轮", "推进你", "尽快推进", "入职时间"),
    "wechat": ("微信", "加微", "加个微", "vx", "v信", "私聊", "移步微信"),
    "contract": ("合同", "背调", "背调资料", "入职材料", "身份证", "劳动合同"),
    "interest": ("感兴趣", "很匹配", "比较合适", "认可你的", "想进一步了解", "优先考虑"),
}

# Generic technical questions must never trigger a handoff merely because a
# configured keyword such as Python or API appears. These phrases remain
# separate from escalation vocabulary so normal chat turns stay conservative.
_TECHNICAL_ONLY = ("python", "java", "前端", "后端", "框架", "项目", "技术", "接口", "数据库", "部署")


def _local_scores(text: str) -> dict[str, float]:
    normalized = re.sub(r"\s+", "", str(text or "").lower())
    scores: dict[str, float] = {}
    for category, patterns in _LOCAL_PATTERNS.items():
        hits = sum(1 for pattern in patterns if pattern.lower().replace(" ", "") in normalized)
        if hits:
            # One highly specific phrase is enough for a safe local decision;
            # multiple phrases increase confidence without reaching certainty.
            scores[category] = min(0.96, 0.76 + hits * 0.08)
    return scores


def _parse_model_result(raw: str) -> dict[str, Any] | None:
    candidate = str(raw or "").strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()
    try:
        value = json.loads(candidate)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    category = str(value.get("category") or "custom").strip()
    try:
        confidence = float(value.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    if category not in CATEGORY_LABELS:
        category = "custom"
    return {
        "matched": bool(value.get("matched", False)),
        "category": category,
        "confidence": max(0.0, min(confidence, 1.0)),
        "summary": str(value.get("summary") or "").strip()[:300],
        "recommended_action": str(value.get("recommended_action") or "none").strip(),
        "evidence": str(value.get("evidence") or "").strip()[:500],
    }


def classify_hr_message(
    message: str,
    config: dict[str, Any] | None = None,
    *,
    enabled_categories: list[str] | None = None,
    force_model: bool = False,
) -> dict[str, Any]:
    """Return a safe, structured classification for one HR message."""
    text = str(message or "").strip()
    email_cfg = ((config or {}).get("notifications") or {}).get("email") or {}
    enabled = set(enabled_categories or email_cfg.get("notification_types") or _LOCAL_PATTERNS.keys())
    try:
        threshold = float(email_cfg.get("confidence_threshold", 0.8) or 0.8)
    except (TypeError, ValueError):
        threshold = 0.8
    scores = _local_scores(text)
    technical_only = any(token in text.lower() for token in _TECHNICAL_ONLY) and not any(
        category in scores for category in ("salary", "interview", "offer", "wechat", "contract", "interest")
    )
    if technical_only:
        return {
            "matched": False,
            "category": "custom",
            "confidence": 0.0,
            "summary": "普通技术交流，不触发人工接管提醒",
            "recommended_action": "none",
            "evidence": text[:500],
            "source": "technical_question_guard",
        }
    if any(token in text.lower() for token in _TECHNICAL_ONLY) and not any(
        category in scores for category in ("salary", "interview", "offer", "wechat", "contract", "interest")
    ):
        scores = {}
    local_category, local_confidence = (max(scores.items(), key=lambda item: item[1]) if scores else ("custom", 0.0))
    if local_category not in enabled:
        local_confidence = 0.0
    if local_confidence >= threshold and not force_model:
        return {
            "matched": True,
            "category": local_category,
            "confidence": local_confidence,
            "summary": f"HR 可能正在沟通{CATEGORY_LABELS[local_category]}",
            "recommended_action": "pause_and_notify",
            "evidence": text[:500],
            "source": "local_semantic",
        }

    # Ambiguous text is sent to the one configured AI entry point only when
    # needed.  The prompt contains no cross-conversation or company data.
    if get_ai_api_key(config or {}) and (force_model or local_confidence < threshold):
        prompt = (
            "你是求职自动化系统中的通知意图分类器。只分析下面这一条 HR 消息，不要猜测公司、岗位、薪资数字或其他会话信息。\n"
            "请只返回 JSON，不要 Markdown：{\"matched\":true/false,\"category\":\"salary|interview|offer|wechat|contract|interest|custom\","
            "\"confidence\":0到1之间的数字,\"summary\":\"中文短摘要\",\"recommended_action\":\"pause_and_notify|none\",\"evidence\":\"依据\"}\n"
            f"可提醒类型：{sorted(enabled)}\nHR 消息：{text[:2000]}"
        )
        try:
            parsed = _parse_model_result(call_anthropic_text(prompt, config or {}, 300, purpose="notification_classification") or "")
            if parsed and parsed["category"] in enabled and parsed["matched"] and parsed["confidence"] >= threshold:
                parsed["source"] = "ai_semantic"
                return parsed
        except Exception:
            # Classification failure must fail closed: no pause and no email.
            pass

    return {
        "matched": False,
        "category": local_category if local_category in CATEGORY_LABELS else "custom",
        "confidence": local_confidence,
        "summary": "未达到自动提醒置信度",
        "recommended_action": "none",
        "evidence": text[:500],
        "source": "local_or_unavailable",
    }
