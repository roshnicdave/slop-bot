"""Use comparable 72-hour posts; never equate a lucky view spike with proof."""

import json
import random
import statistics


def metric(payload, name):
    data = payload.get(name, {})
    try:
        item = data["data"][0]
        value = item.get("total_value", {}).get("value")
        if value is None:
            value = item["values"][0]["value"]
        return float(value)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def growth(db):
    """Recent observations for creative planning, never early winner selection."""
    posts = []
    for job in db.execute(
        "SELECT id,media_id,published_at,plan FROM jobs WHERE status='published' ORDER BY published_at DESC LIMIT 6"
    ):
        snap = db.execute(
            "SELECT payload,age_hours,observed FROM metrics WHERE media_id=? ORDER BY age_hours DESC LIMIT 1",
            (job["media_id"],),
        ).fetchone()
        if not snap:
            continue
        payload, p = json.loads(snap["payload"]), json.loads(job["plan"] or "{}")
        reach = metric(payload, "reach")
        watch = metric(payload, "ig_reels_avg_watch_time")
        artifact = p.get("quality", {}).get("artifact", {})
        duration = artifact.get("duration_seconds")
        entry = {
            "job": job["id"],
            "question": str(p.get("question", ""))[:120],
            "family": p.get("family"),
            "certification": p.get("certification"),
            "countdown_style": p.get(
                "countdown_style", artifact.get("countdown_style", "bar")
            ),
            "tick_level_dbfs": p.get(
                "tick_level_dbfs",
                (artifact.get("sound_cues") or {}).get("tick_level_dbfs"),
            ),
            "presentation_version": p.get("quality", {})
            .get("artifact", {})
            .get("presentation_version", 0),
            "opening_lines": len(str(p.get("question", "")).splitlines()),
            "snapshot_age_hours": round(snap["age_hours"], 1),
            "observed_at": snap["observed"],
            "reach": reach,
            "views": metric(payload, "views"),
            "average_watch_seconds": None if watch is None else round(watch / 1000, 3),
            "duration_seconds": duration,
            "average_watch_fraction": round(watch / 1000 / duration, 3)
            if watch is not None and isinstance(duration, (float, int)) and duration > 0
            else None,
        }
        for name in ("likes", "shares", "saved", "follows"):
            value = metric(payload, name)
            entry[name + "_per_1000_reached"] = (
                round(1000 * value / reach, 2)
                if value is not None and reach is not None and reach > 0
                else None
            )
        posts.append(entry)
    account = []
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='account_snapshots'"
    ).fetchone():
        account = [
            dict(r)
            for r in db.execute(
                "SELECT observed_at,followers FROM account_snapshots WHERE followers IS NOT NULL ORDER BY day DESC LIMIT 7"
            )
        ]
    return {
        "recent_posts": posts,
        "account_followers": account,
        "follower_change": account[0]["followers"] - account[-1]["followers"]
        if len(account) >= 2
        else None,
        "interpretation": "Different snapshot ages are not a fair ranking. Use early data to propose hypotheses; retain comparable 72-hour results for adoption. Average watch fraction is not completion rate and may include replays. Missing follows are unavailable, not zero; account follower changes cannot be attributed to individual Reels. Shares are not an isolated DM-send metric.",
    }


def analyze(db):
    groups = {}
    posts = []
    for job in db.execute('SELECT media_id,plan FROM jobs WHERE status="published"'):
        # One snapshot per post at a comparable age. Do not compare 1h to 7d.
        row = db.execute(
            "SELECT payload,age_hours FROM metrics WHERE media_id=? AND age_hours BETWEEN 60 AND 84 ORDER BY ABS(age_hours-72) LIMIT 1",
            (job["media_id"],),
        ).fetchone()
        if not row:
            continue
        payload = json.loads(row["payload"])
        reach = metric(payload, "reach")
        if reach is None or reach < 100:
            continue
        follows = metric(payload, "follows")
        shares = metric(payload, "shares")
        saved = metric(payload, "saved")
        if shares is None:
            continue
        p = json.loads(job["plan"])
        score = 1000 * shares / reach
        entry = {
            "media_id": job["media_id"],
            "format": p["format"],
            "family": p["family"],
            "reach": reach,
            "follows_per_1000": None if follows is None else 1000 * follows / reach,
            "shares_per_1000": 1000 * shares / reach,
            "saves_per_1000": None if saved is None else 1000 * saved / reach,
            "score": score,
        }
        posts.append(entry)
        groups.setdefault(p["format"], []).append(score)
    eligible = {k: statistics.median(v) for k, v in groups.items() if len(v) >= 5}
    winner = max(eligible, key=eligible.get) if len(eligible) >= 2 else None
    return {
        "comparable_posts": len(posts),
        "formats": {
            k: {"posts": len(v), "median_shares_per_1000": statistics.median(v)}
            for k, v in groups.items()
        },
        "objective": "shares per 1000 reached; follows and saves are separate outcomes",
        "preferred_format": winner,
        "experiment_share": 0.25,
        "posts": posts,
        "growth": growth(db),
        "cadence_recommendation": "Use the configured cadence. Compare similar-age reach, shares and follows while accounting for topic and format differences; two posts per day is an experiment, not a virality guarantee.",
    }


def select_format(db, job):
    result = analyze(db)
    rng = random.Random(job)
    if result["preferred_format"] and rng.random() >= 0.25:
        return result["preferred_format"]
    return rng.choice(["quiz", "challenge"])


def experiment(db, p, job):
    from .experiments import assign

    return assign(db, p, job)
