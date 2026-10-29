import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cyberquiz.store import connect, new_job
from cyberquiz.context import snapshot, read
from cyberquiz.chat import tables, preference, remember, propose
from cyberquiz.telegram import tables as telegram_tables


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = connect(Path(self.temp.name) / "db")
        self.addCleanup(self.db.close)
        telegram_tables(self.db)
        tables(self.db)

    def test_live_queue_includes_ready_older_than_last_eight_jobs(self):
        ready = new_job(self.db, "ready")
        self.db.execute(
            "UPDATE jobs SET approved=1,status='rendered' WHERE id=?", (ready,)
        )
        self.db.commit()
        for _ in range(12):
            new_job(self.db, "draft")
        snap = snapshot(self.db)
        self.assertEqual(snap["queue"]["ready"][0]["id"], ready)
        self.assertEqual(snap["queue"]["ready_count"], 1)
        self.assertEqual(snap["readiness_policy"]["target_ready"], 1)

    def test_model_can_retrieve_saved_advice_then_explain_without_resaving(self):
        preference(self.db, 1, "Mention relevant certifications in some reels.")
        remember(
            self.db,
            1,
            1,
            "suggestion: mention certifications",
            "Saved for future videos.",
            "idea",
            100,
        )
        with patch(
            "cyberquiz.chat.cloudflare.llm",
            side_effect=[
                {"action": "inspect", "resource": "preferences"},
                {
                    "action": "answer",
                    "reply": "Saved in SQLite; research and script drafting read it.",
                },
            ],
        ) as llm:
            result = propose(self.db, "op", "how did you save the advice?", {}, 1)
            self.assertEqual(result["action"], "answer")
            messages = llm.call_args_list[1].args[2]
            evidence = json.loads(messages[-1]["content"])
            self.assertEqual(
                evidence["data"]["saved"][0]["text"],
                "Mention relevant certifications in some reels.",
            )
            self.assertEqual(
                self.db.execute("SELECT COUNT(*) FROM preferences").fetchone()[0], 1
            )

    def test_missing_resource_is_not_treated_as_empty_and_unknown_reads_cannot_execute(
        self,
    ):
        self.assertEqual(read(self.db, "experiments"), [])
        with self.assertRaises(ValueError):
            read(self.db, "credentials")
        with patch(
            "cyberquiz.chat.cloudflare.llm",
            return_value={"action": "inspect", "resource": "credentials"},
        ):
            result = propose(self.db, "x", "show me everything", {}, 1)
            self.assertEqual(result["action"], "answer")
