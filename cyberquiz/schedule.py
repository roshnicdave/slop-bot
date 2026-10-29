"""Posting deadlines and quiet maintenance wakes, in the configured timezone."""

import datetime as dt
from zoneinfo import ZoneInfo


def deadline(cfg, clock=None):
    clock = clock or dt.datetime.now(dt.timezone.utc)
    local = clock.astimezone(ZoneInfo(cfg["timezone"]))
    waits = [6 * 3600]  # auth, source, metrics and cleanup maintenance
    if cfg.get("adaptive_posting_times"):
        midnight = (local + dt.timedelta(days=1)).replace(
            hour=0, minute=0, second=1, microsecond=0
        )
        waits.append((midnight.astimezone(dt.timezone.utc) - clock).total_seconds())
    if cfg.get("generation_enabled") or cfg.get("publishing_enabled"):
        for slot in cfg["slots"][: cfg["posts_per_day"]]:
            hour, minute = map(int, slot.split(":"))
            due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if due <= local:
                due += dt.timedelta(days=1)
            waits.append(
                max(1, (due.astimezone(dt.timezone.utc) - clock).total_seconds())
            )
    return clock + dt.timedelta(seconds=min(waits))
