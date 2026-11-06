import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cyberquiz.store import connect, new_job, now
from cyberquiz.telegram import tables, notify, retry_notifications
from cyberquiz.health import check
from cyberquiz.notice_policy import prepare, current_facts


class NoticeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = connect(Path(self.temp.name) / "db")
        self.addCleanup(self.db.close)
        tables(self.db)
        self.db.executemany("INSERT INTO telegram_chats VALUES(?,?)", [(1, 1), (2, 2)])
        self.db.commit()
        self.cfg = {
            "telegram_owner_user_id": 1,
            "generation_enabled": True,
            "publishing_enabled": True,
            "timezone": "UTC",
            "slots": ["23:59"],
            "posts_per_day": 1,
        }
        for path in (
            "cyberquiz.telegram.config",
            "cyberquiz.notice_policy.config",
            "cyberquiz.health.config",
        ):
            patcher = patch(path, return_value=self.cfg)
            patcher.start()
            self.addCleanup(patcher.stop)

    def published(self, age=0):
        job = new_job(self.db, "test")
        stamp = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=age)).isoformat()
        self.db.execute(
            "UPDATE jobs SET status='published',published_at=? WHERE id=?", (stamp, job)
        )
        self.db.commit()
        return job

    def test_legacy_alert_backlog_and_old_publications_never_reach_ai_or_telegram(self):
        prepare(self.db)
        old = self.published(age=3)
        fresh = self.published()
        for event in (
            "health:2026-11-01T00:00:00+00:00",
            "missed-post:2026-11-01T12:35:00+00:00",
            "published:" + old,
        ):
            self.db.execute(
                "INSERT INTO notice_texts(event,facts) VALUES(?,?)", (event, "{}")
            )
        self.db.commit()
        with (
            patch("cyberquiz.agent.event_reply") as ai,
            patch("cyberquiz.telegram.send") as send,
        ):
            retry_notifications(self.db)
            ai.assert_not_called()
            send.assert_not_called()
        self.assertEqual(
            self.db.execute(
                "SELECT count(*) FROM notice_texts WHERE state='pending'"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.db.execute(
                "SELECT count(*) FROM jobs WHERE status='published'"
            ).fetchone()[0],
            2,
        )
        self.assertNotEqual(old, fresh)
        from cyberquiz.context import read

        activity = read(self.db, "activity")
        self.assertTrue(activity["notifications"])
        self.assertTrue(
            all(n["state"] == "superseded" for n in activity["notifications"])
        )

    def test_delayed_health_notice_uses_fresh_local_publication_facts(self):
        self.cfg["timezone"] = "America/Los_Angeles"
        self.cfg["slots"] = ["12:35", "19:19"]
        self.cfg["posts_per_day"] = 2
        prepare(self.db)
        self.db.execute(
            "CREATE TABLE health_outages(scope TEXT PRIMARY KEY,since TEXT,event TEXT,facts TEXT)"
        )
        for stamp in ("2026-11-05T21:30:00+00:00", "2026-11-06T03:30:00+00:00"):
            job = new_job(self.db, stamp)
            self.db.execute(
                "UPDATE jobs SET status='published',published_at=? WHERE id=?",
                (stamp, job),
            )
        old = {
            "event": "buffer_needs_attention",
            "scope": "content",
            "confirmed_posts_today": 0,
        }
        self.db.execute(
            "INSERT INTO health_outages VALUES('content',?,?,?)",
            ("2026-11-06T03:30:00+00:00", "health:content:test", json.dumps(old)),
        )
        row = {
            "event": "health:content:test",
            "facts": json.dumps(old),
            "created": "2026-11-06T03:30:00+00:00",
        }
        with patch(
            "cyberquiz.notice_policy.now", return_value="2026-11-06T04:00:00+00:00"
        ):
            payload = json.loads(current_facts(self.db, row))
        self.assertEqual(payload["confirmed_posts_today"], 2)
        self.assertEqual(payload["local_date"], "2026-11-05")
        self.assertEqual(payload["occurred_at"], "2026-11-05T19:30:00-08:00")
        self.assertEqual(payload["next_post_at"], "2026-11-06T12:35:00-08:00")

    def test_unsent_failure_that_recovers_has_no_failure_or_recovery_message(self):
        self.cfg["publishing_enabled"] = False
        # A confirmed publication also proves an empty refill is not "no post".
        self.published()
        with (
            patch("cyberquiz.health.findings") as issues,
            patch(
                "cyberquiz.agent.event_reply", side_effect=RuntimeError("AI offline")
            ) as ai,
            patch("cyberquiz.telegram.send") as send,
        ):
            issues.return_value = [{"kind": "queue_empty"}]
            check(self.db)
            self.db.execute(
                "UPDATE health_outages SET since='2020-01-01T00:00:00+00:00'"
            )
            self.db.commit()
            check(self.db)
            self.assertEqual(ai.call_count, 1)
            issues.return_value = []
            check(self.db)
            retry_notifications(self.db)
            self.assertEqual(ai.call_count, 1)
            send.assert_not_called()
        self.assertEqual(
            self.db.execute("SELECT state FROM notice_texts").fetchone()[0],
            "superseded",
        )

    def test_transient_queue_and_chat_errors_do_not_create_all_clear_pairs(self):
        self.cfg["publishing_enabled"] = False
        with (
            patch("cyberquiz.health.findings") as issues,
            patch("cyberquiz.telegram.notify") as alert,
        ):
            for current in (
                [{"kind": "queue_empty"}],
                [],
                [
                    {
                        "kind": "open_incident",
                        "component": "conversation",
                        "phase": "reply",
                        "message": "502",
                    }
                ],
                [],
            ):
                issues.return_value = current
                check(self.db)
            alert.assert_not_called()

    def test_chat_alert_is_scoped_and_includes_real_publication_count(self):
        self.published()
        with (
            patch("cyberquiz.health.findings") as issues,
            patch(
                "cyberquiz.agent.event_reply", side_effect=lambda db, op, facts: facts
            ),
            patch("cyberquiz.telegram.send") as send,
        ):
            issues.return_value = [
                {
                    "kind": "open_incident",
                    "component": "conversation",
                    "phase": "reply",
                    "message": "502",
                }
            ]
            check(self.db)
            self.db.execute(
                "UPDATE health_outages SET since='2020-01-01T00:00:00+00:00'"
            )
            self.db.commit()
            check(self.db)
            check(self.db)
            self.assertEqual(send.call_count, 1)
            payload = json.loads(send.call_args.args[1])
            self.assertEqual(payload["scope"], "chat")
            self.assertEqual(payload["confirmed_posts_today"], 1)
            self.assertEqual(send.call_args.args[0], 1)
            issues.return_value = []
            check(self.db)
            self.assertEqual(send.call_count, 2)
            self.assertEqual(
                json.loads(send.call_args.args[1])["event"], "workflow_recovered"
            )

    def test_state_rechecked_if_recovery_happens_during_ai_composition(self):
        def compose(db, op, facts):
            db.execute("DELETE FROM health_outages")
            db.commit()
            return "A stale failure report"

        with (
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
            patch("cyberquiz.agent.event_reply", side_effect=compose),
            patch("cyberquiz.telegram.send") as send,
        ):
            check(self.db)
            send.assert_not_called()

    def test_cached_publication_after_partial_delivery_only_sends_missing_recipient(
        self,
    ):
        job = self.published()
        prepare(self.db)
        event = "published:" + job
        self.db.execute(
            "INSERT INTO notice_texts(event,facts,text,created,state) VALUES(?,?,?,?,'pending')",
            (event, "{}", "A confirmed post", now()),
        )
        self.db.execute("INSERT INTO notices VALUES(?,1,'sent')", (event,))
        self.db.commit()
        with (
            patch("cyberquiz.agent.event_reply") as ai,
            patch("cyberquiz.telegram.send") as send,
        ):
            retry_notifications(self.db)
            retry_notifications(self.db)
            ai.assert_not_called()
            send.assert_called_once_with(2, "A confirmed post")

    def test_uncertain_telegram_send_is_not_replayed(self):
        job = self.published()
        with (
            patch("cyberquiz.agent.event_reply", return_value="A confirmed post"),
            patch(
                "cyberquiz.telegram.send", side_effect=RuntimeError("unknown")
            ) as send,
        ):
            notify(self.db, "published:" + job, "{}")
            retry_notifications(self.db)
            self.assertEqual(send.call_count, 2)
            self.assertEqual(
                self.db.execute(
                    "SELECT count(*) FROM notices WHERE status='uncertain'"
                ).fetchone()[0],
                2,
            )

    def test_ongoing_outage_remains_deliverable_after_quota_reset(self):
        with (
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
                "cyberquiz.agent.event_reply", side_effect=RuntimeError("AI offline")
            ) as ai,
            patch("cyberquiz.telegram.send") as send,
        ):
            check(self.db)
            self.db.execute(
                "UPDATE notice_texts SET created='2020-01-01T00:00:00+00:00',next_attempt=NULL"
            )
            self.db.commit()
            retry_notifications(self.db)
            self.assertEqual(ai.call_count, 2)
            self.assertEqual(
                self.db.execute("SELECT state FROM notice_texts").fetchone()[0],
                "pending",
            )
            send.assert_not_called()
