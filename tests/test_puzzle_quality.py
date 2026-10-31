import unittest
from unittest.mock import patch
from cyberquiz.scenarios import bank, dns, plan, vlan
from cyberquiz.quality import review


class PuzzleQualityTests(unittest.TestCase):
    def evaluate(self, checks):
        p = plan(vlan(), {}, "test")
        with patch(
            "cyberquiz.quality.cloudflare.llm",
            return_value={
                "pass": True,
                "issues": [],
                "puzzle_checks": checks,
            },
        ) as model:
            result = review(None, "test", p)
        return result, model.call_args.args[2]

    def test_generic_pass_cannot_bypass_puzzle_audit(self):
        result, _ = self.evaluate({})
        self.assertFalse(result["passed"])

    def test_leakage_or_trivial_distractors_prevent_approval(self):
        for failing in (
            "answer_not_given",
            "inference_required",
            "plausible_distractors",
        ):
            checks = {
                k: k != failing
                for k in (
                    "answer_not_given",
                    "inference_required",
                    "plausible_distractors",
                )
            }
            result, _ = self.evaluate(checks)
            self.assertFalse(result["passed"])

    def test_valid_puzzle_passes_explicit_audit(self):
        result, _ = self.evaluate(
            {
                k: True
                for k in (
                    "answer_not_given",
                    "inference_required",
                    "plausible_distractors",
                )
            }
        )
        self.assertTrue(result["passed"])

    def test_legacy_dns_puzzle_is_not_selected_for_new_reels(self):
        self.assertNotIn(dns()["key"], {p["key"] for p in bank()})
