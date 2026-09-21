"""Opt-in local scheduler for the daily email summary.

This worker reads only local SQLite/config state. It never opens a browser or
contacts a recruitment platform. The execution ledger makes each date
idempotent across polling iterations and process restarts.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable
from bosshunter.daily_summary import generate_daily_summary, load_daily_summary_settings, resolve_timezone
from bosshunter.notifications import load_email_settings


def init_daily_summary_scheduler_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily_summary_scheduler_runs (
            run_date TEXT PRIMARY KEY,
            scheduled_for TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            notification_id INTEGER,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_daily_summary_scheduler_status
            ON daily_summary_scheduler_runs(status, run_date);
        """
    )
    conn.commit()


def _scheduled_datetime(now: datetime, settings: dict[str, Any]) -> datetime:
    hour, minute = (int(part) for part in str(settings["send_time"]).split(":", 1))
    return datetime.combine(now.date(), time(hour, minute), tzinfo=now.tzinfo)


def should_run_today(
    settings: dict[str, Any],
    email_settings: dict[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether the opt-in summary is due at the supplied local time."""
    tz = resolve_timezone(str(settings.get("timezone") or "Asia/Shanghai"))
    current = (now or datetime.now(tz)).astimezone(tz)
    scheduled = _scheduled_datetime(current, settings)
    return (
        bool(settings.get("enabled"))
        and bool(settings.get("auto_send"))
        and bool(email_settings.get("enabled"))
        and bool(email_settings.get("auto_send"))
        and current >= scheduled
    )


def _claim_today(conn: sqlite3.Connection, *, run_date: str, scheduled_for: str) -> bool:
    init_daily_summary_scheduler_tables(conn)
    cursor = conn.execute(
        """INSERT OR IGNORE INTO daily_summary_scheduler_runs
           (run_date, scheduled_for, status) VALUES (?, ?, 'running')""",
        (run_date, scheduled_for),
    )
    conn.commit()
    return cursor.rowcount == 1


def run_daily_summary_once(
    db_path: Path,
    *,
    base_dir: Path,
    config: dict[str, Any],
    now: datetime | None = None,
    generate_fn: Callable[..., dict[str, Any]] = generate_daily_summary,
) -> dict[str, Any]:
    """Run the due summary at most once for the local calendar date."""
    settings = load_daily_summary_settings(config)
    tz = resolve_timezone(str(settings.get("timezone") or "Asia/Shanghai"))
    current = (now or datetime.now(tz)).astimezone(tz)
    email_settings = load_email_settings(base_dir, config)
    if not should_run_today(settings, email_settings, now=current):
        return {"status": "not_due", "date": current.date().isoformat()}

    scheduled = _scheduled_datetime(current, settings)
    run_date = current.date().isoformat()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if not _claim_today(conn, run_date=run_date, scheduled_for=scheduled.isoformat()):
            row = conn.execute(
                "SELECT * FROM daily_summary_scheduler_runs WHERE run_date = ?", (run_date,)
            ).fetchone()
            return {"status": "already_run", "date": run_date, "run": dict(row) if row else None}
        try:
            result = generate_fn(conn, base_dir=base_dir, config=config, day=run_date, allow_send=True)
        except Exception as exc:
            conn.execute(
                "UPDATE daily_summary_scheduler_runs SET status = 'failed', error = ?, completed_at = CURRENT_TIMESTAMP WHERE run_date = ?",
                (str(exc)[:1000], run_date),
            )
            conn.commit()
            return {"status": "failed", "date": run_date, "error": str(exc)[:1000]}
        notification = result.get("notification") if isinstance(result, dict) else None
        notification_id = notification.get("id") if isinstance(notification, dict) else None
        conn.execute(
            "UPDATE daily_summary_scheduler_runs SET status = 'sent', notification_id = ?, completed_at = CURRENT_TIMESTAMP WHERE run_date = ?",
            (notification_id, run_date),
        )
        conn.commit()
        return {
            "status": "sent",
            "date": run_date,
            "notification": notification,
            "summary": result.get("summary") if isinstance(result, dict) else None,
        }
    finally:
        conn.close()


class DailySummaryScheduler:
    """Small daemon worker that checks the local clock without blocking Web."""

    def __init__(self, *, base_dir: Path, db_path: Path, config_path: Path, poll_seconds: float = 30.0):
        self.base_dir = Path(base_dir)
        self.db_path = Path(db_path)
        self.config_path = Path(config_path)
        self.poll_seconds = max(float(poll_seconds), 5.0)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "DailySummaryScheduler":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="daily-summary-scheduler", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(float(timeout), 0.0))

    def _run(self) -> None:
        from bosshunter.config import load_config

        while not self._stop.is_set():
            try:
                config = load_config(self.config_path)
                run_daily_summary_once(self.db_path, base_dir=self.base_dir, config=config)
            except Exception:
                # The ledger and outbox remain the source of truth; Web stays up.
                pass
            self._stop.wait(self.poll_seconds)


def start_daily_summary_scheduler(
    *, base_dir: Path, db_path: Path, config_path: Path, poll_seconds: float = 30.0
) -> DailySummaryScheduler:
    return DailySummaryScheduler(
        base_dir=base_dir, db_path=db_path, config_path=config_path, poll_seconds=poll_seconds
    ).start()
