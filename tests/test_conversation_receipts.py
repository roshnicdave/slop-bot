import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cyberquiz.store import connect
from cyberquiz.telegram import tables
from cyberquiz.agent import run
from cyberquiz.agent_tools import execute


class AgentLoopTests(unittest.TestCase):
    def test_native_tool_result_precedes_ai_reply_and_real_resume_executes(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            tables(db)
            cfg = {"telegram_allowed_user_ids": [1001], "publishing_enabled": False}
            calls = []

            def turn(db, op, messages, tools):
                calls.append(messages.copy())
                if len(calls) == 1:
                    self.assertEqual(messages[-1]["content"], "resume")
                    return {
                        "tool_calls": [
                            {
                                "name": "set_pipeline_running",
                                "arguments": {"enabled": True},
                            }
                        ]
                    }
                result = json.loads(messages[-1]["content"])
                self.assertEqual(messages[-1]["role"], "tool")
                self.assertTrue(result["result"]["actual_state"]["publishing_enabled"])
                return {"content": "Publishing is enabled now."}

            with (
                patch(
                    "cyberquiz.agent.snapshot",
                    return_value={"publishing_enabled": False},
                ),
                patch("cyberquiz.agent_tools.config", return_value=cfg),
                patch(
                    "cyberquiz.agent_tools.snapshot", side_effect=lambda db: cfg.copy()
                ),
                patch("cyberquiz.auth_health.check", return_value=True),
                patch("cyberquiz.telegram.update_config", side_effect=cfg.update),
            ):
                self.assertEqual(
                    run(db, 42, 1001, "resume", turn=turn), "Publishing is enabled now."
                )
            self.assertTrue(cfg["publishing_enabled"])
            self.assertEqual(len(calls), 2)
            self.assertEqual(
                db.execute("SELECT action,phase FROM action_receipts").fetchone()[:],
                ("set_pipeline_running", "completed"),
            )
            db.close()

    def test_queue_work_is_durable_and_deduplicated_without_sending_messages(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            tables(db)
            with (
                patch(
                    "cyberquiz.agent_tools.config",
                    return_value={"telegram_allowed_user_ids": [1001]},
                ),
                patch("cyberquiz.wakeup.signal"),
            ):
                first = execute(db, 42, 1001, "enqueue_work", {"task": "publish_next"})
                second = execute(db, 42, 1001, "enqueue_work", {"task": "publish_next"})
                self.assertEqual(first["request_id"], second["request_id"])
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM telegram_updates").fetchone()[0], 1
                )
            db.close()

    def test_plain_conversation_is_one_model_turn_without_command_router(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            tables(db)
            seen = []

            def turn(db, op, messages, tools):
                seen.append(messages[-1]["content"])
                return {"content": "The ready Reel covers subnet masks."}

            with patch("cyberquiz.agent.snapshot", return_value={"ready_count": 1}):
                result = run(db, 1, 1001, "what will be published?", turn=turn)
            self.assertEqual(seen, ["what will be published?"])
            self.assertEqual(result, "The ready Reel covers subnet masks.")
            db.close()
