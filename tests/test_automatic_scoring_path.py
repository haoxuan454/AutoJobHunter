import sqlite3
import threading
from pathlib import Path
from unittest.mock import patch

from bosshunter.ai import scorer
from bosshunter.automation.scoring import score_collected_jobs
from bosshunter.db import get_db, get_score_trace, insert_job
from bosshunter.token_usage import record_token_usage


def _job(job_id: str = "job-1") -> dict:
    return {
        "id": job_id,
        "title": "Python 工程师",
        "company": "测试公司",
        "salary": "10-15K",
        "city": "东莞",
        "experience": "1-3年",
        "education": "本科",
        "jd": "负责 Python 服务开发",
        "source_platform": "boss",
        "status": "pending",
        "score": 0,
    }


def test_automatic_scoring_passes_the_collection_database_path(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    db = get_db(db_path)
    try:
        insert_job(db, _job())
    finally:
        db.close()

    with patch("bosshunter.automation.scoring.score_jobs") as score:
        result = score_collected_jobs(
            {"scoring": {"threshold": 60}},
            ["job-1"],
            threshold=60,
            max_per_platform=2,
            db_path=db_path,
        )

    assert score.call_args.kwargs["db_path"] == db_path
    assert result["eligible_job_ids"] == []


def test_automatic_scoring_rescores_existing_search_matches_and_records_fresh_trace(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    db = get_db(db_path)
    try:
        insert_job(
            db,
            {
                **_job("existing-ready"),
                "status": "ready",
                "score": 78,
                "score_reason": "old score",
            },
        )
    finally:
        db.close()

    payload = {
        "role_summary": "Python backend",
        "core_duties": {"score": 36, "evidence": "backend delivery"},
        "transferable_evidence": {"score": 21, "evidence": "project experience"},
        "hard_requirements": {"score": 14, "evidence": "requirements match"},
        "tools_industry": {"score": 8, "evidence": "Python tooling"},
        "practical_fit": {"score": 9, "evidence": "city and schedule fit"},
        "caps": [],
        "hard_gaps": [],
        "reason": "fresh automatic score",
        "missing": "",
    }
    result = scorer._structured_score_result(payload)
    assert result is not None
    outcome = scorer.ScoreOutcome(result=result)

    with (
        patch("bosshunter.ai.scorer._load_resume", return_value="resume"),
        patch("bosshunter.ai.scorer.quick_score", return_value=(80, "pass")),
        patch("bosshunter.ai.scorer._score_job_with_ai", return_value=outcome),
    ):
        scored = score_collected_jobs(
            {"ai": {"scoring_concurrency": 1}, "scoring": {"threshold": 60}},
            ["existing-ready"],
            threshold=60,
            max_per_platform=2,
            db_path=db_path,
        )

    assert scored["scoring_complete"] is True
    assert scored["eligible_job_ids"] == ["existing-ready"]
    db = get_db(db_path)
    try:
        found, trace = get_score_trace(db, "existing-ready")
    finally:
        db.close()
    assert found is True
    assert trace is not None
    assert trace["_automatic_run_id"]


def test_automatic_scoring_mixed_batch_skips_terminal_job_and_keeps_it_out_of_delivery(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    db = get_db(db_path)
    try:
        insert_job(db, _job("pending-job"))
        insert_job(db, {**_job("already-sent"), "status": "sent", "score": 95})
        db.execute("UPDATE jobs SET status='sent', score=95 WHERE id='already-sent'")
        db.commit()
    finally:
        db.close()

    payload = {
        "role_summary": "Python backend",
        "core_duties": {"score": 36, "evidence": "backend delivery"},
        "transferable_evidence": {"score": 21, "evidence": "project experience"},
        "hard_requirements": {"score": 14, "evidence": "requirements match"},
        "tools_industry": {"score": 8, "evidence": "Python tooling"},
        "practical_fit": {"score": 9, "evidence": "city and schedule fit"},
        "caps": [], "hard_gaps": [], "reason": "fresh automatic score", "missing": "",
    }
    outcome = scorer.ScoreOutcome(result=scorer._structured_score_result(payload))
    with (
        patch("bosshunter.ai.scorer._load_resume", return_value="resume"),
        patch("bosshunter.ai.scorer.quick_score", return_value=(80, "pass")),
        patch("bosshunter.ai.scorer._score_job_with_ai", return_value=outcome),
    ):
        result = score_collected_jobs(
            {"ai": {"scoring_concurrency": 1}, "scoring": {"threshold": 60}},
            ["pending-job", "already-sent"], threshold=60, max_per_platform=2,
            db_path=db_path,
        )

    assert result["scoring_complete"] is True
    assert result["scored_job_ids"] == ["pending-job"]
    assert result["skipped_job_ids"] == ["already-sent"]
    assert result["eligible_job_ids"] == ["pending-job"]


def test_automatic_scoring_all_terminal_jobs_is_a_safe_noop(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    db = get_db(db_path)
    try:
        insert_job(db, {**_job("sent-job"), "status": "sent", "score": 90})
        insert_job(db, {**_job("rejected-job"), "status": "rejected", "score": 90})
        db.execute("UPDATE jobs SET status='sent', score=90 WHERE id='sent-job'")
        db.execute("UPDATE jobs SET status='rejected', score=90 WHERE id='rejected-job'")
        db.commit()
    finally:
        db.close()

    with patch("bosshunter.automation.scoring.score_jobs") as score:
        result = score_collected_jobs(
            {"scoring": {"threshold": 60}}, ["sent-job", "rejected-job"],
            threshold=60, max_per_platform=2, db_path=db_path,
        )

    score.assert_not_called()
    assert result["scoring_complete"] is True
    assert result["scoring_checkpoint_status"] == "skipped"
    assert result["eligible_job_ids"] == []
    assert result["skipped_job_ids"] == ["sent-job", "rejected-job"]


def test_automatic_scoring_unknown_status_remains_fail_closed(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    db = get_db(db_path)
    try:
        insert_job(db, {**_job("mystery-job"), "status": "mystery"})
        db.execute("UPDATE jobs SET status='mystery' WHERE id='mystery-job'")
        db.commit()
    finally:
        db.close()

    with patch("bosshunter.automation.scoring.score_jobs") as score:
        result = score_collected_jobs(
            {"scoring": {"threshold": 60}}, ["mystery-job"], threshold=60,
            max_per_platform=2, db_path=db_path,
        )

    score.assert_not_called()
    assert result["scoring_complete"] is False
    assert result["unknown_status_job_ids"] == ["mystery-job"]
    assert result["scoring_incomplete_job_ids"] == ["mystery-job"]
    assert result["eligible_job_ids"] == []


def test_unknown_platform_is_incomplete_even_when_existing_score_is_terminal(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    db = get_db(db_path)
    try:
        insert_job(
            db,
            {
                **_job(),
                "source_platform": "unknown",
                "status": "ready",
                "score": 95,
            },
        )
    finally:
        db.close()

    with patch("bosshunter.automation.scoring.score_jobs"):
        result = score_collected_jobs(
            {"scoring": {"threshold": 60}},
            ["job-1"],
            threshold=60,
            max_per_platform=2,
            db_path=db_path,
        )

    assert result["scoring_complete"] is False
    assert result["invalid_platform_job_ids"] == ["job-1"]
    assert result["eligible_job_ids"] == []


def test_delivery_config_with_runtime_event_is_not_deepcopied(tmp_path: Path):
    from bosshunter.automation.delivery import deliver_eligible_jobs

    db_path = tmp_path / "runtime" / "bosshunter.db"
    db = get_db(db_path)
    try:
        insert_job(db, {**_job(), "status": "ready", "score": 85})
    finally:
        db.close()

    observed = {}

    def fake_sender(config, **_kwargs):
        observed["event"] = config["_workbench_stop_event"]
        config["_workbench_send_report"] = {"sent_count": 1, "failed_count": 0}

    with patch("bosshunter.automation.delivery.prepare_eligible_jobs"), patch(
        "bosshunter.automation.delivery.send_greetings", side_effect=fake_sender
    ):
        stop_event = threading.Event()
        attempts = deliver_eligible_jobs(
            {"_workbench_stop_event": stop_event, "nested": {"value": "safe"}},
            {"boss": ["job-1"]},
            db_path=db_path,
            boss_greeting="您好",
            min_delay_seconds=0,
            max_delay_seconds=0,
            stop_event=stop_event,
        )

    assert attempts[0].safe_success is True
    assert observed["event"] is stop_event


def test_explicit_scoring_database_is_used_and_failure_reason_is_persisted(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    db = get_db(db_path)
    try:
        insert_job(db, _job())
    finally:
        db.close()

    with (
        patch("bosshunter.ai.scorer._load_resume", return_value="resume"),
        patch("bosshunter.ai.scorer.quick_score", return_value=(80, "通过")),
        patch(
            "bosshunter.ai.scorer._score_job_with_ai",
            side_effect=sqlite3.OperationalError("database is locked"),
        ),
    ):
        scored, filtered = scorer.score_jobs(
            {"ai": {"scoring_concurrency": 1}, "scoring": {"threshold": 60}},
            scope="selected",
            job_ids=["job-1"],
            db_path=db_path,
        )

    assert (scored, filtered) == (0, 0)
    db = get_db(db_path)
    try:
        history = db.execute(
            "SELECT action, detail FROM history WHERE job_id = 'job-1' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        db.close()
    assert history["action"] == "score_failed"
    assert "OperationalError" in history["detail"]
    assert "database is locked" in history["detail"]


def test_token_usage_ledger_uses_automatic_workflow_database(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    record_token_usage(
        {"_db_path": str(db_path)},
        purpose="scoring",
        prompt="prompt",
        output="output",
        provider="deepseek",
        model="deepseek-flash",
    )

    db = get_db(db_path)
    try:
        row = db.execute(
            "SELECT provider, model, purpose FROM ai_token_usage ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        db.close()
    assert dict(row) == {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "purpose": "scoring",
    }


def test_scoring_commits_each_result_before_next_worker_writes_token_usage(tmp_path: Path):
    db_path = tmp_path / "runtime" / "bosshunter.db"
    db = get_db(db_path)
    try:
        insert_job(db, _job("job-1"))
        insert_job(db, _job("job-2"))
    finally:
        db.close()

    def score_with_token_write(job, _resume, config, _max_attempts):
        record_token_usage(
            config,
            purpose="scoring",
            prompt="score prompt",
            output="score result",
            provider="deepseek",
            model="deepseek-flash",
        )
        return scorer.ScoreOutcome(
            result=scorer.ScoreResult(
                score=85,
                raw_score=85,
                reason="matched",
                components={},
                caps=(),
                summary_reason="matched",
                missing="",
                structured=False,
                role_summary="",
                component_evidence={},
                hard_gaps=(),
                reviewed=False,
            )
        )

    # Keep the regression fast while retaining SQLite's real cross-connection
    # locking behavior: without a commit between workers, the second ledger
    # insert cannot acquire the write lock held by the scoring connection.
    with (
        patch("bosshunter.ai.scorer._load_resume", return_value="resume"),
        patch("bosshunter.ai.scorer.quick_score", return_value=(80, "pass")),
        patch("bosshunter.ai.scorer._score_job_with_ai", side_effect=score_with_token_write),
        patch("bosshunter.token_usage._TOKEN_DB_TIMEOUT_SECONDS", 0.05),
        patch("bosshunter.token_usage._TOKEN_DB_BUSY_TIMEOUT_MS", 50),
        patch("bosshunter.token_usage._TOKEN_DB_WRITE_ATTEMPTS", 1),
    ):
        scored, filtered = scorer.score_jobs(
            {
                "ai": {"scoring_concurrency": 1},
                "scoring": {"threshold": 60},
            },
            scope="selected",
            job_ids=["job-1", "job-2"],
            db_path=db_path,
        )

    db = get_db(db_path)
    try:
        usage_count = db.execute("SELECT COUNT(*) FROM ai_token_usage").fetchone()[0]
        failed_count = db.execute(
            "SELECT COUNT(*) FROM history WHERE action='score_failed'"
        ).fetchone()[0]
        statuses = [
            row[0]
            for row in db.execute(
                "SELECT status FROM jobs WHERE id IN ('job-1','job-2') ORDER BY id"
            ).fetchall()
        ]
    finally:
        db.close()

    assert (scored, filtered) == (2, 0)
    assert usage_count == 2
    assert failed_count == 0
    assert statuses == ["ready", "ready"]
