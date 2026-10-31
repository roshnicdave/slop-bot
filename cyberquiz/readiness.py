"""Keep one quality-checked Reel staged; refill without minute polling."""

import datetime as dt
from zoneinfo import ZoneInfo
from .store import config, now, worker_lock


def ensure(db, recover_preflight=False):
    from .production import make

    with worker_lock():
        cfg = config()
        if cfg.get("emergency_pause") or not cfg.get("generation_enabled"):
            return "paused"
        if db.execute(
            "SELECT 1 FROM jobs WHERE approved=1 AND status IN ('rendered','container_created') LIMIT 1"
        ).fetchone():
            from .incidents import resolve

            resolve(db, "readiness")
            return "ready"
        if db.execute(
            "SELECT 1 FROM jobs WHERE status IN ('voice','rendering','publish_unknown','container_submitting') LIMIT 1"
        ).fetchone():
            return "in_progress"
        db.execute(
            "CREATE TABLE IF NOT EXISTS readiness_attempts(id INTEGER PRIMARY KEY,created TEXT,status TEXT,job TEXT,error TEXT)"
        )
        if "error" not in {
            r[1] for r in db.execute("PRAGMA table_info(readiness_attempts)")
        }:
            db.execute("ALTER TABLE readiness_attempts ADD COLUMN error TEXT")
        db.commit()
        last = db.execute(
            "SELECT created,status,job FROM readiness_attempts ORDER BY id DESC LIMIT 1"
        ).fetchone()
        clock = dt.datetime.now(dt.timezone.utc)
        if (
            last
            and last[1] != "complete"
            and not (recover_preflight and last[2] is None)
            and (clock - dt.datetime.fromisoformat(last[0])).total_seconds() < 1800
        ):
            return "backoff"
        local = clock.astimezone(ZoneInfo(cfg["timezone"]))
        # Only an attempt that actually created a production job consumes the daily
        # generation allowance. Preflight failures cannot exhaust a day's output.
        count = sum(
            dt.datetime.fromisoformat(r[1]).astimezone(ZoneInfo(cfg["timezone"])).date()
            == local.date()
            and bool(
                db.execute(
                    "SELECT 1 FROM jobs WHERE slot=? OR slot LIKE ? LIMIT 1",
                    ("buffer:" + str(r[0]), "buffer:" + str(r[0]) + ":%"),
                ).fetchone()
            )
            for r in db.execute("SELECT id,created FROM readiness_attempts")
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
            row = db.execute(
                "SELECT status,approved FROM jobs WHERE id=?", (job,)
            ).fetchone()
            complete = row and row["status"] == "rendered" and row["approved"]
            db.execute(
                "UPDATE readiness_attempts SET status=?,job=? WHERE id=?",
                ("complete" if complete else "held_quality", job, ident),
            )
            db.commit()
            if complete:
                from .incidents import resolve

                resolve(db, "readiness")
            return job if complete else "held"
        except Exception as exc:
            from .incidents import record
            from .scout import ResearchDeferred

            detail = type(exc).__name__ + (
                ": " + str(exc)[:240]
                if isinstance(exc, (ValueError, RuntimeError))
                else ""
            )
            record(db, "readiness", "generation", None, detail)
            db.execute(
                "UPDATE readiness_attempts SET status=?,error=? WHERE id=?",
                (
                    "deferred:research"
                    if isinstance(exc, ResearchDeferred)
                    else "failed:" + type(exc).__name__,
                    type(exc).__name__
                    + (
                        ": " + str(exc)[:240]
                        if isinstance(exc, (ValueError, RuntimeError))
                        else ""
                    ),
                    ident,
                ),
            )
            db.commit()
            return "held"
