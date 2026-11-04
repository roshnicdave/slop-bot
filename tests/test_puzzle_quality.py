import unittest
from unittest.mock import patch
from cyberquiz.scenarios import bank, dns, plan, vlan
from cyberquiz.quality import review


class PuzzleQualityTests(unittest.TestCase):
    def test_rejected_opening_has_one_rewrite_without_relaxing_review(self):
        from cyberquiz.editorial import review_opening

        p = plan(vlan(), {}, "test")
        held = {"passed": False, "editorial": {"issues": ["Opening is unclear"]}}
        with (
            patch("cyberquiz.quality.review", side_effect=[held, held.copy()]) as check,
            patch("cyberquiz.editorial.craft", return_value=p) as rewrite,
        ):
            _, result = review_opening(None, "test", p, {})
            self.assertFalse(result["passed"])
            self.assertTrue(result["opening_rewritten"])
            self.assertEqual(check.call_count, 2)
            rewrite.assert_called_once()
            self.assertEqual(
                rewrite.call_args.args[3]["editorial_feedback"], held["editorial"]
            )

    def evaluate(self, **changes):
        p = plan(vlan(), {}, "test")
        solver = {
            "answer_text": p["answer"],
            "ambiguous": False,
            "clear_question": True,
            "issues": [],
            "title_gives_answer": False,
            "diagram_needed": True,
            "plausible_distractors": True,
        }
        solver.update(changes)

        def respond(db, operation, messages, **kwargs):
            return (
                {"restates_option": None}
                if operation.endswith(":title-review")
                else solver
            )

        with patch("cyberquiz.quality.cloudflare.llm", side_effect=respond) as model:
            result = review(None, "test", p)
        return result, model.call_args.args[2]

    def test_generic_pass_cannot_bypass_actual_solution(self):
        self.assertFalse(self.evaluate(answer_text=None)[0]["passed"])

    def test_solver_must_choose_exact_option_text_instead_of_inventing_index(self):
        self.assertTrue(self.evaluate(answer_index=999)[0]["passed"])
        self.assertFalse(
            self.evaluate(answer_text="Some other interpretation")[0]["passed"]
        )

    def test_wrong_solution_or_ambiguity_prevents_approval(self):
        for change in (
            {"answer_text": "Wrong cable"},
            {"ambiguous": True},
            {"clear_question": False},
            {"clear_question": None},
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

    def test_blind_title_review_catches_paraphrased_answer_before_solving(self):
        p = plan(vlan(), {}, "test")
        p["question"] = "The ports have separate VLAN IDs.\nWhy does ping fail?"
        with patch(
            "cyberquiz.quality.cloudflare.llm",
            return_value={
                "restates_option": p["answer"],
                "reasoning": "The premise states the diagnosis",
            },
        ) as model:
            self.assertFalse(review(None, "test", p)["passed"])
            model.assert_called_once()
            candidate = model.call_args.args[2][1]["content"]
            self.assertNotIn('"diagram"', candidate)
            self.assertNotIn('"correct"', candidate)

    def test_statement_only_opening_cannot_reach_the_reviewer(self):
        p = plan(vlan(), {}, "test")
        p["question"] = "Pool addresses all leased\nNew client gets no offer"
        p["intro"] = p["question"].replace("\n", " ")
        with patch("cyberquiz.quality.cloudflare.llm") as model:
            with self.assertRaisesRegex(ValueError, "ask a question"):
                review(None, "test", p)
            model.assert_not_called()

    def test_visible_question_with_statement_narration_is_rejected(self):
        p = plan(vlan(), {}, "test")
        p["intro"] = "Both links are green."
        with self.assertRaisesRegex(ValueError, "narration"):
            review(None, "test", p)
