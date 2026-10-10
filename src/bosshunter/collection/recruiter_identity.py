"""Normalize only a known BOSS activity suffix, never fuzzy recruiter names."""

import re


_ACTIVITY = re.compile(r"(?:(?:刚刚|今日|今天|昨日|昨天|近期|本周|本月|半年前|\d+\s*(?:分钟|小时|天|周|个月|月|年)前)\s*)?(?:活跃|在线)")


def normalize_boss_recruiter_name(value: object) -> str:
    text = str(value or "").strip()
    # Old detail snapshots contain a separate activity child node. Only remove
    # a complete recognized label separated by whitespace, not name substrings.
    match = re.search(r"\s+(\S.*)$", text, flags=re.DOTALL)
    if match and _ACTIVITY.fullmatch(match.group(1).strip()):
        return text[:match.start()].strip()
    return text
