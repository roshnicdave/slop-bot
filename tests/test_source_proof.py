import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cyberquiz.discovery import validate
from cyberquiz.timing_plan import plan
from cyberquiz.store import connect


class SourceProofTests(unittest.TestCase):
    def test_review_flag_alone_is_not_a_validated_source_and_mutations_fail(self):
        p = {
            "key": "source-test",
            "family": "source-grounded",
            "topic": "request cache isolation",
            "core_claim": "request-specific cached data must stay isolated",
            "question": "What crossed\nthe request boundary?",
            "clue": "",
            "diagram": {
                "kind": "flow",
                "links_up": True,
                "nodes": [
                    {"id": "a", "kind": "server", "label": "Request A"},
                    {"id": "b", "kind": "cache", "label": "Shared cache"},
                ],
                "edges": [{"from": "a", "to": "b", "label": "cached data"}],
            },
            "answer": "cached data",
            "distractors": ["link lights", "DHCP lease", "a cable"],
            "explanation": "The source describes cached data crossing requests.",
            "fix": "Isolate request-specific cache data.",
            "fix_diagram": {},
            "source_url": "https://blog.cloudflare.com/test",
            "source_label": "Primary article",
            "narration_question": "What crossed the request boundary?",
            "narration_answer": "Cached data.",
            "provenance": {
                "quote": "cached data crossing requests",
                "excerpt": "The disclosure described cached data crossing requests in its investigation.",
                "review": {"pass": True, "issues": []},
            },
        }
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data" / "discovery").mkdir(parents=True)
            with patch("cyberquiz.discovery.ROOT", root):
                with self.assertRaises(ValueError):
                    validate(p)
                (root / "data" / "discovery" / "source-test.json").write_text(
                    json.dumps(p)
                )
                validate(p)
                p["diagram"]["edges"][0]["label"] = "invented traffic"
                with self.assertRaises(ValueError):
                    validate(p)

    def test_posting_experiment_is_stable_and_spaced_without_claiming_proven_times(
        self,
    ):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            cfg = {"timezone": "America/Los_Angeles", "slots": ["11:23", "19:41"]}
            for day in ["2026-10-29", "2026-10-30", "2026-10-31"]:
                with patch(
                    "cyberquiz.timing_plan.cloudflare.llm",
                    return_value={
                        "slots": ["11:23", "19:41"],
                        "hypothesis": "unproven exploration",
                    },
                ):
                    p = plan(db, cfg, day)
                    self.assertEqual(p, plan(db, cfg, day))
                a, b = [int(t[:2]) * 60 + int(t[3:]) for t in p["slots"]]
                self.assertGreaterEqual(b - a, 360)
                self.assertIn("unproven", p["basis"])
            db.close()
