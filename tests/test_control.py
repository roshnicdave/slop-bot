import unittest
from unittest.mock import patch
from cyberquiz.control import set_schedule, set_publishing, lower_budget

CFG = {
    "timezone": "America/Los_Angeles",
    "monthly_budget_usd": 1.8,
    "per_job_budget_usd": 0.03,
}


class TelegramControlTests(unittest.TestCase):
    def test_schedule_rejects_bursts_and_invalid_times(self):
        with (
            patch("cyberquiz.control.config", return_value=CFG),
            patch("cyberquiz.control.update_config") as update,
        ):
            for times in [["09:00", "10:00"], ["23:00", "02:00"], ["99:00"]]:
                with self.assertRaises(ValueError):
                    set_schedule(times)
            update.assert_not_called()
            set_schedule(["09:00", "17:00"])
            update.assert_called_once_with(
                {
                    "posts_per_day": 2,
                    "slots": ["09:00", "17:00"],
                    "adaptive_posting_times": False,
                }
            )

    def test_missing_token_blocks_publication_control(self):
        with (
            patch("cyberquiz.control.config", return_value=CFG),
            patch("cyberquiz.control.secrets", return_value={}),
            patch("cyberquiz.control.update_config") as update,
        ):
            with self.assertRaisesRegex(ValueError, "Missing Meta token"):
                set_publishing(True)
            update.assert_not_called()

    def test_budget_cannot_increase_or_enable_paid_calls(self):
        with (
            patch("cyberquiz.control.config", return_value=CFG),
            patch("cyberquiz.control.update_config") as update,
        ):
            for value in [2, -1, True, float("nan")]:
                with self.assertRaises(ValueError):
                    lower_budget(value)
            update.assert_not_called()
            lower_budget(0.5)
            update.assert_called_once_with(
                {"monthly_budget_usd": 0.5, "per_job_budget_usd": 0.03}
            )
