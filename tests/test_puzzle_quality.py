import unittest
from unittest.mock import patch
from cyberquiz.scenarios import bank, dns, plan, vlan
from cyberquiz.quality import review


class PuzzleQualityTests(unittest.TestCase):
    def evaluate(self, **changes):
        p = plan(vlan(), {}, "test")
        solver = {
            "answer_index": p["correct"],
            "ambiguous": False,
            "issues": [],
            "title_gives_answer": False,
            "diagram_needed": True,
            "plausible_distractors": True,
        }
        solver.update(changes)
        with patch("cyberquiz.quality.cloudflare.llm", return_value=solver) as model:
            result = review(None, "test", p)
        return result, model.call_args.args[2]

    def test_generic_pass_cannot_bypass_actual_solution(self):
        self.assertFalse(self.evaluate(answer_index=None)[0]["passed"])

    def test_wrong_solution_or_ambiguity_prevents_approval(self):
        for change in (
            {"answer_index": 99},
            {"ambiguous": True},
            {"title_gives_answer": True},
            {"diagram_needed": False},
            {"plausible_distractors": False},
        ):
            self.assertFalse(self.evaluate(**change)[0]["passed"])

    def test_valid_puzzle_passes_independent_solution(self):
        result, messages = self.evaluate()
        self.assertTrue(result["passed"])
        self.assertNotIn("verified_answer_key", messages[1]["content"])
        self.assertNotIn("post_caption", messages[1]["content"])

    def test_legacy_dns_puzzle_is_not_selected_for_new_reels(self):
        self.assertNotIn(dns()["key"], {p["key"] for p in bank()})

    def test_literal_answer_in_opening_is_rejected_without_inference(self):
        p = plan(vlan(), {}, "test")
        p["question"] = "The PCs are in different VLANs.\nWhy does ping fail?"
        p["intro"] = p["question"].replace("\n", " ")
        with patch("cyberquiz.quality.cloudflare.llm") as model:
            self.assertFalse(review(None, "test", p)["passed"])
            model.assert_not_called()
