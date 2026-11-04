"""Posting deadlines and quiet maintenance wakes, in the configured timezone."""

import datetime as dt
from zoneinfo import ZoneInfo


def next_post_at(cfg, published, clock=None):
    """Unfilled daily posts remain due; the publication ledger survives restarts."""
    if not cfg.get("publishing_enabled") or cfg.get("emergency_pause"):
        return None
    clock = clock or dt.datetime.now(dt.timezone.utc)
    zone = ZoneInfo(cfg["timezone"])
    local = clock.astimezone(zone)
    slots = sorted(cfg["slots"][: cfg["posts_per_day"]])
    if not slots:
        return None
    count = sum(p.astimezone(zone).date() == local.date() for p in published)
    day = local if count < len(slots) else local + dt.timedelta(days=1)
    slot = slots[count] if count < len(slots) else slots[0]
    hour, minute = map(int, slot.split(":"))
    due = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    earliest = (
        max(published) + dt.timedelta(minutes=cfg.get("min_post_spacing_minutes", 360))
        if published
        else clock
    )
    hold = cfg.get("publishing_not_before")
    if hold:
        earliest = max(earliest, dt.datetime.fromisoformat(hold))
    candidate = max(due, earliest)
    if candidate.astimezone(zone).date() > due.date():
        # Never burst old-day obligations into a new day's quota.
        day = candidate.astimezone(zone)
        hour, minute = map(int, slots[0].split(":"))
        candidate = max(
            candidate, day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        )
    return candidate.astimezone(dt.timezone.utc)


def deadline(cfg, clock=None, *, published=(), ready=False):
    clock = clock or dt.datetime.now(dt.timezone.utc)
    local = clock.astimezone(ZoneInfo(cfg["timezone"]))
    waits = [6 * 3600]  # auth, source, metrics and cleanup maintenance
    due = next_post_at(cfg, published, clock)
    if due is not None:
        seconds = (due - clock).total_seconds()
        waits.append(max(1, seconds) if seconds > 0 or ready else 1800)
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
