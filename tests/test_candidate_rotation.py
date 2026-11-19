import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cyberquiz.store import connect, new_job
from cyberquiz.scenarios import vlan, subnet
from cyberquiz.scout import choose


class CandidateRotationTests(unittest.TestCase):
    def test_single_question_copy_keeps_the_verified_facts_and_choice_order(self):
        from cyberquiz.editorial import choices, craft
        from cyberquiz.scenarios import bank, plan

        p = plan(next(s for s in bank() if s["key"] == "acl-order"), {}, "test")
        facts = (p["model"].copy(), list(p["options"]), p["answer"], p["reveal_voice"])
        labels = ["Choice " + letter for letter in "ABCD"]
        with patch(
            "cyberquiz.editorial.cloudflare.llm",
            return_value={
                "question": "Why can't this PC open the website?",
                "choice_labels": labels,
            },
        ):
            result = craft(
                None, "test", p, {"editorial_feedback": {"issues": ["Vague opening"]}}
            )
        self.assertEqual(
            result["question"].replace("\n", " "), "Why can't this PC open the website?"
        )
        self.assertEqual(choices(result), labels)
        self.assertEqual(
            (
                result["model"],
                result["options"],
                result["answer"],
                result["reveal_voice"],
            ),
            facts,
        )

    def test_rejected_candidate_yields_to_another_concept(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "state.sqlite")
            ident = new_job(db, "first")
            db.execute(
                "UPDATE jobs SET status='held_quality',plan=? WHERE id=?",
                (json.dumps(vlan()), ident),
            )
            db.commit()
            with (
                patch(
                    "cyberquiz.scout.config",
                    return_value={"source_discovery_enabled": False},
                ),
                patch(
                    "cyberquiz.scout.scenarios.bank", return_value=[vlan(), subnet()]
                ),
                patch("cyberquiz.novelty.check"),
            ):
                picked = choose(db, {"ideas": [{"key": vlan()["key"]}]})
            self.assertEqual(picked["key"], subnet()["key"])
            db.close()

    def test_rejection_does_not_disable_a_concept_forever(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "state.sqlite")
            ident = new_job(db, "old")
            db.execute(
                "UPDATE jobs SET status='held_quality',plan=?,created='2020-01-01T00:00:00+00:00' WHERE id=?",
                (json.dumps(vlan()), ident),
            )
            db.commit()
            with (
                patch(
                    "cyberquiz.scout.config",
                    return_value={"source_discovery_enabled": False},
                ),
                patch("cyberquiz.scout.scenarios.bank", return_value=[vlan()]),
                patch("cyberquiz.novelty.check"),
            ):
                self.assertEqual(choose(db, {"ideas": []})["key"], vlan()["key"])
            db.close()

    def test_editorial_copy_cannot_rewrite_verified_reveal(self):
        from cyberquiz.scenarios import plan
        from cyberquiz.editorial import craft

        p = plan(vlan(), {}, "test")
        original = (p["reveal_voice"], p["fix_voice"])
        with patch(
            "cyberquiz.editorial.cloudflare.llm",
            return_value={
                "hook_lines": ["The links are up.", "Why does ping fail?"],
                "spoken_answer": "Invented technical claim",
                "spoken_fix": "Invented correction",
            },
        ):
            result = craft(None, "test", p, {"ideas": []})
        self.assertEqual((result["reveal_voice"], result["fix_voice"]), original)
        self.assertNotIn("Invented", result["caption"])
