"""Daily model-proposed posting experiments, constrained by spacing and evidence."""

import datetime as dt
import json
import re
from zoneinfo import ZoneInfo
from .store import config
from .learning import metric
from . import cloudflare


def valid_slots(slots):
    if not isinstance(slots, list) or len(slots) != 2:
        return False
    if any(
        not isinstance(t, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t)
        for t in slots
    ):
        return False
    a, b = sorted(int(t[:2]) * 60 + int(t[3:]) for t in slots)
    return min(b - a, 1440 - b + a) >= 360


def plan(db, cfg, day):
    db.execute(
        "CREATE TABLE IF NOT EXISTS posting_plans(day TEXT PRIMARY KEY,payload TEXT)"
    )
    db.commit()
    saved = db.execute(
        "SELECT payload FROM posting_plans WHERE day=?", (day,)
    ).fetchone()
    if saved:
        return json.loads(saved[0])
    observations = []
    for row in db.execute(
        'SELECT media_id,published_at,plan FROM jobs WHERE status="published" AND published_at IS NOT NULL ORDER BY published_at DESC LIMIT 30'
    ):
        snap = db.execute(
            "SELECT payload FROM metrics WHERE media_id=? AND age_hours BETWEEN 60 AND 84 ORDER BY ABS(age_hours-72) LIMIT 1",
            (row["media_id"],),
        ).fetchone()
        local = dt.datetime.fromisoformat(row["published_at"]).astimezone(
            ZoneInfo(cfg["timezone"])
        )
        item = {
            "time": local.strftime("%H:%M"),
            "topic": json.loads(row["plan"]).get("topic", "")[:100],
        }
        if snap:
            payload = json.loads(snap[0])
            reach = metric(payload, "reach")
            shares = metric(payload, "shares")
            if reach is not None and reach >= 100 and shares is not None:
                item.update(reach=reach, shares_per_1000=1000 * shares / reach)
        observations.append(item)
    result = {
        "slots": cfg.get("slots", ["12:00", "20:00"]),
        "basis": "unproven: preserving previous schedule",
        "observations": observations,
    }
    try:
        proposed = cloudflare.llm(
            db,
            "posting-plan:" + day,
            [
                {
                    "role": "system",
                    "content": "Propose a two-Reel posting experiment for one day. Return JSON {slots:[two local HH:MM times],hypothesis}. Choose useful exploration based on the supplied own-account observations; you can propose new windows rather than selecting preset times. Keep posts at least six hours apart including overnight. Do not default to 9am and 5pm. Changing arbitrary minutes does not create virality. Without comparable measurements, describe the plan as unproven exploration. With measurements, compare approximately 72-hour outcomes while acknowledging topic/format confounding. Never invent follower geography, online hours, optimal times or evidence. No extra actions.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "day": day,
                            "timezone": cfg["timezone"],
                            "previous_schedule": cfg.get("slots"),
                            "observations": observations,
                        }
                    ),
                },
            ],
            max_tokens=240,
        )
        if not valid_slots(proposed.get("slots")):
            raise ValueError("Invalid posting experiment")
        result.update(
            slots=sorted(proposed["slots"]),
            basis=str(proposed.get("hypothesis", "unproven exploration"))[:500],
        )
    except Exception as exc:
        result["planner_unavailable"] = type(exc).__name__
    result["limitation"] = (
        "Unproven until comparable own-account results; topic, format and audience can confound timing."
    )
    db.execute("INSERT INTO posting_plans VALUES(?,?)", (day, json.dumps(result)))
    db.commit()
    return result


def apply(db):
    cfg = config()
    if not cfg.get("adaptive_posting_times"):
        return
    day = dt.datetime.now(ZoneInfo(cfg["timezone"])).date().isoformat()
    result = plan(db, cfg, day)
    if cfg.get("posting_plan_date") != day or cfg["slots"] != result["slots"]:
        from .telegram import update_config

        update_config({"slots": result["slots"], "posting_plan_date": day})
