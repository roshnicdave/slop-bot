"""Durable operator intents against the same jobs used by the scheduler."""

from .store import config, worker_lock, now


def publish_next(db, request_id):
    from .instagram import publish
    from .production import make
    from .auth_health import check

    with worker_lock():
        db.execute(
            "CREATE TABLE IF NOT EXISTS operator_requests(id TEXT PRIMARY KEY,job TEXT,created TEXT)"
        )
        db.commit()
        saved = db.execute(
            "SELECT job FROM operator_requests WHERE id=?", (str(request_id),)
        ).fetchone()
        if saved and saved[0]:
            job = db.execute("SELECT * FROM jobs WHERE id=?", (saved[0],)).fetchone()
            if job["status"] == "published":
                return job["id"]
        else:
            job = None
        cfg = config()
        if cfg.get("emergency_pause") or not cfg.get("publishing_enabled"):
            raise ValueError("Posting is paused. Ask me to resume first.")
        if not check():
            raise ValueError("Instagram authorization needs renewal.")
        if db.execute(
            "SELECT 1 FROM jobs WHERE status IN ('publish_unknown','container_submitting')"
        ).fetchone():
            raise ValueError(
                "A previous publication has an unknown outcome. Reconcile it before posting again."
            )
        if not job:
            job = db.execute(
                "SELECT * FROM jobs WHERE approved=1 AND status IN ('rendered','container_created') ORDER BY created LIMIT 1"
            ).fetchone()
            if not job:
                if not cfg.get("generation_enabled"):
                    raise ValueError("Queue is empty and generation is paused.")
                # Stable slot prevents repeated generation after a crash or redelivery.
                slot = "operator:" + str(request_id)
                job = db.execute("SELECT * FROM jobs WHERE slot=?", (slot,)).fetchone()
                if not job:
                    ident = make(db, slot=slot)
                    job = db.execute(
                        "SELECT * FROM jobs WHERE id=?", (ident,)
                    ).fetchone()
            db.execute(
                "INSERT OR REPLACE INTO operator_requests VALUES(?,?,?)",
                (str(request_id), job["id"], now()),
            )
            db.commit()
        if (
            job["status"] not in ("rendered", "container_created")
            or not job["approved"]
        ):
            raise ValueError(
                "The next job is "
                + job["status"]
                + "; it has not passed publication checks."
            )
        # Explicit Telegram intent overrides the scheduled time, never quality,
        # authorization, pause, budget or uncertain-publication protections.
        publish(db, job["id"], immediate=True)
        return job["id"]
