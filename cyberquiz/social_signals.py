"""Bounded public engagement observations, distinct from reach or viral proof."""

import datetime as dt
import statistics
from .store import now


def tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS social_observations(
        account TEXT,post TEXT,observed TEXT,published TEXT,url TEXT,caption TEXT,
        media_type TEXT,followers INTEGER,likes INTEGER,comments INTEGER,
        PRIMARY KEY(account,post,observed))''')
    db.commit()


def observe(db, result):
    tables(db)
    for group in result.get("competitors", []):
        data = group.get("data", {})
        observed = group.get("observed_at") or result.get("checked_at")
        if not observed:
            continue
        for post in data.get("media", {}).get("data", [])[:12]:
            if not post.get("id"):
                continue
            db.execute("INSERT OR IGNORE INTO social_observations VALUES(?,?,?,?,?,?,?,?,?,?)", (
                group.get("username"), post["id"], observed, post.get("timestamp"),
                post.get("permalink"), str(post.get("caption", ""))[:600],
                post.get("media_type"), data.get("followers_count"),
                post.get("like_count"), post.get("comments_count"),
            ))
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)).isoformat()
    db.execute("DELETE FROM social_observations WHERE observed<?", (cutoff,))
    db.commit()


def analyze(db):
    tables(db)
    latest = db.execute('''SELECT o.* FROM social_observations o JOIN
        (SELECT account,post,MAX(observed) AS observed FROM social_observations GROUP BY account,post) x
        USING(account,post,observed) ORDER BY observed DESC LIMIT 200''').fetchall()
    candidates = []
    clock = dt.datetime.now(dt.timezone.utc)
    for row in latest:
        # Video can include non-Reel posts; never label it a verified Reel.
        if row["media_type"] != "VIDEO" or row["likes"] is None or row["comments"] is None:
            continue
        try:
            published = dt.datetime.fromisoformat(row["published"])
            observed = dt.datetime.fromisoformat(row["observed"])
            age = (observed - published).total_seconds() / 3600
            stale = (clock - observed).total_seconds() / 3600
        except (ValueError, TypeError):
            continue
        if not 0 < age <= 14 * 24 or stale > 48:
            continue
        prior = db.execute('''SELECT * FROM social_observations WHERE account=? AND post=?
            AND observed<? ORDER BY observed DESC LIMIT 1''', (row["account"], row["post"], row["observed"])).fetchone()
        velocity = None
        if prior and prior["likes"] is not None and prior["comments"] is not None:
            hours = (observed - dt.datetime.fromisoformat(prior["observed"])).total_seconds() / 3600
            delta = row["likes"] + row["comments"] - prior["likes"] - prior["comments"]
            if hours > 0 and delta >= 0:
                velocity = round(delta / hours, 3)
        engagement = row["likes"] + row["comments"]
        candidates.append({"account": row["account"], "post": row["post"], "url": row["url"],
            "caption": row["caption"], "observed_at": row["observed"], "age_hours": round(age, 1),
            "likes": row["likes"], "comments": row["comments"],
            "engagement_per_hour_since_post": round(engagement / max(age, 1), 3),
            "observed_growth_per_hour": velocity})
    for item in candidates:
        peers = [p["engagement_per_hour_since_post"] for p in candidates
                 if p["account"] == item["account"] and p["post"] != item["post"]
                 and item["age_hours"] / 2 <= p["age_hours"] <= item["age_hours"] * 2]
        baseline = statistics.median(peers) if len(peers) >= 3 else None
        item["relative_to_account_age_matched_median"] = (
            round(item["engagement_per_hour_since_post"] / baseline, 2) if baseline else None)
        item["baseline_posts"] = len(peers)
    candidates.sort(key=lambda p: (p["relative_to_account_age_matched_median"] or 0,
                                   p["observed_growth_per_hour"] or 0), reverse=True)
    return {"observed_at": now(), "candidate_videos": candidates[:6],
            "accounts_observed": len({r["account"] for r in latest}),
            "limitations": "Public video likes/comments only; no competitor reach, retention, shares, audio or visual inspection. Relative engagement and growth are observational hypotheses, not viral proof. Missing baselines remain unknown."}
