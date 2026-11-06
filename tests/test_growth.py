import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cyberquiz.store import connect, new_job
from cyberquiz.learning import analyze, growth
from cyberquiz.instagram import account_snapshot
from cyberquiz.captions import caption
from cyberquiz.research_context import project


class GrowthTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = connect(Path(folder.name) / "state.db")
        self.addCleanup(self.db.close)

    def test_early_success_informs_planning_without_becoming_a_proven_winner(self):
        job = new_job(self.db, "growth")
        plan = {
            "question": "Links are up.\nWhy does ping fail?",
            "format": "technical-diagram",
            "family": "visual-vlan",
            "quality": {"artifact": {"duration_seconds": 20}},
        }
        self.db.execute(
            "UPDATE jobs SET status='published',media_id='media',published_at=?,plan=? WHERE id=?",
            ("2026-11-06T03:30:00+00:00", json.dumps(plan), job),
        )
        payload = {
            k: {"data": [{"total_value": {"value": v}}]}
            for k, v in {
                "reach": 2000,
                "views": 2500,
                "shares": 7,
                "saved": 15,
                "ig_reels_avg_watch_time": 5500,
            }.items()
        }
        self.db.execute(
            "INSERT INTO metrics VALUES('media',?,10,?)",
            ("2026-11-06T13:30:00+00:00", json.dumps(payload)),
        )
        result = analyze(self.db)
        self.assertEqual(result["comparable_posts"], 0)
        self.assertIsNone(result["preferred_format"])
        post = result["growth"]["recent_posts"][0]
        self.assertEqual(post["average_watch_seconds"], 5.5)
        self.assertEqual(post["average_watch_fraction"], 0.275)
        self.assertEqual(post["shares_per_1000_reached"], 3.5)
        self.assertIsNone(post["follows_per_1000_reached"])
        packed = project({"own_growth": result["growth"]})["own_growth"]
        self.assertEqual(packed["recent_posts"][0]["question"], plan["question"])
        self.assertIn("not completion rate", packed["interpretation"])
        from cyberquiz.context import read

        self.assertEqual(read(self.db, "performance")["recent_posts"], [post])

    def test_account_growth_is_daily_and_not_per_reel_attribution(self):
        with (
            patch(
                "cyberquiz.instagram.secrets", return_value={"IG_USER_ID": "account"}
            ),
            patch("cyberquiz.instagram.now", return_value="2026-11-05T18:00:00+00:00"),
            patch(
                "cyberquiz.instagram.graph", return_value={"followers_count": 100}
            ) as graph,
        ):
            account_snapshot(self.db)
            account_snapshot(self.db)
            graph.assert_called_once()
        with (
            patch(
                "cyberquiz.instagram.secrets", return_value={"IG_USER_ID": "account"}
            ),
            patch("cyberquiz.instagram.now", return_value="2026-11-06T18:00:00+00:00"),
            patch("cyberquiz.instagram.graph", return_value={"followers_count": 104}),
        ):
            account_snapshot(self.db)
        result = growth(self.db)
        self.assertEqual(result["follower_change"], 4)
        self.assertIn("cannot be attributed", result["interpretation"])

    def test_failed_account_read_stays_unknown_and_does_not_poll(self):
        with (
            patch(
                "cyberquiz.instagram.secrets", return_value={"IG_USER_ID": "account"}
            ),
            patch(
                "cyberquiz.instagram.graph", side_effect=RuntimeError("unavailable")
            ) as graph,
        ):
            account_snapshot(self.db)
            account_snapshot(self.db)
            graph.assert_called_once()
        self.assertIsNone(
            self.db.execute("SELECT followers FROM account_snapshots").fetchone()[0]
        )
        self.assertIsNone(growth(self.db)["follower_change"])

    def test_experiment_model_receives_growth_even_with_cached_research(self):
        from cyberquiz.experiments import ensure

        with (
            patch("cyberquiz.experiments.config", return_value={}),
            patch(
                "cyberquiz.learning.growth",
                return_value={"recent_posts": [{"views": 2500}]},
            ),
            patch(
                "cyberquiz.experiments.cloudflare.llm",
                return_value={"hold_reason": "Need more observations"},
            ) as model,
        ):
            ensure(self.db, {})
        facts = json.loads(model.call_args.args[2][1]["content"])
        self.assertEqual(
            facts["recent_growth_observations"]["recent_posts"][0]["views"], 2500
        )

    def test_follow_reason_is_before_answer_without_forcing_an_exam_claim(self):
        p = {
            "question": "Links are up.\nWhy does ping fail?",
            "explanation": "The VLANs differ.",
            "fix": "Match the access VLANs.",
            "clue": "No router.",
            "source_url": "https://example.com/docs",
            "certification": "CCNA",
        }
        text = caption(p)
        self.assertIn("Follow for visual CCNA practice.", text)
        self.assertLess(text.index("Follow for"), text.index(p["explanation"]))
        self.assertIn("#CCNA", text)
        p["content_scope"] = "industry"
        self.assertNotIn("CCNA practice", caption(p))
