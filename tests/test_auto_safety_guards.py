from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

from bosshunter.ai.scorer import sanitize_score_trace
from bosshunter.automation.delivery import deliver_eligible_jobs
from bosshunter.automation.quota import claim_slot, consume_slot, release_slot
from bosshunter.automation.scoring import score_collected_jobs
from bosshunter.browser.platform_targets import target_belongs_to_platform
from bosshunter.db import get_db, insert_job


def _job(job_id: str = "job-1", platform: str = "boss") -> dict:
    return {
        "id": job_id,
        "title": f"{platform} test job",
        "company": "Example company",
        "source_platform": platform,
        "status": "ready",
        "score": 90,
        "url": f"https://example.test/{platform}/{job_id}",
    }


def _claim_statuses(db_path: Path) -> list[str]:
    db = get_db(db_path)
    try:
        return [
            str(row[0])
            for row in db.execute(
                "SELECT status FROM automatic_delivery_claims ORDER BY rowid"
            ).fetchall()
        ]
    finally:
        db.close()


def test_platform_target_ownership_rejects_cross_platform_and_lookalike_hosts():
    assert target_belongs_to_platform(
        {"targetId": "boss", "url": "https://www.zhipin.com/web/geek"}, "boss"
    )
    assert not target_belongs_to_platform(
        {"targetId": "zhilian", "url": "https://www.zhaopin.com/"}, "boss"
    )
    assert not target_belongs_to_platform(
        {"targetId": "evil", "url": "https://zhipin.com.evil.test/"}, "boss"
    )
    assert not target_belongs_to_platform(
        {"targetId": "evil", "url": "https://evil-zhipin.com/"}, "boss"
    )
    assert not target_belongs_to_platform(
        {"targetId": "file", "url": "file:///tmp/zhipin"}, "boss"
    )


def test_quota_claim_is_atomic_and_consume_release_are_one_shot(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    config = {"throttle": {"daily_limit": 1}}

    first = claim_slot(config, db_path=db_path, job_id="job-1", platform="boss")
    second = claim_slot(config, db_path=db_path, job_id="job-2", platform="zhilian")

    assert first["status"] == "claimed"
    assert second["status"] == "exhausted"
    assert release_slot(db_path=db_path, claim_id=first["claim_id"])
    assert not release_slot(db_path=db_path, claim_id=first["claim_id"])

    replacement = claim_slot(config, db_path=db_path, job_id="job-2", platform="zhilian")
    assert replacement["status"] == "claimed"
    assert consume_slot(db_path=db_path, claim_id=replacement["claim_id"])
    assert not consume_slot(db_path=db_path, claim_id=replacement["claim_id"])
    assert not release_slot(db_path=db_path, claim_id=replacement["claim_id"])
    assert _claim_statuses(db_path) == ["released", "consumed"]


def test_delivery_releases_claim_when_quota_consume_cannot_be_verified(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    db = get_db(db_path)
    try:
        insert_job(db, _job())
    finally:
        db.close()

    def fake_sender(config, **_kwargs):
        config["_workbench_send_report"] = {"sent_count": 1, "failed_count": 0}

    with patch("bosshunter.automation.delivery.prepare_eligible_jobs"), patch(
        "bosshunter.automation.delivery.send_greetings", side_effect=fake_sender
    ), patch("bosshunter.automation.delivery.consume_slot", return_value=False):
        attempts = deliver_eligible_jobs(
            {"throttle": {"daily_limit": 1}},
            {"boss": ["job-1"]},
            db_path=db_path,
            boss_greeting="您好",
            min_delay_seconds=0,
            max_delay_seconds=0,
        )

    assert attempts[0].status == "quota_consume_failed"
    assert attempts[0].safe_success is False
    assert _claim_statuses(db_path) == ["released"]


def test_delivery_releases_claim_when_sender_raises(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    db = get_db(db_path)
    try:
        insert_job(db, _job())
    finally:
        db.close()

    with patch("bosshunter.automation.delivery.prepare_eligible_jobs"), patch(
        "bosshunter.automation.delivery.send_greetings", side_effect=RuntimeError("transport")
    ):
        attempts = deliver_eligible_jobs(
            {"throttle": {"daily_limit": 1}},
            {"boss": ["job-1"]},
            db_path=db_path,
            boss_greeting="您好",
            min_delay_seconds=0,
            max_delay_seconds=0,
        )

    assert attempts[0].status == "exception"
    assert _claim_statuses(db_path) == ["released"]


def test_queue_stop_does_not_leave_unattempted_claims(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    db = get_db(db_path)
    try:
        insert_job(db, _job("job-1"))
        insert_job(db, _job("job-2"))
    finally:
        db.close()
    stop_event = threading.Event()

    def fake_sender(config, **_kwargs):
        config["_workbench_send_report"] = {"sent_count": 1, "failed_count": 0}
        stop_event.set()

    with patch("bosshunter.automation.delivery.prepare_eligible_jobs"), patch(
        "bosshunter.automation.delivery.send_greetings", side_effect=fake_sender
    ):
        attempts = deliver_eligible_jobs(
            {"throttle": {"daily_limit": 2}},
            {"boss": ["job-1", "job-2"]},
            db_path=db_path,
            boss_greeting="您好",
            min_delay_seconds=0,
            max_delay_seconds=0,
            stop_event=stop_event,
        )

    assert [attempt.job_id for attempt in attempts] == ["job-1"]
    assert _claim_statuses(db_path) == ["consumed"]


def test_automatic_scoring_rejects_a_batch_without_fresh_trace(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    db = get_db(db_path)
    try:
        insert_job(db, _job())
    finally:
        db.close()

    def fake_score(config, **_kwargs):
        config["_workbench_score_checkpoint"](
            {"status": "completed", "remaining_job_ids": []}
        )

    with patch("bosshunter.automation.scoring.score_jobs", side_effect=fake_score):
        result = score_collected_jobs(
            {"scoring": {"threshold": 60}},
            ["job-1"],
            threshold=60,
            max_per_platform=2,
            db_path=db_path,
        )

    assert result["scoring_complete"] is False
    assert result["scoring_trace_missing_job_ids"] == ["job-1"]
    assert result["eligible_job_ids"] == []


def test_internal_automatic_trace_marker_is_not_exposed_by_sanitizer():
    from bosshunter.ai import scorer

    result = scorer._structured_score_result(
        {
            "role_summary": "backend",
            "core_duties": {"score": 34, "evidence": "e"},
            "transferable_evidence": {"score": 21, "evidence": "e"},
            "hard_requirements": {"score": 12, "evidence": "e"},
            "tools_industry": {"score": 7, "evidence": "e"},
            "practical_fit": {"score": 8, "evidence": "e"},
            "caps": [],
            "hard_gaps": [],
            "reason": "matched",
            "missing": "",
        }
    )
    assert result is not None
    trace = scorer.build_score_trace(result, automatic_run_id="run-1")
    assert trace["_automatic_run_id"] == "run-1"
    safe = sanitize_score_trace(trace)
    assert safe is not None
    assert "_automatic_run_id" not in safe
