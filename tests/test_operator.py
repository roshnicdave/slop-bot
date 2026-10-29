import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cyberquiz.store import connect, new_job
from cyberquiz.operator import publish_next
from cyberquiz.chat import propose


class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name) / "state.sqlite")
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.db.close)

    def test_natural_language_uses_model_without_phrase_gate(self):
        with patch(
            "cyberquiz.chat.cloudflare.llm", return_value={"action": "publish_next"}
        ) as llm:
            for text in (
                "can u post the next reel now",
                "just post it now and then queue another. i still want two posts tomorrow",
            ):
                self.assertEqual(
                    propose(self.db, text, text, {}, 1)["action"], "publish_next"
                )
            self.assertEqual(llm.call_count, 2)

    def test_delivery_is_bound_to_one_job_and_never_reposts(self):
        ident = new_job(self.db, "test")
        self.db.execute(
            "UPDATE jobs SET approved=1,status='rendered' WHERE id=?", (ident,)
        )
        self.db.commit()

        def publish(db, job, **kwargs):
            self.assertTrue(kwargs["immediate"])
            db.execute("UPDATE jobs SET status='published' WHERE id=?", (job,))
            db.commit()

        with (
            patch("cyberquiz.operator.worker_lock", side_effect=contextlib.nullcontext),
            patch(
                "cyberquiz.operator.config", return_value={"publishing_enabled": True}
            ),
            patch("cyberquiz.auth_health.check", return_value=True),
            patch("cyberquiz.instagram.publish", side_effect=publish) as call,
        ):
            self.assertEqual(publish_next(self.db, "request"), ident)
            self.assertEqual(publish_next(self.db, "request"), ident)
            call.assert_called_once()

    def test_pause_and_unknown_result_block_publication(self):
        with (
            patch("cyberquiz.operator.worker_lock", side_effect=contextlib.nullcontext),
            patch("cyberquiz.auth_health.check", return_value=True),
            patch("cyberquiz.instagram.publish") as call,
        ):
            with patch(
                "cyberquiz.operator.config", return_value={"publishing_enabled": False}
            ):
                with self.assertRaisesRegex(ValueError, "paused"):
                    publish_next(self.db, "a")
            ident = new_job(self.db, "test")
            self.db.execute(
                "UPDATE jobs SET status='publish_unknown' WHERE id=?", (ident,)
            )
            self.db.commit()
            with patch(
                "cyberquiz.operator.config", return_value={"publishing_enabled": True}
            ):
                with self.assertRaisesRegex(ValueError, "unknown"):
                    publish_next(self.db, "b")
            call.assert_not_called()

    def test_empty_queue_generates_once_under_stable_request_slot(self):
        def make(db, slot):
            ident = new_job(db, "generated", slot)
            db.execute(
                "UPDATE jobs SET approved=1,status='rendered' WHERE id=?", (ident,)
            )
            db.commit()
            return ident

        with (
            patch("cyberquiz.operator.worker_lock", side_effect=contextlib.nullcontext),
            patch(
                "cyberquiz.operator.config",
                return_value={"publishing_enabled": True, "generation_enabled": True},
            ),
            patch("cyberquiz.auth_health.check", return_value=True),
            patch("cyberquiz.production.make", side_effect=make) as generation,
            patch("cyberquiz.instagram.publish"),
        ):
            job = publish_next(self.db, "one")
            self.assertEqual(publish_next(self.db, "one"), job)
            generation.assert_called_once_with(self.db, slot="operator:one")

    def test_unsupported_model_action_is_rejected(self):
        with patch(
            "cyberquiz.chat.cloudflare.llm", return_value={"action": "run_shell"}
        ):
            with self.assertRaises(ValueError):
                propose(self.db, "x", "hello", {}, 1)

    def test_telegram_acknowledges_durable_work_without_publishing_in_chat_process(
        self,
    ):
        from cyberquiz.telegram import tables
        from cyberquiz.conversation import process

        tables(self.db)
        self.db.execute(
            "INSERT INTO telegram_updates VALUES(?,?,?,?,?,?)",
            (42, 1, "post the next reel now", "chat_running", None, "now"),
        )
        self.db.commit()
        db_path = Path(self.temp.name) / "state.sqlite"
        cfg = {
            "telegram_allowed_user_ids": [1],
            "timezone": "UTC",
            "slots": ["12:00"],
            "posts_per_day": 1,
            "monthly_budget_usd": 1.8,
        }
        with (
            patch(
                "cyberquiz.conversation.connect", side_effect=lambda: connect(db_path)
            ),
            patch("cyberquiz.conversation.config", return_value=cfg),
            patch("cyberquiz.conversation.status_text", return_value="ready"),
            patch("cyberquiz.conversation.send"),
            patch("cyberquiz.chat.propose", return_value={"action": "publish_next"}),
            patch("cyberquiz.wakeup.signal") as wake,
            patch("cyberquiz.instagram.publish") as publish,
        ):
            process(42)
            saved = self.db.execute(
                "SELECT command,status FROM telegram_updates WHERE id=42"
            ).fetchone()
            self.assertEqual(tuple(saved), ("/publish-next", "queued"))
            wake.assert_called_once()
            publish.assert_not_called()
