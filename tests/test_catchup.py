import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cyberquiz.schedule import deadline, next_post_at
from cyberquiz.store import connect, new_job
from cyberquiz.__main__ import publish_due


class CatchupTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "publishing_enabled": True,
            "generation_enabled": True,
            "timezone": "America/Los_Angeles",
            "slots": ["12:35", "19:19"],
            "posts_per_day": 2,
        }
        self.clock = dt.datetime(2026, 11, 4, 22, 30, tzinfo=dt.timezone.utc)

    def test_missed_window_remains_due_without_tight_idle_polling(self):
        self.assertEqual(next_post_at(self.cfg, [], self.clock), self.clock)
        self.assertEqual(
            (deadline(self.cfg, self.clock, ready=True) - self.clock).total_seconds(), 1
        )
        self.assertEqual(
            (deadline(self.cfg, self.clock) - self.clock).total_seconds(), 1800
        )

    def test_catchup_preserves_second_post_and_wakes_at_spacing_deadline(self):
        clock = self.clock.replace(day=5, hour=3, minute=19)  # 19:19 Pacific
        due = self.clock + dt.timedelta(hours=6)
        self.assertEqual(next_post_at(self.cfg, [self.clock], clock), due)
        self.assertEqual(
            deadline(self.cfg, clock, published=[self.clock], ready=True), due
        )

    def test_daily_limit_and_old_days_do_not_create_a_burst(self):
        two = [self.clock - dt.timedelta(hours=7), self.clock]
        self.assertEqual(
            next_post_at(self.cfg, two, self.clock),
            self.clock.replace(day=5, hour=20, minute=35),
        )
        yesterday = [self.clock - dt.timedelta(days=1)]
        self.assertLessEqual(next_post_at(self.cfg, yesterday, self.clock), self.clock)
        self.assertIsNone(
            next_post_at(dict(self.cfg, emergency_pause=True), [], self.clock)
        )

    def test_repeated_ticks_publish_one_ready_reel_and_respect_uncertainty(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            self.addCleanup(db.close)
            job = new_job(db, "ready")
            db.execute(
                "UPDATE jobs SET status='rendered',approved=1 WHERE id=?", (job,)
            )
            db.commit()

            def publish(db, job):
                db.execute(
                    "UPDATE jobs SET status='published',published_at=? WHERE id=?",
                    (self.clock.isoformat(), job),
                )
                db.commit()

            with patch("cyberquiz.instagram.publish", side_effect=publish) as submit:
                self.assertTrue(publish_due(db, self.cfg, self.clock))
                self.assertFalse(publish_due(db, self.cfg, self.clock))
                submit.assert_called_once()
                unknown = new_job(db, "unknown")
                db.execute(
                    "UPDATE jobs SET status='publish_unknown' WHERE id=?", (unknown,)
                )
                next_job = new_job(db, "next")
                db.execute(
                    "UPDATE jobs SET status='rendered',approved=1 WHERE id=?",
                    (next_job,),
                )
                db.commit()
                later = self.clock + dt.timedelta(hours=7)
                self.assertFalse(publish_due(db, self.cfg, later))
                submit.assert_called_once()

    def test_recovery_before_next_slot_does_not_publish_twice(self):
        later = self.clock + dt.timedelta(hours=1)
        self.assertGreater(next_post_at(self.cfg, [self.clock], later), later)
