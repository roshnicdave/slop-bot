"""Durable production inbox. Telegram/chat stay in separate processes."""

import datetime as dt
import fcntl
import json

from .store import ROOT, connect, config, transaction, worker_lock
from .telegram import tables, send as deliver, video, notify


def run(db, row):
    def send(user, facts):
        from .agent import event_reply

        text = event_reply(db, "worker-reply:" + str(row["id"]), facts)
        return deliver(user, text)

    ident = row["id"]
    user = row["user_id"]
    command = row["command"]
    parts = command.split(maxsplit=1)
    try:
        if parts[0] == "/refill":
            from .readiness import ensure

            ensure(db)
        elif parts[0] == "/publish-next":
            from .operator import publish_next

            publish_next(db, ident)
        elif parts[0] == "/next":
            from .production import make

            # An update ID is a stable idempotency key, not a new job on retry.
            slot = "telegram:" + str(ident)
            existing = db.execute(
                "SELECT id,status FROM jobs WHERE slot=?", (slot,)
            ).fetchone()
            if existing:
                send(user, {"event": "existing_work", "job": dict(existing)})
            else:
                try:
                    scene_key = json.loads(row["result"] or "{}").get("scene_key")
                except ValueError:
                    scene_key = None
                job = make(db, slot=slot, scene_key=scene_key)
                if (
                    db.execute("SELECT status FROM jobs WHERE id=?", (job,)).fetchone()[
                        0
                    ]
                    == "rendered"
                ):
                    db.execute(
                        'UPDATE jobs SET status="preview",approved=0 WHERE id=?', (job,)
                    )
                    db.commit()
                    video(config().get("telegram_owner_user_id", user), job)
        elif parts[0] == "/preview":
            job = parts[1].strip() if len(parts) > 1 else ""
            if not job:
                latest = db.execute(
                    'SELECT j.id FROM jobs j LEFT JOIN telegram_media t ON t.job=j.id WHERE t.file_id IS NOT NULL OR j.status="rendered" ORDER BY j.created DESC LIMIT 1'
                ).fetchone()
                job = latest[0] if latest else ""
            if job:
                video(user, job)
            else:
                send(user, {"event": "preview_unavailable"})
        elif parts[0] == "/research":
            from .scout import daily

            result = daily(db)
            send(
                user,
                {
                    "event": "research_completed",
                    "day": result["day"],
                    "ideas": result["ideas"],
                    "limitations": result.get("limitations"),
                    "scope": "Configured daily primary-source feeds",
                },
            )
        from .incidents import resolve

        resolve(db, "worker", phase=parts[0])
        db.execute('UPDATE telegram_updates SET status="done" WHERE id=?', (ident,))
        db.commit()
    except Exception as exc:
        db.execute(
            'UPDATE telegram_updates SET status="failed",result=? WHERE id=?',
            (type(exc).__name__, ident),
        )
        db.commit()
        from .incidents import record

        reason = str(exc)[:220] if isinstance(exc, ValueError) else type(exc).__name__
        record(db, "worker", parts[0], None, reason)
        send(
            user, {"event": "work_failed", "error": reason, "receipts_preserved": True}
        )

    finally:
        from .health import check

        check(db)


def main():
    import os
    import select
    import socket
    from .schedule import deadline

    db = connect()
    tables(db)
    db.execute(
        'UPDATE telegram_updates SET status="interrupted" WHERE status="running"'
    )
    db.commit()
    # A daemon lease protects the socket from concurrent worker startups.
    with (ROOT / "data" / "worker-daemon.lock").open("w") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = ROOT / "data" / "worker.sock"
        path.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as wake:
            wake.bind(str(path))
            os.chmod(path, 0o600)
            due = dt.datetime.now(dt.timezone.utc)
            try:
                while True:
                    try:
                        with transaction(db):
                            row = db.execute(
                                'SELECT * FROM telegram_updates WHERE status="queued" ORDER BY created,id LIMIT 1'
                            ).fetchone()
                            if row:
                                db.execute(
                                    'UPDATE telegram_updates SET status="running" WHERE id=?',
                                    (row["id"],),
                                )
                        if row:
                            with worker_lock():
                                run(db, row)
                            continue
                        clock = dt.datetime.now(dt.timezone.utc)
                        if clock >= due:
                            from .__main__ import tick

                            tick(db)
                            from .incidents import resolve

                            resolve(db, "worker", phase="maintenance")
                            due = deadline(config())
                        timeout = max(
                            0, (due - dt.datetime.now(dt.timezone.utc)).total_seconds()
                        )
                        if select.select([wake], [], [], timeout)[0]:
                            wake.recv(4096)
                            due = dt.datetime.now(dt.timezone.utc)
                    except Exception as exc:
                        from .incidents import record

                        incident = record(
                            db, "worker", "maintenance", None, type(exc).__name__
                        )
                        try:
                            notify(
                                db,
                                "worker-error:"
                                + dt.datetime.now(dt.timezone.utc).date().isoformat()
                                + ":"
                                + type(exc).__name__,
                                json.dumps(
                                    {
                                        "event": "maintenance_failed",
                                        "incident": incident,
                                        "failure_type": type(exc).__name__,
                                        "publication_attempted": "consult job phase and receipts",
                                    }
                                ),
                            )
                        except Exception:
                            pass
                        # Bounded recovery wait; no one-minute idle polling.
                        if select.select([wake], [], [], 300)[0]:
                            wake.recv(4096)
                        due = dt.datetime.now(dt.timezone.utc)
            finally:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
