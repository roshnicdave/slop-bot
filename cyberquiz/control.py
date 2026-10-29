"""Typed Telegram controls. No shell, secret edits, or paid-provider switching."""

import re
from .store import config
from .providers import secrets
from .telegram import update_config


def execute(action, proposal):
    c = config()
    if action == "posting":
        enabled = proposal.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("Specify whether posting should be on or off")
        if enabled and not secrets().get("IG_ACCESS_TOKEN"):
            return "Posting is blocked by the missing Meta token. Generation stays autonomous."
        if enabled and c.get("emergency_pause"):
            return "The pipeline is paused. Resume it before enabling posting."
        update_config({"publishing_enabled": enabled})
        return "Scheduled posting " + ("enabled." if enabled else "paused.")
    if action == "schedule":
        slots = proposal.get("slots")
        count = proposal.get("posts_per_day")
        if type(count) is not int or count not in (1, 2):
            raise ValueError("Choose one or two daily posts")
        if (
            not isinstance(slots, list)
            or len(slots) != count
            or any(
                not isinstance(t, str)
                or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t)
                for t in slots
            )
        ):
            raise ValueError("Specify a time for each daily post")
        minutes = sorted(int(t[:2]) * 60 + int(t[3:]) for t in slots)
        if (
            count == 2
            and min(minutes[1] - minutes[0], 1440 - minutes[1] + minutes[0]) < 360
        ):
            raise ValueError("Post times must be at least six hours apart")
        update_config(
            {
                "posts_per_day": count,
                "slots": sorted(slots),
                "adaptive_posting_times": False,
            }
        )
        return (
            "Scheduled "
            + str(count)
            + "/day at "
            + ", ".join(sorted(slots))
            + " ("
            + c["timezone"]
            + ")."
        )
    if action == "set_budget":
        amount = proposal.get("monthly_budget_usd")
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not 0 <= amount <= c["monthly_budget_usd"]
        ):
            raise ValueError(
                "Telegram can lower the spending cap; increases are not enabled"
            )
        update_config(
            {
                "monthly_budget_usd": amount,
                "per_job_budget_usd": min(amount, c["per_job_budget_usd"]),
            }
        )
        return (
            f"Monthly paid-AI cap set to ${amount:.2f}. Paid fallback stays disabled."
        )
    raise ValueError("Unsupported control")
