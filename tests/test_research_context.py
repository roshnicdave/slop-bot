import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cyberquiz.research_context import messages
from cyberquiz.store import connect, now


class ResearchBudgetTests(unittest.TestCase):
    def test_large_unicode_research_is_structurally_packed_under_provider_limit(self):
        url = "https://example.com/article/" + "x" * 1300
        prompt = {
            "task": "Return source-grounded ideas",
            "user_preference": "新" * 2000,
            "sources": [
                {"url": url + str(i), "title": "新" * 2000, "summary": "新" * 4000}
                for i in range(8)
            ],
            "recent": [
                {"family": "network", "question": "新" * 2000} for _ in range(50)
            ],
            "supported_scenes": [
                {"key": str(i), "question": "新" * 2000} for i in range(40)
            ],
            "inspected_reference_examples": [{"observations": ["新" * 4000] * 10}] * 3,
            "social_evidence": {
                "topic_wide_discovery": {
                    "examples": [
                        {
                            "url": "https://example.com/reel/1",
                            "inspection": {"findings": {"visible_hook": "新" * 4000}},
                        }
                    ]
                    * 20
                }
            },
        }
        packed = messages("Evidence editor", prompt)
        self.assertLessEqual(
            len(json.dumps(packed, ensure_ascii=False).encode()) + 512, 16000
        )
        self.assertLess(
            len(json.dumps({"messages": packed, "max_tokens": 1000})), 48000
        )
        view = json.loads(packed[1]["content"])
        self.assertTrue(view["sources"])
        self.assertIn(view["sources"][0]["url"], [x["url"] for x in prompt["sources"]])
        self.assertLess(len(view["supported_scenes"]), 40)

    def test_legacy_local_failure_recovers_without_replaying_provider_submission(self):
        from cyberquiz.scout import daily, ResearchDeferred

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "data/research"
            target.mkdir(parents=True)
            day = now()[:10]
            marker = target / (day + "-v2.error.json")
            marker.write_text(json.dumps({"created": now(), "error": "ValueError"}))
            db = connect(root / "db")
            with (
                patch("cyberquiz.scout.ROOT", root),
                patch(
                    "cyberquiz.scout._daily", return_value={"ideas": ["verified"]}
                ) as work,
            ):
                with self.assertRaises(ResearchDeferred):
                    daily(db)
                self.assertEqual(daily(db, force=True), {"ideas": ["verified"]})
                work.assert_called_once()
            self.assertFalse(marker.exists())
            marker.write_text(
                json.dumps({"created": now(), "detail": "Provider outcome unknown"})
            )
            db.execute("CREATE TABLE cf_calls(operation TEXT,status TEXT)")
            db.execute(
                "INSERT INTO cf_calls VALUES(?,?)",
                ("daily-scout-v2:" + day, "reserved"),
            )
            db.commit()
            with (
                patch("cyberquiz.scout.ROOT", root),
                patch("cyberquiz.scout._daily") as work,
            ):
                with self.assertRaises(ResearchDeferred):
                    daily(db, force=True)
                work.assert_not_called()
            db.close()


class CompletedPlanningTests(unittest.TestCase):
    def test_completed_planning_is_reused_without_provider_call(self):
        from cyberquiz.scout import _planning_call

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            db.execute("CREATE TABLE cf_calls(operation TEXT,status TEXT,result TEXT)")
            value = {"ideas": [{"key": "article", "source_url": "https://example.com"}]}
            db.execute(
                "INSERT INTO cf_calls VALUES(?,?,?)",
                (
                    "plan",
                    "complete",
                    json.dumps({"success": True, "result": {"response": value}}),
                ),
            )
            with patch("cyberquiz.scout.cloudflare.llm") as provider:
                self.assertEqual(_planning_call(db, "plan", []), value)
                provider.assert_not_called()

    def test_article_key_is_normalized_only_for_approved_source(self):
        from cyberquiz.scout import _daily

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            db = connect(root / "db")
            evidence = {
                "records": [{"url": "https://blog.cloudflare.com/example"}],
                "social": {},
                "own_metrics": {"formats": {}},
                "reference_observations": [],
            }
            response = {
                "ideas": [
                    {
                        "key": "article-slug",
                        "topic": "Origins",
                        "source_url": evidence["records"][0]["url"],
                        "cta": "answer",
                    },
                    {
                        "key": "invented",
                        "topic": "Fake",
                        "source_url": "https://example.invalid",
                        "cta": "answer",
                    },
                ]
            }
            with (
                patch("cyberquiz.scout.ROOT", root),
                patch("cyberquiz.scout.gather", return_value=evidence),
                patch("cyberquiz.scout.scenarios.bank", return_value=[]),
                patch("cyberquiz.scout._planning_call", return_value=response),
            ):
                result = _daily(db)
            self.assertEqual(len(result["ideas"]), 1)
            self.assertEqual(result["ideas"][0]["key"], "source")
