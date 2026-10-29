"""Keep one quality-checked Reel staged; refill without minute polling."""

import datetime as dt
from zoneinfo import ZoneInfo
from .store import config, now, worker_lock


def ensure(db):
    from .production import make

    with worker_lock():
        cfg = config()
        if cfg.get("emergency_pause") or not cfg.get("generation_enabled"):
            return "paused"
        if db.execute(
            "SELECT 1 FROM jobs WHERE approved=1 AND status IN ('rendered','container_created') LIMIT 1"
        ).fetchone():
            return "ready"
        if db.execute(
            "SELECT 1 FROM jobs WHERE status IN ('voice','rendering','publish_unknown','container_submitting') LIMIT 1"
        ).fetchone():
            return "in_progress"
        db.execute(
            "CREATE TABLE IF NOT EXISTS readiness_attempts(id INTEGER PRIMARY KEY,created TEXT,status TEXT,job TEXT)"
        )
        db.commit()
        last = db.execute(
            "SELECT created,status FROM readiness_attempts ORDER BY id DESC LIMIT 1"
        ).fetchone()
        clock = dt.datetime.now(dt.timezone.utc)
        if (
            last
            and last[1] != "complete"
            and (clock - dt.datetime.fromisoformat(last[0])).total_seconds() < 1800
        ):
            return "backoff"
        local = clock.astimezone(ZoneInfo(cfg["timezone"]))
        count = sum(
            dt.datetime.fromisoformat(r[0]).astimezone(ZoneInfo(cfg["timezone"])).date()
            == local.date()
            for r in db.execute("SELECT created FROM readiness_attempts")
        )
        if count >= cfg["posts_per_day"] + 1:
            return "daily_limit"
        cursor = db.execute(
            "INSERT INTO readiness_attempts(created,status) VALUES(?,?)",
            (now(), "started"),
        )
        ident = cursor.lastrowid
        db.commit()
        try:
            job = make(db, slot="buffer:" + str(ident))
            db.execute(
                "UPDATE readiness_attempts SET status=?,job=? WHERE id=?",
                ("complete", job, ident),
            )
            db.commit()
            return job
        except Exception as exc:
            db.execute(
                "UPDATE readiness_attempts SET status=? WHERE id=?",
                ("failed:" + type(exc).__name__, ident),
            )
            db.commit()
            return "held"
