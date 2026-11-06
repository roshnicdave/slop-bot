import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cyberquiz.store import connect
from cyberquiz.health import findings, check, alert_scopes, publication_context


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.tmp.name) / "state.sqlite")
        self.cfg = {
            "generation_enabled": True,
            "publishing_enabled": True,
            "timezone": "UTC",
            "slots": ["12:35", "19:19"],
            "posts_per_day": 2,
        }

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def delivered_notice(self, db, event, facts):
        db.execute("INSERT OR IGNORE INTO notices VALUES(?,1,'sent')", (event,))
        db.commit()

    def test_missed_slot_and_empty_queue_include_actual_failure(self):
        self.db.execute(
            "CREATE TABLE readiness_attempts(id INTEGER PRIMARY KEY,status TEXT,error TEXT)"
        )
        self.db.execute(
            "INSERT INTO readiness_attempts VALUES(1,?,?)",
            ("failed:ValueError", "Source unavailable"),
        )
        issues = findings(
            self.db, self.cfg, dt.datetime(2026, 10, 30, 14, tzinfo=dt.timezone.utc)
        )
        self.assertEqual([i["kind"] for i in issues], ["queue_empty", "missed_post"])
        self.assertEqual(issues[0]["failure"]["error"], "Source unavailable")

    def test_operator_pause_does_not_report_empty_queue_or_missed_posts(self):
        self.cfg["emergency_pause"] = True
        self.assertEqual(findings(self.db, self.cfg), [])

    def test_empty_buffer_after_daily_target_is_not_a_delay_across_utc_midnight(self):
        from cyberquiz.store import new_job

        self.cfg["timezone"] = "America/Los_Angeles"
        clock = dt.datetime.fromisoformat("2026-11-06T04:00:00+00:00")
        for stamp in ("2026-11-05T21:30:00+00:00", "2026-11-06T03:30:00+00:00"):
            job = new_job(self.db, stamp)
            self.db.execute(
                "UPDATE jobs SET status='published',published_at=? WHERE id=?",
                (stamp, job),
            )
        self.db.execute(
            "CREATE TABLE readiness_attempts(id INTEGER PRIMARY KEY,status TEXT,error TEXT)"
        )
        self.db.execute("INSERT INTO readiness_attempts VALUES(1,'complete',NULL)")
        self.db.commit()
        issues = findings(self.db, self.cfg, clock)
        self.assertEqual([i["kind"] for i in issues], ["queue_empty"])
        self.assertFalse(issues[0]["actionable"])
        self.assertFalse(any(alert_scopes(issues).values()))
        context = publication_context(self.db, self.cfg, clock)
        self.assertEqual(context["confirmed_posts_today"], 2)
        self.assertTrue(context["daily_target_met"])
        self.assertEqual(context["local_date"], "2026-11-05")
        self.assertEqual(context["next_post_at"], "2026-11-06T12:35:00-08:00")

    def test_failed_refill_or_approaching_deadline_still_warns(self):
        clock = dt.datetime.fromisoformat("2026-11-06T03:00:00+00:00")
        self.db.execute(
            "CREATE TABLE readiness_attempts(id INTEGER PRIMARY KEY,status TEXT,error TEXT)"
        )
        self.db.execute(
            "INSERT INTO readiness_attempts VALUES(1,'failed:ValueError','Source unavailable')"
        )
        issues = findings(self.db, self.cfg, clock)
        self.assertTrue(alert_scopes(issues)["content"])
        self.db.execute("UPDATE readiness_attempts SET status='complete',error=NULL")
        self.assertFalse(any(alert_scopes(findings(self.db, self.cfg, clock)).values()))
        near = clock.replace(hour=12)
        self.assertTrue(alert_scopes(findings(self.db, self.cfg, near))["content"])

    def test_legacy_false_buffer_alarm_is_retired_without_recovery_spam(self):
        with (
            patch("cyberquiz.health.config", return_value=self.cfg),
            patch("cyberquiz.health.findings") as issues,
            patch(
                "cyberquiz.telegram.notify", side_effect=self.delivered_notice
            ) as notify,
        ):
            issues.return_value = [
                {
                    "kind": "queue_empty",
                    "failure": {"status": "complete", "error": None},
                }
            ]
            check(self.db)
            self.db.execute(
                "UPDATE health_outages SET since='2020-01-01T00:00:00+00:00'"
            )
            check(self.db)
            self.assertEqual(notify.call_count, 1)
            event = self.db.execute("SELECT event FROM health_outages").fetchone()[0]
            self.db.execute(
                "INSERT INTO notice_texts(event,facts,created,state) VALUES(?,?,?,'delivered')",
                (event, "{}", "2020-01-01T00:00:00+00:00"),
            )
            issues.return_value = [{"kind": "queue_empty", "actionable": False}]
            check(self.db)
            self.assertEqual(notify.call_count, 1)
            self.assertEqual(
                self.db.execute("SELECT count(*) FROM health_outages").fetchone()[0], 0
            )
            self.assertEqual(
                self.db.execute(
                    "SELECT state FROM notice_texts WHERE event=?", (event,)
                ).fetchone()[0],
                "superseded",
            )

    def test_caught_up_posts_clear_missed_slot_and_spacing_is_not_an_outage(self):
        from cyberquiz.store import new_job

        job = new_job(self.db, "catchup")
        self.db.execute(
            "UPDATE jobs SET status='published',published_at=? WHERE id=?",
            (
                "2026-11-04T16:00:00+00:00",
                job,
            ),
        )
        self.db.commit()
        clock = dt.datetime(2026, 11, 4, 21, 0, tzinfo=dt.timezone.utc)
        issues = findings(self.db, self.cfg, clock)
        self.assertNotIn("missed_post", [i["kind"] for i in issues])

    def test_repeated_health_state_does_not_spam_and_recovery_is_not_post(self):
        with (
            patch("cyberquiz.health.config", return_value=self.cfg),
            patch(
                "cyberquiz.health.findings",
                return_value=[
                    {
                        "kind": "service_down",
                        "service": "cyberquiz-worker",
                        "state": "failed",
                    }
                ],
            ),
            patch(
                "cyberquiz.telegram.notify", side_effect=self.delivered_notice
            ) as notify,
        ):
            check(self.db)
            check(self.db)
            self.assertEqual(notify.call_count, 1)
        with (
            patch("cyberquiz.health.config", return_value=self.cfg),
            patch("cyberquiz.health.findings", return_value=[]),
            patch("cyberquiz.telegram.notify") as notify,
        ):
            check(self.db, services={"cyberquiz-worker": "active"})
            facts = json.loads(notify.call_args.args[2])
            self.assertEqual(facts["event"], "workflow_recovered")
            self.assertEqual(facts["scope"], "publishing")

    def test_worker_failure_is_visible_even_when_pipeline_paused(self):
        self.cfg["emergency_pause"] = True
        issues = findings(self.db, self.cfg, services={"cyberquiz-worker": "failed"})
        self.assertEqual(issues[0]["kind"], "service_down")

    def test_ai_notice_failure_remains_retryable_after_three_attempts(self):
        from cyberquiz.telegram import notify, retry_notifications

        with patch(
            "cyberquiz.agent.event_reply", side_effect=RuntimeError("Unavailable")
        ) as ai:
            for attempt in range(4):
                if attempt:
                    self.db.execute("UPDATE notice_texts SET next_attempt=NULL")
                    self.db.commit()
                if attempt == 0:
                    notify(self.db, "test-health", json.dumps({"event": "blocked"}))
                else:
                    retry_notifications(self.db)
            self.assertEqual(ai.call_count, 4)
            row = self.db.execute(
                "SELECT attempts,text,next_attempt FROM notice_texts"
            ).fetchone()
            self.assertEqual(row["attempts"], 4)
            self.assertIsNone(row["text"])
            self.assertIsNotNone(row["next_attempt"])

    def test_continuation_uses_only_known_containers_and_honors_pause(self):
        from unittest.mock import MagicMock
        from cyberquiz.__main__ import continue_publication

        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [{"id": "known"}]
        with patch("cyberquiz.instagram.publish") as publish:
            continue_publication(db, self.cfg)
            publish.assert_called_once_with(db, "known")
            self.assertIn("status='container_created'", db.execute.call_args.args[0])
            publish.reset_mock()
            continue_publication(db, dict(self.cfg, emergency_pause=True))
            publish.assert_not_called()

    def test_changing_failure_details_does_not_repeat_outage_alert(self):
        self.cfg["publishing_enabled"] = False
        with (
            patch("cyberquiz.health.config", return_value=self.cfg),
            patch("cyberquiz.health.findings") as issues,
            patch(
                "cyberquiz.telegram.notify", side_effect=self.delivered_notice
            ) as notify,
        ):
            issues.return_value = [{"kind": "queue_empty", "failure": "first"}]
            check(self.db)
            self.assertEqual(notify.call_count, 0)
            self.db.execute(
                "UPDATE health_outages SET since='2020-01-01T00:00:00+00:00'"
            )
            self.db.commit()
            issues.return_value = [{"kind": "queue_empty", "failure": "second"}]
            check(self.db)
            check(self.db)
            self.assertEqual(notify.call_count, 1)

    def test_missed_slot_is_separate_from_current_outage_and_recovery(self):
        missed = {"kind": "missed_post", "slot": "2026-10-30T12:35:00+00:00"}
        with (
            patch("cyberquiz.health.config", return_value=self.cfg),
            patch("cyberquiz.health.findings") as issues,
            patch(
                "cyberquiz.telegram.notify", side_effect=self.delivered_notice
            ) as notify,
        ):
            issues.return_value = [missed, {"kind": "queue_empty"}]
            check(self.db)
            issues.return_value = [missed]
            check(self.db)
            issues.return_value = []
            check(self.db)
            events = [
                json.loads(call.args[2])["event"] for call in notify.call_args_list
            ]
            self.assertEqual(
                events,
                ["workflow_delayed", "workflow_recovered"],
            )

    def test_worker_tick_cannot_clear_monitor_service_failure(self):
        with (
            patch("cyberquiz.health.config", return_value=self.cfg),
            patch("cyberquiz.health.findings") as issues,
            patch(
                "cyberquiz.telegram.notify", side_effect=self.delivered_notice
            ) as notify,
        ):
            issues.return_value = [
                {
                    "kind": "service_down",
                    "service": "cyberquiz-worker",
                    "state": "failed",
                }
            ]
            check(self.db, services={"worker": "failed"})
            issues.return_value = []
            check(self.db)
            self.assertEqual(notify.call_count, 1)
            check(self.db, services={"worker": "active"})
            self.assertEqual(notify.call_count, 2)
