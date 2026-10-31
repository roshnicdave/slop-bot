import contextlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cyberquiz.store import connect, new_job
from cyberquiz.readiness import ensure
from cyberquiz.telegram import tables, notify


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = connect(Path(self.temp.name) / "db")
        self.addCleanup(self.db.close)
        self.cfg = {"generation_enabled": True, "posts_per_day": 2, "timezone": "UTC"}

    def test_fill_one_then_refill_after_consumption_without_stockpiling(self):
        def make(db, slot):
            ident = new_job(db, "test", slot)
            db.execute(
                "UPDATE jobs SET status='rendered',approved=1 WHERE id=?", (ident,)
            )
            db.commit()
            return ident

        with (
            patch("cyberquiz.readiness.config", return_value=self.cfg),
            patch(
                "cyberquiz.readiness.worker_lock", side_effect=contextlib.nullcontext
            ),
            patch("cyberquiz.production.make", side_effect=make) as generate,
        ):
            first = ensure(self.db)
            self.assertEqual(ensure(self.db), "ready")
            generate.assert_called_once()
            self.db.execute("UPDATE jobs SET status='published' WHERE id=?", (first,))
            self.db.commit()
            self.assertNotEqual(ensure(self.db), first)
            self.assertEqual(generate.call_count, 2)
            self.assertEqual(ensure(self.db), "ready")
            self.assertEqual(generate.call_count, 2)

    def test_failure_backoff_and_pause_do_not_spend_again(self):
        with (
            patch("cyberquiz.readiness.config", return_value=self.cfg),
            patch(
                "cyberquiz.readiness.worker_lock", side_effect=contextlib.nullcontext
            ),
            patch(
                "cyberquiz.production.make", side_effect=ValueError("held")
            ) as generate,
        ):
            self.assertEqual(ensure(self.db), "held")
            self.assertEqual(ensure(self.db), "backoff")
            generate.assert_called_once()
            self.cfg["generation_enabled"] = False
            self.assertEqual(ensure(self.db), "paused")

    def test_post_notifications_reach_both_once_other_alerts_owner_only(self):
        tables(self.db)
        self.db.executemany("INSERT INTO telegram_chats VALUES(?,?)", [(1, 1), (2, 2)])
        self.db.commit()
        with (
            patch(
                "cyberquiz.telegram.config", return_value={"telegram_owner_user_id": 1}
            ),
            patch("cyberquiz.telegram.send") as send,
            patch(
                "cyberquiz.agent.event_reply", side_effect=lambda db, op, facts: facts
            ),
        ):
            notify(self.db, "published:job", "Posted: link")
            notify(self.db, "published:job", "Posted: link")
            self.assertEqual(send.call_count, 2)
            self.assertEqual({c.args[0] for c in send.call_args_list}, {1, 2})
            send.reset_mock()
            notify(self.db, "quality:job", "Held")
            send.assert_called_once_with(1, "Held")

    def test_legacy_preflight_failures_do_not_exhaust_real_generation_budget(self):
        from cyberquiz.store import now

        self.db.execute(
            "CREATE TABLE readiness_attempts(id INTEGER PRIMARY KEY,created TEXT,status TEXT,job TEXT)"
        )
        self.db.executemany(
            "INSERT INTO readiness_attempts(created,status) VALUES(?,?)",
            [(now(), "failed:ValueError")] * 3,
        )
        self.db.commit()

        def make(db, slot):
            ident = new_job(db, "test", slot)
            db.execute(
                "UPDATE jobs SET status='rendered',approved=1 WHERE id=?", (ident,)
            )
            db.commit()
            return ident

        with (
            patch("cyberquiz.readiness.config", return_value=self.cfg),
            patch(
                "cyberquiz.readiness.worker_lock", side_effect=contextlib.nullcontext
            ),
            patch("cyberquiz.production.make", side_effect=make) as generate,
        ):
            import datetime as dt

            fixed = dt.datetime(2026, 10, 30, 12, tzinfo=dt.timezone.utc)
            self.db.execute(
                "UPDATE readiness_attempts SET created=?",
                ((fixed - dt.timedelta(hours=2)).isoformat(),),
            )
            self.db.commit()
            with patch("cyberquiz.readiness.dt.datetime", wraps=dt.datetime) as clock:
                clock.now.return_value = fixed
                job = ensure(self.db)
            self.assertEqual(
                self.db.execute(
                    "SELECT status FROM jobs WHERE id=?", (job,)
                ).fetchone()[0],
                "rendered",
            )
            generate.assert_called_once()

    def test_real_failed_jobs_still_exhaust_daily_generation_allowance(self):
        from cyberquiz.store import now

        self.db.execute(
            "CREATE TABLE readiness_attempts(id INTEGER PRIMARY KEY,created TEXT,status TEXT,job TEXT)"
        )
        for i in range(1, 4):
            self.db.execute(
                "INSERT INTO readiness_attempts VALUES(?,?,?,NULL)",
                (i, now(), "failed:ValueError"),
            )
            job = new_job(self.db, "test", "buffer:" + str(i))
            self.db.execute("UPDATE jobs SET status='failed' WHERE id=?", (job,))
        self.db.commit()
        with (
            patch("cyberquiz.readiness.config", return_value=self.cfg),
            patch(
                "cyberquiz.readiness.worker_lock", side_effect=contextlib.nullcontext
            ),
            patch("cyberquiz.production.make") as generate,
        ):
            # Avoid backoff masking the independent daily-spend cap.
            self.db.execute("UPDATE readiness_attempts SET status='complete'")
            self.db.commit()
            self.assertEqual(ensure(self.db), "daily_limit")
            generate.assert_not_called()

    def test_held_quality_result_is_not_reported_as_ready(self):
        def make(db, slot):
            job = new_job(db, "test", slot)
            db.execute("UPDATE jobs SET status='held_quality' WHERE id=?", (job,))
            db.commit()
            return job

        with (
            patch("cyberquiz.readiness.config", return_value=self.cfg),
            patch(
                "cyberquiz.readiness.worker_lock", side_effect=contextlib.nullcontext
            ),
            patch("cyberquiz.production.make", side_effect=make),
        ):
            self.assertEqual(ensure(self.db), "held")
        self.assertEqual(
            self.db.execute("SELECT status FROM readiness_attempts").fetchone()[0],
            "held_quality",
        )
