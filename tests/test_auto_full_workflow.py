from __future__ import annotations

import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from bosshunter.automation.delivery import deliver_eligible_jobs
from bosshunter.automation.collector import collect_selected_platforms
from bosshunter.automation.full_flow import select_eligible_jobs
from bosshunter.automation.models import AutomationPhase, DeliveryAttempt
from bosshunter.automation.runner import AutoFullRunner
from bosshunter.db import get_db, insert_job


def _job(job_id: str, platform: str, *, score: int = 80, status: str = "ready") -> dict:
    return {
        "id": job_id,
        "title": f"{platform} test job {job_id}",
        "company": f"{platform} company",
        "source_platform": platform,
        "status": status,
        "score": score,
        "hr_name": f"HR-{job_id}",
        "url": f"https://example.test/{platform}/{job_id}",
    }


class AutoFullCollectionTests(TestCase):
    def test_runtime_handles_are_preserved_while_platform_configs_are_isolated(self):
        stop_event = threading.Event()
        start_together = threading.Barrier(2)
        callback_lock = threading.Lock()
        observed: dict[str, dict] = {}
        logs: list[str] = []
        progress_updates: list[dict] = []
        base_config = {
            "nested": {"values": []},
            "_workbench_stop_event": stop_event,
            "_workbench_log": lambda message: None,
            "_workbench_collect_progress": lambda state: None,
        }

        class FakeOrchestrator:
            def __init__(self, config, **kwargs):
                self.config = config

            def run(self, options):
                platform = options["platform_order"][0]
                start_together.wait(timeout=3)
                self.config["nested"]["values"].append(platform)
                self.config["_workbench_log"]("collecting")
                self.config["_workbench_collect_progress"]({"status": "running"})
                with callback_lock:
                    observed[platform] = {
                        "stop_event_preserved": self.config["_workbench_stop_event"] is stop_event,
                        "runtime_callbacks_callable": callable(self.config["_workbench_log"])
                        and callable(self.config["_workbench_collect_progress"]),
                        "nested_values": list(self.config["nested"]["values"]),
                    }
                return {
                    "run_id": f"{platform}-run",
                    "platforms": {platform: {"status": "completed", "new": 1}},
                    "collected_job_ids": [f"{platform}-job"],
                }

        def log(message):
            with callback_lock:
                logs.append(message)

        def progress(state):
            with callback_lock:
                progress_updates.append(state)

        options = {
            "platform_order": ["boss", "zhilian"],
            "platforms": {"boss": {"search": {"keyword": "python"}}, "zhilian": {"search": {"keyword": "python"}}},
        }
        with patch("bosshunter.automation.collector.CollectionOrchestrator", FakeOrchestrator):
            result = collect_selected_platforms(
                base_config,
                options,
                db_path=Path("unused.db"),
                stop_event=stop_event,
                log=log,
                progress=progress,
            )

        self.assertEqual(set(result.collected_job_ids), {"boss-job", "zhilian-job"})
        self.assertFalse(result.errors)
        self.assertEqual(set(observed), {"boss", "zhilian"})
        self.assertTrue(all(item["stop_event_preserved"] for item in observed.values()))
        self.assertTrue(all(item["runtime_callbacks_callable"] for item in observed.values()))
        self.assertEqual(observed["boss"]["nested_values"], ["boss"])
        self.assertEqual(observed["zhilian"]["nested_values"], ["zhilian"])
        self.assertEqual(base_config["nested"]["values"], [])
        self.assertEqual(len(logs), 2)
        self.assertEqual({item["platform"] for item in progress_updates}, {"boss", "zhilian"})


