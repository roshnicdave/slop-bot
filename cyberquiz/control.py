"""Validated state changes used by the agent's typed capabilities."""

import re
from .store import config
from .providers import secrets
from .telegram import update_config


def set_publishing(enabled):
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be boolean")
    if enabled and not secrets().get("IG_ACCESS_TOKEN"):
        raise ValueError("Missing Meta token")
    if enabled and config().get("emergency_pause"):
        raise ValueError("Pipeline is paused")
    update_config({"publishing_enabled": enabled})
    return {"publishing_enabled": enabled}


def set_schedule(slots):
    if (
        not isinstance(slots, list)
        or len(slots) not in (1, 2)
        or any(
            not isinstance(t, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t)
            for t in slots
        )
    ):
        raise ValueError("Specify one or two valid daily times")
    minutes = sorted(int(t[:2]) * 60 + int(t[3:]) for t in slots)
    if (
        len(minutes) == 2
        and min(minutes[1] - minutes[0], 1440 - minutes[1] + minutes[0]) < 360
    ):
        raise ValueError("Post times must be at least six hours apart")
    state = {
        "posts_per_day": len(slots),
        "slots": sorted(slots),
        "adaptive_posting_times": False,
    }
    update_config(state)
    return {**state, "timezone": config()["timezone"]}


def lower_budget(amount):
    cfg = config()
    if (
        isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or not 0 <= amount <= cfg["monthly_budget_usd"]
    ):
        raise ValueError("Budget must be nonnegative and cannot increase")
    state = {
        "monthly_budget_usd": amount,
        "per_job_budget_usd": min(amount, cfg["per_job_budget_usd"]),
    }
    update_config(state)
    return state
