import unittest
from unittest.mock import patch
from cyberquiz.control import execute

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
                    execute("schedule", {"posts_per_day": len(times), "slots": times})
            update.assert_not_called()
            execute(
                "schedule",
                {
                    "posts_per_day": 2,
                    "slots": ["09:00", "17:00"],
                    "adaptive_posting_times": False,
                },
            )
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
            self.assertIn("missing Meta token", execute("posting", {"enabled": True}))
            update.assert_not_called()

    def test_budget_cannot_increase_or_enable_paid_calls(self):
        with (
            patch("cyberquiz.control.config", return_value=CFG),
            patch("cyberquiz.control.update_config") as update,
        ):
            for value in [2, -1, True, float("nan")]:
                with self.assertRaises(ValueError):
                    execute("set_budget", {"monthly_budget_usd": value})
            update.assert_not_called()
            execute("set_budget", {"monthly_budget_usd": 0.5})
            update.assert_called_once_with(
                {"monthly_budget_usd": 0.5, "per_job_budget_usd": 0.03}
            )
