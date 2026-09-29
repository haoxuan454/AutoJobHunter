"""Bounded, local-only runtime log reader for the dashboard."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50
DEFAULT_TAIL_BYTES = 2 * 1024 * 1024
MAX_TAIL_BYTES = 8 * 1024 * 1024

_SENSITIVE_PATTERNS = (
    (re.compile(r"(?i)(remember_token|authorization|cookie|api[_-]?key|auth[_-]?token)(\s*[:=]\s*)[^\s,;]+"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
)


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "cp936"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _redact(value: str) -> str:
    for pattern, replacement in _SENSITIVE_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def _tail_lines(path: Path, max_bytes: int) -> list[str]:
    if not path.is_file():
        return []
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        payload = handle.read(max_bytes)
    lines = _decode(payload).splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    return lines


def _source_files(runtime_dir: Path) -> dict[str, Path]:
    # Deliberately fixed allow-list: callers cannot select arbitrary files.
    return {
        "web.err": runtime_dir / "web.err.log",
        "web.out": runtime_dir / "web.out.log",
    }


def read_logs(
    runtime_dir: Path | str,
    *,
    source: str = "all",
    query: str = "",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    tail_bytes: int = DEFAULT_TAIL_BYTES,
    task_lines: Iterable[str] = (),
) -> dict:
    """Return newest-first log lines without reading unbounded files."""
    runtime_dir = Path(runtime_dir).resolve()
    if source not in {"all", "web.err", "web.out", "task"}:
        raise ValueError("source must be all, web.err, web.out, or task")
    if page < 1:
        raise ValueError("page must be >= 1")
    page_size = min(max(int(page_size), 1), MAX_PAGE_SIZE)
    tail_bytes = min(max(int(tail_bytes), 4096), MAX_TAIL_BYTES)
    needle = str(query or "").strip().casefold()

    rows: list[dict] = []
    if source in {"all", "web.err", "web.out"}:
        for name, path in _source_files(runtime_dir).items():
            if source != "all" and source != name:
                continue
            for line_number, line in enumerate(_tail_lines(path, tail_bytes), 1):
                clean = _redact(line)
                if needle and needle not in clean.casefold():
                    continue
                rows.append({"source": name, "line": clean, "line_number": line_number})
    if source in {"all", "task"}:
        for line_number, line in enumerate(task_lines, 1):
            clean = _redact(str(line))
            if needle and needle not in clean.casefold():
                continue
            rows.append({"source": "task", "line": clean, "line_number": line_number})

    # File lines do not all carry parseable timestamps. Stable reverse order is
    # still correct for each tail and makes newest entries appear first.
    rows.reverse()
    total = len(rows)
    start = (page - 1) * page_size
    items = rows[start:start + page_size]
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": start + page_size < total,
        "truncated": any(path.is_file() and path.stat().st_size > tail_bytes for path in _source_files(runtime_dir).values()),
    }