class AutoFullSelectionTests(TestCase):
    def test_selects_only_current_batch_supported_platforms_and_threshold(self):
        rows = [
            _job("boss-good", "boss", score=80),
            _job("zhilian-good", "zhilian", score=60),
            _job("boss-low", "boss", score=59),
            _job("old-good", "boss", score=99),
            _job("liepin-good", "liepin", score=100),
        ]

        selected = select_eligible_jobs(
            rows,
            ["boss-good", "zhilian-good", "boss-low", "liepin-good"],
            threshold=60,
        )

        self.assertEqual(selected, {"boss": ["boss-good"], "zhilian": ["zhilian-good"]})

    def test_status_must_be_ready_or_approved(self):
        rows = [_job("sent", "boss", score=100, status="sent")]
        self.assertEqual(select_eligible_jobs(rows, ["sent"], threshold=0), {})

    def test_missing_platform_is_not_inferred_as_boss(self):
        rows = [
            {**_job("missing-platform", "boss", score=95), "source_platform": ""},
            {**_job("unknown-platform", "boss", score=95), "source_platform": "unknown"},
            _job("explicit-boss", "boss", score=95),
        ]
        selected = select_eligible_jobs(
            rows,
            ["missing-platform", "unknown-platform", "explicit-boss"],
            threshold=60,
        )
        self.assertEqual(selected, {"boss": ["explicit-boss"]})

    def test_delivery_limit_is_per_platform_and_highest_scores_win(self):
        rows = [
            _job("boss-low", "boss", score=70),
            _job("boss-high", "boss", score=95),
            _job("boss-mid", "boss", score=80),
            _job("zhilian-low", "zhilian", score=75),
            _job("zhilian-high", "zhilian", score=90),
        ]

        selected = select_eligible_jobs(
            rows,
            [row["id"] for row in rows],
            threshold=60,
            max_per_platform=2,
        )

        self.assertEqual(selected, {
            "boss": ["boss-high", "boss-mid"],
            "zhilian": ["zhilian-high", "zhilian-low"],
        })

    def test_invalid_delivery_limit_fails_closed(self):
        for limit in (0, 4, 1.5, True, "three"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                select_eligible_jobs([], [], threshold=0, max_per_platform=limit)


class AutoFullQueueTests(TestCase):
    def test_platforms_overlap_but_each_platform_is_serial_and_delay_is_bounded(self):
        job_platform = {
            "boss-1": "boss",
            "boss-2": "boss",
            "zhilian-1": "zhilian",
            "zhilian-2": "zhilian",
        }
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        active = {"boss": 0, "zhilian": 0}
        max_active = {"boss": 0, "zhilian": 0}
        calls: list[tuple[str, str]] = []
        sleeps: list[float] = []
        first_call = {"boss": True, "zhilian": True}

        def fake_sender(config, force=False, db_path=None):
            job_id = next(iter(config["_workbench_job_ids"]))
            platform = job_platform[job_id]
            if first_call[platform]:
                first_call[platform] = False
                barrier.wait(timeout=2)
            with lock:
                active[platform] += 1
                max_active[platform] = max(max_active[platform], active[platform])
                calls.append((platform, job_id))
            time.sleep(0.01)
            with lock:
                active[platform] -= 1
            config["_workbench_send_report"] = {
                "sent_count": 1,
                "failed_count": 0,
                "stop_reason": None,
            }

        with patch("bosshunter.automation.delivery.prepare_eligible_jobs"), patch(
            "bosshunter.automation.delivery.send_greetings", side_effect=fake_sender
        ):
            attempts = deliver_eligible_jobs(
                {},
                {
                    "boss": ["boss-1", "boss-2"],
                    "zhilian": ["zhilian-1", "zhilian-2"],
                },
                db_path=Path("unused.db"),
                boss_greeting="您好",
                min_delay_seconds=0,
                max_delay_seconds=0,
                sleeper=lambda seconds: sleeps.append(seconds),
            )

        self.assertEqual(len(attempts), 4)
        self.assertTrue(all(attempt.safe_success for attempt in attempts))
        self.assertEqual(max_active, {"boss": 1, "zhilian": 1})
        self.assertEqual({platform for platform, _ in calls}, {"boss", "zhilian"})
        self.assertTrue(all(0 <= value <= 180 for value in sleeps))

    def test_unverified_send_is_reported_as_failure(self):
        def fake_sender(config, force=False, db_path=None):
            config["_workbench_send_report"] = {
                "sent_count": 0,
                "failed_count": 0,
                "stop_reason": "platform conversation could not be selected safely",
            }

        with patch("bosshunter.automation.delivery.prepare_eligible_jobs"), patch(
            "bosshunter.automation.delivery.send_greetings", side_effect=fake_sender
        ):
            attempts = deliver_eligible_jobs(
                {},
                {"boss": ["boss-1"]},
                db_path=Path("unused.db"),
                boss_greeting="您好",
                min_delay_seconds=0,
                max_delay_seconds=0,
            )

        self.assertEqual(len(attempts), 1)
        self.assertFalse(attempts[0].safe_success)
        self.assertEqual(attempts[0].status, "platform conversation could not be selected safely")


class AutoFullRunnerTests(TestCase):
    def test_runner_scores_search_matches_even_when_collection_added_no_new_rows(self):
        collection = type(
            "CollectionResult",
            (),
            {
                "collected_job_ids": [],
                "matched_job_ids": ["boss-existing"],
                "platform_states": {"boss": {"status": "completed_with_shortage", "new": 0, "duplicate": 1}},
                "errors": {},
            },
        )()
        score_result = {
            "eligible_by_platform": {"boss": ["boss-existing"]},
            "eligible_job_ids": ["boss-existing"],
            "scoring_complete": True,
        }
        attempts = [DeliveryAttempt("boss", "boss-existing", True, True)]
        with TemporaryDirectory() as tmp, patch(
            "bosshunter.automation.runner.collect_selected_platforms", return_value=collection
        ), patch(
            "bosshunter.automation.runner.score_collected_jobs", return_value=score_result
        ) as score, patch(
            "bosshunter.automation.runner.deliver_eligible_jobs", return_value=attempts
        ), patch(
            "bosshunter.automation.runner.reconcile_deliveries",
            return_value={"ok": True, "successful_job_ids": ["boss-existing"]},
        ):
            result = AutoFullRunner(
                {"scoring": {"threshold": 60}, "automation": {"boss_greeting": "您好"}},
                options={"platform_order": ["boss"], "platforms": {"boss": {}}},
                auto_approve_delivery=True,
                db_path=Path(tmp) / "test.db",
            ).run()

        self.assertEqual(result.phase, AutomationPhase.COMPLETED)
        self.assertEqual(result.collected_job_ids, [])
        self.assertEqual(result.matched_job_ids, ["boss-existing"])
        self.assertEqual(result.succeeded_job_ids, ["boss-existing"])
        self.assertEqual(score.call_args.args[1], ["boss-existing"])

    def test_runner_requires_confirmation_by_default(self):
        collection = type(
            "CollectionResult",
            (),
            {"collected_job_ids": ["boss-1"], "platform_states": {}, "errors": {}},
        )()
        score_result = {
            "eligible_by_platform": {"boss": ["boss-1"]},
            "eligible_job_ids": ["boss-1"],
            "scoring_complete": True,
        }
        with TemporaryDirectory() as tmp, patch(
            "bosshunter.automation.runner.collect_selected_platforms", return_value=collection
        ), patch(
            "bosshunter.automation.runner.score_collected_jobs", return_value=score_result
        ), patch("bosshunter.automation.runner.deliver_eligible_jobs") as deliver:
            result = AutoFullRunner(
                {"scoring": {"threshold": 60}, "automation": {"boss_greeting": "您好"}},
                options={"platform_order": ["boss"], "platforms": {"boss": {}}},
                db_path=Path(tmp) / "test.db",
            ).run()

        self.assertEqual(result.stop_reason, "delivery_not_confirmed")
        deliver.assert_not_called()

    def test_explicit_auto_approval_sends_all_eligible_jobs_without_callback(self):
        collection = type(
            "CollectionResult",
            (),
            {"collected_job_ids": ["boss-1", "zhilian-1"], "platform_states": {}, "errors": {}},
        )()
        score_result = {
            "eligible_by_platform": {"boss": ["boss-1"], "zhilian": ["zhilian-1"]},
            "eligible_job_ids": ["boss-1", "zhilian-1"],
            "scoring_complete": True,
        }
        attempts = [
            DeliveryAttempt("boss", "boss-1", True, True),
            DeliveryAttempt("zhilian", "zhilian-1", True, True),
        ]
        with TemporaryDirectory() as tmp, patch(
            "bosshunter.automation.runner.collect_selected_platforms", return_value=collection
        ), patch(
            "bosshunter.automation.runner.score_collected_jobs", return_value=score_result
        ), patch(
            "bosshunter.automation.runner.deliver_eligible_jobs", return_value=attempts
        ) as deliver, patch(
            "bosshunter.automation.runner.reconcile_deliveries",
            return_value={"ok": True, "successful_job_ids": ["boss-1", "zhilian-1"]},
        ):
            result = AutoFullRunner(
                {"scoring": {"threshold": 60}, "automation": {"boss_greeting": "您好"}},
                options={"platform_order": ["boss", "zhilian"], "platforms": {"boss": {}, "zhilian": {}}},
                auto_approve_delivery=True,
                db_path=Path(tmp) / "test.db",
            ).run()

        self.assertEqual(result.phase, AutomationPhase.COMPLETED)
        self.assertEqual(result.approved_job_ids, ["boss-1", "zhilian-1"])
        self.assertEqual(result.succeeded_job_ids, ["boss-1", "zhilian-1"])
        delivered = deliver.call_args.args[1]
        self.assertEqual(delivered, {"boss": ["boss-1"], "zhilian": ["zhilian-1"]})

    def test_empty_collection_is_not_reported_as_plain_success(self):
        collection = type(
            "CollectionResult",
            (),
            {"collected_job_ids": [], "platform_states": {"boss": {"status": "completed"}}, "errors": {}},
        )()
        with TemporaryDirectory() as tmp, patch(
            "bosshunter.automation.runner.collect_selected_platforms", return_value=collection
        ), patch("bosshunter.automation.runner.deliver_eligible_jobs") as deliver:
            result = AutoFullRunner(
                {"scoring": {"threshold": 60}, "automation": {"boss_greeting": "您好"}},
                options={"platform_order": ["boss"], "platforms": {"boss": {}}},
                db_path=Path(tmp) / "test.db",
            ).run()
        self.assertEqual(result.phase, AutomationPhase.FAILED)
        self.assertEqual(result.stop_reason, "collection_no_candidates")
        self.assertIn("collection", result.errors)
        deliver.assert_not_called()

    def test_no_eligible_jobs_is_not_sent_as_an_empty_delivery(self):
        collection = type(
            "CollectionResult",
            (),
            {"collected_job_ids": ["boss-1"], "platform_states": {}, "errors": {}},
        )()
        score_result = {
            "eligible_by_platform": {},
            "eligible_job_ids": [],
            "scoring_complete": True,
        }
        with TemporaryDirectory() as tmp, patch(
            "bosshunter.automation.runner.collect_selected_platforms", return_value=collection
        ), patch(
            "bosshunter.automation.runner.score_collected_jobs", return_value=score_result
        ), patch("bosshunter.automation.runner.deliver_eligible_jobs") as deliver:
            result = AutoFullRunner(
                {"scoring": {"threshold": 60}, "automation": {"boss_greeting": "您好"}},
                options={"platform_order": ["boss"], "platforms": {"boss": {}}},
                db_path=Path(tmp) / "test.db",
            ).run()
        self.assertEqual(result.phase, AutomationPhase.FAILED)
        self.assertEqual(result.stop_reason, "no_eligible_jobs")
        self.assertIn("delivery", result.errors)
        deliver.assert_not_called()
    def test_runner_fails_closed_when_scoring_is_incomplete(self):
        collection = type(
            "CollectionResult",
            (),
            {"collected_job_ids": ["boss-1"], "platform_states": {}, "errors": {}},
        )()
        score_result = {
            "eligible_by_platform": {"boss": ["boss-1"]},
            "eligible_job_ids": ["boss-1"],
            "scoring_complete": False,
            "scoring_incomplete_job_ids": ["boss-1"],
        }

        with TemporaryDirectory() as tmp, patch(
            "bosshunter.automation.runner.collect_selected_platforms", return_value=collection
        ), patch(
            "bosshunter.automation.runner.score_collected_jobs", return_value=score_result
        ), patch("bosshunter.automation.runner.deliver_eligible_jobs") as deliver:
            result = AutoFullRunner(
                {"scoring": {"threshold": 70}, "automation": {"boss_greeting": "您好"}},
                options={"platform_order": ["boss"], "platforms": {"boss": {}}},
                db_path=Path(tmp) / "test.db",
            ).run()

        self.assertEqual(result.phase, AutomationPhase.FAILED)
        self.assertEqual(result.stop_reason, "scoring_incomplete")
        deliver.assert_not_called()

    def test_runner_completes_only_after_reconciliation(self):
        collection = type(
            "CollectionResult",
            (),
            {
                "collected_job_ids": ["boss-1", "zhilian-1"],
                "platform_states": {"boss": {"status": "completed"}, "zhilian": {"status": "completed"}},
                "errors": {},
            },
        )()
        attempts = [
            DeliveryAttempt("boss", "boss-1", True, True),
            DeliveryAttempt("zhilian", "zhilian-1", True, True),
        ]
        score_result = {
            "eligible_by_platform": {"boss": ["boss-1"], "zhilian": ["zhilian-1"]},
            "eligible_job_ids": ["boss-1", "zhilian-1"],
            "scoring_complete": True,
        }

        with TemporaryDirectory() as tmp, patch(
            "bosshunter.automation.runner.collect_selected_platforms", return_value=collection
        ), patch(
            "bosshunter.automation.runner.score_collected_jobs", return_value=score_result
        ), patch(
            "bosshunter.automation.runner.deliver_eligible_jobs", return_value=attempts
        ), patch(
            "bosshunter.automation.runner.reconcile_deliveries",
            return_value={"ok": True, "successful_job_ids": ["boss-1", "zhilian-1"]},
        ):
            result = AutoFullRunner(
                {"scoring": {"threshold": 70}, "automation": {"boss_greeting": "您好"}},
                options={"platform_order": ["boss", "zhilian"], "platforms": {"boss": {}, "zhilian": {}}},
                confirm_delivery=lambda ids: ids,
                db_path=Path(tmp) / "test.db",
            ).run()

        self.assertEqual(result.phase, AutomationPhase.COMPLETED)
        self.assertEqual(result.succeeded_job_ids, ["boss-1", "zhilian-1"])
        self.assertEqual(result.failed_job_ids, [])

    def test_runner_fails_closed_when_any_delivery_is_not_verified(self):
        collection = type(
            "CollectionResult",
            (),
            {"collected_job_ids": ["boss-1"], "platform_states": {}, "errors": {}},
        )()
        score_result = {
            "eligible_by_platform": {"boss": ["boss-1"]},
            "eligible_job_ids": ["boss-1"],
            "scoring_complete": True,
        }
        attempts = [DeliveryAttempt("boss", "boss-1", False, False, status="risk_lock")]

        with TemporaryDirectory() as tmp, patch(
            "bosshunter.automation.runner.collect_selected_platforms", return_value=collection
        ), patch(
            "bosshunter.automation.runner.score_collected_jobs", return_value=score_result
        ), patch(
            "bosshunter.automation.runner.deliver_eligible_jobs", return_value=attempts
        ), patch("bosshunter.automation.runner.reconcile_deliveries") as reconcile:
            result = AutoFullRunner(
                {"scoring": {"threshold": 70}, "automation": {"boss_greeting": "您好"}},
                options={"platform_order": ["boss"], "platforms": {"boss": {}}},
                confirm_delivery=lambda ids: ids,
                db_path=Path(tmp) / "test.db",
            ).run()

        self.assertEqual(result.phase, AutomationPhase.FAILED)
        self.assertEqual(result.stop_reason, "delivery_not_safely_verified")
        reconcile.assert_not_called()

    def test_runner_reconciles_verified_delivery_and_monitors_partial_batch(self):
        collection = type(
            "CollectionResult",
            (),
            {"collected_job_ids": ["boss-1", "zhilian-1"], "platform_states": {}, "errors": {}},
        )()
        score_result = {
            "eligible_by_platform": {"boss": ["boss-1"], "zhilian": ["zhilian-1"]},
            "eligible_job_ids": ["boss-1", "zhilian-1"],
            "scoring_complete": True,
        }
        attempts = [
            DeliveryAttempt("boss", "boss-1", True, True, status="sent"),
            DeliveryAttempt("zhilian", "zhilian-1", False, False, status="application_contact_not_ready"),
        ]

        with TemporaryDirectory() as tmp, patch(
            "bosshunter.automation.runner.collect_selected_platforms", return_value=collection
        ), patch(
            "bosshunter.automation.runner.score_collected_jobs", return_value=score_result
        ), patch(
            "bosshunter.automation.runner.deliver_eligible_jobs", return_value=attempts
        ), patch(
            "bosshunter.automation.runner.reconcile_deliveries",
            return_value={"ok": True, "successful_deliveries": [{"platform": "boss", "job_id": "boss-1"}]},
        ) as reconcile:
            result = AutoFullRunner(
                {"scoring": {"threshold": 70}, "automation": {"boss_greeting": "\u60a8\u597d"}},
                options={"platform_order": ["boss", "zhilian"], "platforms": {"boss": {}, "zhilian": {}}},
                confirm_delivery=lambda ids: ids,
                db_path=Path(tmp) / "test.db",
            ).run()

        self.assertEqual(result.phase, AutomationPhase.PARTIAL_COMPLETED)
        self.assertEqual(result.stop_reason, "delivery_partially_completed")
        self.assertEqual(result.succeeded_job_ids, ["boss-1"])
        self.assertEqual(result.failed_job_ids, ["zhilian-1"])
        self.assertIn("verified deliveries were reconciled locally", result.errors["delivery"])
        reconcile.assert_called_once_with(
            Path(tmp) / "test.db",
            [{"platform": "boss", "job_id": "boss-1"}],
        )

    def test_runner_reconciles_verified_subset_before_honoring_stop_after_delivery(self):
        collection = type(
            "CollectionResult",
            (),
            {"collected_job_ids": ["boss-1", "zhilian-1"], "platform_states": {}, "errors": {}},
        )()
        score_result = {
            "eligible_by_platform": {"boss": ["boss-1"], "zhilian": ["zhilian-1"]},
            "eligible_job_ids": ["boss-1", "zhilian-1"],
            "scoring_complete": True,
        }
        attempts = [
            DeliveryAttempt("boss", "boss-1", True, True, status="sent"),
            DeliveryAttempt("zhilian", "zhilian-1", False, False, status="not_verified"),
        ]
        stop_event = threading.Event()

        def stop_after_delivery(*_args, **_kwargs):
            stop_event.set()
            return attempts

        with TemporaryDirectory() as tmp, patch(
            "bosshunter.automation.runner.collect_selected_platforms", return_value=collection
        ), patch(
            "bosshunter.automation.runner.score_collected_jobs", return_value=score_result
        ), patch(
            "bosshunter.automation.runner.deliver_eligible_jobs", side_effect=stop_after_delivery
        ), patch(
            "bosshunter.automation.runner.reconcile_deliveries",
            return_value={
                "ok": True,
                "successful_deliveries": [{"platform": "boss", "job_id": "boss-1"}],
            },
        ) as reconcile:
            result = AutoFullRunner(
                {"scoring": {"threshold": 70}, "automation": {"boss_greeting": "您好"}},
                options={"platform_order": ["boss", "zhilian"], "platforms": {"boss": {}, "zhilian": {}}},
                db_path=Path(tmp) / "test.db",
                stop_event=stop_event,
                auto_approve_delivery=True,
            ).run()

        self.assertEqual(result.phase, AutomationPhase.STOPPED)
        self.assertEqual(result.stop_reason, "user_stopped_after_verified_delivery")
        self.assertEqual(result.succeeded_job_ids, ["boss-1"])
        self.assertEqual(result.failed_job_ids, ["zhilian-1"])
        reconcile.assert_called_once_with(
            Path(tmp) / "test.db",
            [{"platform": "boss", "job_id": "boss-1"}],
        )

    def test_runner_reports_reconciliation_failure_for_verified_subset(self):
        collection = type(
            "CollectionResult",
            (),
            {"collected_job_ids": ["boss-1", "zhilian-1"], "platform_states": {}, "errors": {}},
        )()
        score_result = {
            "eligible_by_platform": {"boss": ["boss-1"], "zhilian": ["zhilian-1"]},
            "eligible_job_ids": ["boss-1", "zhilian-1"],
            "scoring_complete": True,
        }
        attempts = [
            DeliveryAttempt("boss", "boss-1", True, True),
            DeliveryAttempt("zhilian", "zhilian-1", False, False),
        ]

        with TemporaryDirectory() as tmp, patch(
            "bosshunter.automation.runner.collect_selected_platforms", return_value=collection
        ), patch(
            "bosshunter.automation.runner.score_collected_jobs", return_value=score_result
        ), patch(
            "bosshunter.automation.runner.deliver_eligible_jobs", return_value=attempts
        ), patch(
            "bosshunter.automation.runner.reconcile_deliveries", return_value={"ok": False}
        ) as reconcile:
            result = AutoFullRunner(
                {"scoring": {"threshold": 70}, "automation": {"boss_greeting": "\u60a8\u597d"}},
                options={"platform_order": ["boss", "zhilian"], "platforms": {"boss": {}, "zhilian": {}}},
                confirm_delivery=lambda ids: ids,
                db_path=Path(tmp) / "test.db",
            ).run()

        self.assertEqual(result.phase, AutomationPhase.FAILED)
        self.assertEqual(result.stop_reason, "conversation_reconciliation_failed")
        reconcile.assert_called_once()

    def test_collection_failure_on_either_platform_stops_before_scoring(self):
        collection = type(
            "CollectionResult",
            (),
            {
                "collected_job_ids": ["boss-1", "zhilian-1"],
                "platform_states": {
                    "boss": {"status": "completed"},
                    "zhilian": {"status": "failed", "error": "blocked"},
                },
                "errors": {"zhilian": "platform blocked"},
            },
        )()

        with TemporaryDirectory() as tmp, patch(
            "bosshunter.automation.runner.collect_selected_platforms", return_value=collection
        ), patch("bosshunter.automation.runner.score_collected_jobs") as score, patch(
            "bosshunter.automation.runner.deliver_eligible_jobs"
        ) as deliver, patch("bosshunter.automation.runner.reconcile_deliveries") as reconcile:
            result = AutoFullRunner(
                {"scoring": {"threshold": 60}, "automation": {"boss_greeting": "您好"}},
                options={
                    "platform_order": ["boss", "zhilian"],
                    "max_deliveries_per_platform": 3,
                    "platforms": {"boss": {}, "zhilian": {}},
                },
                db_path=Path(tmp) / "test.db",
            ).run()

        self.assertEqual(result.phase, AutomationPhase.FAILED)
        self.assertEqual(result.stop_reason, "collection_failed")
        score.assert_not_called()
        deliver.assert_not_called()
        reconcile.assert_not_called()

    def test_invalid_limit_is_rejected_before_collection(self):
        with TemporaryDirectory() as tmp, patch(
            "bosshunter.automation.runner.collect_selected_platforms"
        ) as collect:
            runner = AutoFullRunner(
                {"scoring": {"threshold": 60}, "automation": {"boss_greeting": "您好"}},
                options={
                    "platform_order": ["boss"],
                    "max_deliveries_per_platform": 1.5,
                    "platforms": {"boss": {}},
                },
                db_path=Path(tmp) / "test.db",
            )
            with self.assertRaises(ValueError):
                runner.run()
        collect.assert_not_called()

    def test_reconciliation_is_idempotent_for_successful_deliveries(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            conn = get_db(db_path)
            for job_id, platform in (("boss-1", "boss"), ("zhilian-1", "zhilian")):
                insert_job(conn, _job(job_id, platform))
                conn.execute("UPDATE jobs SET status='sent', score=85 WHERE id=?", (job_id,))
                conn.execute("INSERT INTO history(job_id, action, detail) VALUES (?, 'sent', '您好')", (job_id,))
            conn.commit()
            conn.close()

            from bosshunter.automation.reconciliation import reconcile_deliveries

            first = reconcile_deliveries(db_path, ["boss-1", "zhilian-1"])
            second = reconcile_deliveries(db_path, ["boss-1", "zhilian-1"])

            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertEqual(first["summary"]["created"], 2)
            self.assertEqual(second["summary"]["created"], 0)

    def test_reconciliation_requires_the_verified_platform_to_match(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            conn = get_db(db_path)
            insert_job(conn, _job("boss-1", "boss"))
            conn.execute("UPDATE jobs SET status='sent', score=85 WHERE id=?", ("boss-1",))
            conn.execute(
                "INSERT INTO history(job_id, action, detail) VALUES (?, 'sent', ?)",
                ("boss-1", "您好"),
            )
            conn.commit()
            conn.close()

            from bosshunter.automation.reconciliation import reconcile_deliveries

            result = reconcile_deliveries(
                db_path,
                [{"platform": "zhilian", "job_id": "boss-1"}],
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["missing_job_ids"], ["boss-1"])


if __name__ == "__main__":
    import unittest

    unittest.main()
