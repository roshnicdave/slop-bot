import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cyberquiz.store import connect, now
from cyberquiz.telegram import tables


class ChatRecoveryTests(unittest.TestCase):
    def test_failed_inference_is_durable_and_retry_uses_new_attempt(self):
        from cyberquiz.conversation import process

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite"
            db = connect(path)
            tables(db)
            db.execute(
                "INSERT INTO telegram_updates VALUES(?,?,?,?,?,?)",
                (1, 7, "Please send the plan first", "chat_running", None, now()),
            )
            db.commit()
            db.close()
            with (
                patch(
                    "cyberquiz.conversation.connect", side_effect=lambda: connect(path)
                ),
                patch(
                    "cyberquiz.conversation.config",
                    return_value={"telegram_allowed_user_ids": [7]},
                ),
                patch(
                    "cyberquiz.agent.run",
                    side_effect=RuntimeError("Cloudflare request outcome unknown"),
                ),
                patch("cyberquiz.conversation.send") as send,
            ):
                process(1)
                send.assert_not_called()
            db = connect(path)
            self.assertEqual(
                db.execute("SELECT status FROM telegram_updates").fetchone()[0],
                "chat_retry",
            )
            self.assertEqual(
                db.execute("SELECT attempts FROM chat_recovery").fetchone()[0], 1
            )
            db.close()
            with (
                patch(
                    "cyberquiz.conversation.connect", side_effect=lambda: connect(path)
                ),
                patch(
                    "cyberquiz.conversation.config",
                    return_value={"telegram_allowed_user_ids": [7]},
                ),
                patch(
                    "cyberquiz.agent.run", return_value="Which incident do you mean?"
                ) as agent,
                patch("cyberquiz.conversation.send") as send,
            ):
                process(1)
                self.assertEqual(agent.call_args.kwargs["attempt"], 1)
                send.assert_called_once_with(7, "Which incident do you mean?")

    def test_event_cannot_invent_url_or_use_unrelated_live_state(self):
        from cyberquiz.agent import event_reply

        with patch(
            "cyberquiz.agent.cloudflare.agent_turn",
            return_value={"content": "Posted: https://example.com/fake"},
        ) as model:
            with self.assertRaises(ValueError):
                event_reply(None, "event", {"event": "queue_empty"})
            payload = json.loads(model.call_args.args[2][1]["content"])
            self.assertNotIn("current_state", payload)

    def test_confirmed_event_url_is_allowed(self):
        from cyberquiz.agent import event_reply

        url = "https://www.instagram.com/reel/real/"
        with patch(
            "cyberquiz.agent.cloudflare.agent_turn",
            return_value={"content": "Posted: " + url},
        ):
            self.assertIn(url, event_reply(None, "event", {"permalink": url}))
