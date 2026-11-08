import unittest
from unittest.mock import patch
from cyberquiz.scenarios import bank, dns, plan, vlan
from cyberquiz.quality import review


class PuzzleQualityTests(unittest.TestCase):
    def test_missing_dns_label_cannot_restate_the_correct_option(self):
        from cyberquiz.quality import check_absence_labels

        p = {"answer": "PC lacks DNS server address"}
        with patch(
            "cyberquiz.lab_visual.evidence",
            return_value={"nodes": [{"details": ["IP 10.0.0.20/24", "No DNS"]}]},
        ):
            with self.assertRaisesRegex(ValueError, "restates"):
                check_absence_labels(p)

    def test_no_router_is_not_the_answer_to_a_vlan_comparison(self):
        from cyberquiz.quality import check_absence_labels

        with patch(
            "cyberquiz.lab_visual.evidence",
            return_value={"details": ["No router", "VLAN 10", "VLAN 20"]},
        ):
            check_absence_labels({"answer": "Different VLANs"})

    def test_negative_observation_does_not_restate_an_unrelated_missing_setting(self):
        from cyberquiz.quality import check_absence_labels

        with patch(
            "cyberquiz.lab_visual.evidence", return_value={"details": ["No UDP reply"]}
        ):
            check_absence_labels({"answer": "Missing firewall permit"})

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
            "evidence_consistent": True,
            "issues": [],
            "title_gives_answer": False,
            "diagram_needed": True,
            "plausible_distractors": True,
        }
        solver.update(changes)

        def respond(db, operation, messages, **kwargs):
            return (
                {
                    "restates_option": None,
                    "diagram_restates_option": None,
                    "technical_inference": True,
                }
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
            {"evidence_consistent": False},
            {"title_gives_answer": True},
            {"diagram_needed": False},
            {"plausible_distractors": False},
        ):
            self.assertFalse(self.evaluate(**change)[0]["passed"])

    def test_answer_disagreement_returns_actionable_revision_feedback(self):
        result, _ = self.evaluate(answer_text="Wrong cable")
        issues = " ".join(result["editorial"]["issues"])
        self.assertIn("Wrong cable", issues)
        self.assertIn("intended answer", issues)
        self.assertIn("overlapping correct choices", issues)

    def test_valid_puzzle_passes_independent_solution(self):
        result, messages = self.evaluate()
        self.assertTrue(result["passed"])
        self.assertNotIn("verified_answer_key", messages[1]["content"])
        self.assertNotIn("post_caption", messages[1]["content"])

    def test_notes_about_the_intentional_fault_do_not_override_explicit_checks(self):
        self.assertTrue(self.evaluate(issues=["Different VLANs shown"])[0]["passed"])

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
            self.assertIn('"diagram"', candidate)
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

    def test_diagram_that_repeats_a_choice_is_rejected_before_solving(self):
        p = plan(vlan(), {}, "test")
        with patch(
            "cyberquiz.quality.cloudflare.llm",
            return_value={
                "restates_option": None,
                "diagram_restates_option": p["answer"],
                "technical_inference": False,
            },
        ) as model:
            self.assertFalse(review(None, "test", p)["passed"])
            model.assert_called_once()

    def test_missing_diagram_audit_cannot_reuse_an_old_title_pass(self):
        p = plan(vlan(), {}, "test")
        with patch(
            "cyberquiz.quality.cloudflare.llm", return_value={"restates_option": None}
        ):
            self.assertFalse(review(None, "test", p)["passed"])
