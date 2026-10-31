import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cyberquiz.store import connect
from cyberquiz.health import findings, check


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

    def test_repeated_health_state_does_not_spam_and_recovery_is_not_post(self):
        with (
            patch("cyberquiz.health.config", return_value=self.cfg),
            patch("cyberquiz.health.findings", return_value=[{"kind": "queue_empty"}]),
            patch("cyberquiz.telegram.notify") as notify,
        ):
            check(self.db)
            check(self.db)
            self.assertEqual(notify.call_count, 1)
        with (
            patch("cyberquiz.health.config", return_value=self.cfg),
            patch("cyberquiz.health.findings", return_value=[]),
            patch("cyberquiz.telegram.notify") as notify,
        ):
            check(self.db)
            facts = json.loads(notify.call_args.args[2])
            self.assertEqual(facts["event"], "pipeline_recovered")

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
