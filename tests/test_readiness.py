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
        ):
            notify(self.db, "published:job", "Posted: link")
            notify(self.db, "published:job", "Posted: link")
            self.assertEqual(send.call_count, 2)
            self.assertEqual({c.args[0] for c in send.call_args_list}, {1, 2})
            send.reset_mock()
            notify(self.db, "quality:job", "Held")
            send.assert_called_once_with(1, "Held")
