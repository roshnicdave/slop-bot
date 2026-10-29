import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cyberquiz.store import connect, new_job
from cyberquiz.novelty import check, recent
from cyberquiz.schedule import deadline


class NoveltyTests(unittest.TestCase):
    def test_fifty_published_objectives_and_all_history_exact_claims(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            for n in range(52):
                p = {
                    "family": "topic-" + chr(65 + n),
                    "topic": "lesson " + chr(65 + n),
                    "core_claim": "claim " + chr(65 + n),
                    "question": "Question " + chr(65 + n),
                }
                j = new_job(db, "test")
                db.execute(
                    'UPDATE jobs SET plan=?,status="published",published_at=? WHERE id=?',
                    (json.dumps(p), f"2026-10-{n + 1:02}T09:00:00+00:00", j),
                )
            db.commit()
            with patch(
                "cyberquiz.novelty.config", return_value={"novelty_cooldown_reels": 50}
            ):
                self.assertEqual(len(recent(db)), 50)
                with self.assertRaises(ValueError):
                    check(
                        db,
                        {
                            "family": "different wording",
                            "topic": "new label",
                            "core_claim": "claim A",
                            "question": "Reworded",
                        },
                    )
                with self.assertRaises(ValueError):
                    check(
                        db,
                        {
                            "family": "x",
                            "topic": "lesson Z",
                            "core_claim": "unrelated claim content",
                            "question": "Changed numbers",
                        },
                    )
                check(
                    db,
                    {
                        "family": "fresh",
                        "topic": "certificate wildcard depth",
                        "core_claim": "a wildcard covers a single hostname label",
                        "question": "Which certificate matches?",
                    },
                )
            db.close()

    def test_rejected_drafts_do_not_consume_fifty_reel_window(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            j = new_job(db, "test")
            p = {"family": "dns", "question": "Q", "answer": "A", "explanation": "E"}
            db.execute(
                'UPDATE jobs SET plan=?,status="rejected" WHERE id=?',
                (json.dumps(p), j),
            )
            db.commit()
            with patch("cyberquiz.novelty.config", return_value={}):
                self.assertEqual(recent(db), [])
            db.close()


class ScheduleTests(unittest.TestCase):
    def test_sleeps_to_deadline_and_maintenance_is_not_minute_polling(self):
        cfg = {
            "timezone": "America/Los_Angeles",
            "slots": ["09:00"],
            "posts_per_day": 1,
            "generation_enabled": True,
        }
        before = dt.datetime(2026, 10, 29, 15, 50, tzinfo=dt.timezone.utc)
        self.assertEqual((deadline(cfg, before) - before).total_seconds(), 600)
        after = dt.datetime(2026, 10, 29, 17, 0, tzinfo=dt.timezone.utc)
        self.assertEqual((deadline(cfg, after) - after).total_seconds(), 21600)

    def test_dst_uses_absolute_wait(self):
        cfg = {
            "timezone": "America/Los_Angeles",
            "slots": ["03:00"],
            "posts_per_day": 1,
            "generation_enabled": True,
        }
        before = dt.datetime(2026, 3, 8, 9, 30, tzinfo=dt.timezone.utc)
        self.assertEqual((deadline(cfg, before) - before).total_seconds(), 1800)
