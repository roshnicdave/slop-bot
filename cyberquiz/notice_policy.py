"""Notification lifecycle: history remains in SQLite; obsolete facts stay quiet."""

import datetime as dt
import json
from zoneinfo import ZoneInfo
from .store import now, config


def facts(value):
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"description": value}
    except (ValueError, TypeError):
        return {"description": value}


def prepare(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS notice_texts(event TEXT PRIMARY KEY,facts TEXT,text TEXT,attempts INTEGER DEFAULT 0)"
    )
    columns = {r[1] for r in db.execute("PRAGMA table_info(notice_texts)")}
    for key, kind in (
        ("next_attempt", "TEXT"),
        ("created", "TEXT"),
        ("state", "TEXT DEFAULT 'pending'"),
    ):
        if key not in columns:
            db.execute("ALTER TABLE notice_texts ADD COLUMN " + key + " " + kind)
    # Old operational notices predate current-state validation. Retain their
    # facts for inspection, but never drain that backlog into Telegram.
    db.execute(
        "UPDATE notice_texts SET state='delivered' WHERE created IS NULL AND EXISTS (SELECT 1 FROM notices n WHERE n.event=notice_texts.event)"
    )
    db.execute(
        "UPDATE notice_texts SET state='superseded' WHERE created IS NULL AND event NOT LIKE 'published:%' AND NOT EXISTS (SELECT 1 FROM notices n WHERE n.event=notice_texts.event)"
    )
    db.execute(
        "UPDATE notice_texts SET created=COALESCE((SELECT published_at FROM jobs WHERE 'published:'||id=notice_texts.event),?) WHERE created IS NULL",
        (now(),),
    )
    db.commit()


def relevant(db, row):
    if row["state"] != "pending":
        return False
    event = row["event"]
    payload = facts(row["facts"])
    clock = dt.datetime.now(dt.timezone.utc)
    created = dt.datetime.fromisoformat(row["created"])
    state = None
    ongoing = False
    if event.startswith("published:"):
        latest = db.execute(
            "SELECT id,published_at FROM jobs WHERE status='published' ORDER BY published_at DESC LIMIT 1"
        ).fetchone()
        if not latest or event != "published:" + latest["id"]:
            state = "superseded"
        elif (
            clock - dt.datetime.fromisoformat(latest["published_at"])
        ).total_seconds() > 86400:
            state = "expired"
    elif event.startswith(("health:", "missed-post:", "worker-error:")):
        scope = payload.get("scope")
        outage = (
            db.execute(
                "SELECT event FROM health_outages WHERE scope=?", (scope,)
            ).fetchone()
            if scope
            and db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='health_outages'"
            ).fetchone()
            else None
        )
        if payload.get("event") == "workflow_recovered":
            if outage:
                state = "superseded"
        elif not outage or outage["event"] != event:
            state = "superseded"
        elif scope:
            from .health import findings, alert_scopes

            live = alert_scopes(findings(db, config())).get(scope, [])
            saved = facts(
                db.execute(
                    "SELECT facts FROM health_outages WHERE scope=?", (scope,)
                ).fetchone()[0]
            )
            service_pending = any(
                i["kind"] == "service_down" for i in saved.get("issues", [])
            )
            if not live and not service_pending:
                state = "superseded"
            else:
                ongoing = True
    if (
        state is None
        and not event.startswith("published:")
        and not ongoing
        and not payload.get("incident")
        and (clock - created).total_seconds() > 3600
    ):
        state = "expired"
    incident = payload.get("incident")
    if (
        incident
        and not db.execute(
            "SELECT 1 FROM incidents WHERE id=? AND resolved IS NULL", (incident,)
        ).fetchone()
    ):
        state = "superseded"
    if state:
        db.execute(
            "UPDATE notice_texts SET state=? WHERE event=? AND state='pending'",
            (state, event),
        )
        db.commit()
        return False
    return True


def prune(db):
    prepare(db)
    for row in db.execute(
        "SELECT * FROM notice_texts WHERE state='pending'"
    ).fetchall():
        relevant(db, row)


def current_facts(db, row):
    payload = facts(row["facts"])
    payload["occurred_at"] = row["created"]
    payload["observed_at"] = now()
    cfg = config()
    payload["timezone"] = cfg.get("timezone", "UTC")
    if row["event"].startswith("published:"):
        post = db.execute(
            "SELECT published_at FROM jobs WHERE id=?", (row["event"].split(":", 1)[1],)
        ).fetchone()
        if post:
            payload["occurred_at"] = post[0]
    if (
        row["event"].startswith("health:")
        and payload.get("event") != "workflow_recovered"
    ):
        outage = db.execute(
            "SELECT facts FROM health_outages WHERE event=?", (row["event"],)
        ).fetchone()
        if outage:
            payload.update(facts(outage[0]))
    if row["event"].startswith("health:"):
        from .health import publication_context

        payload.update(
            publication_context(
                db, cfg, dt.datetime.fromisoformat(payload["observed_at"])
            )
        )
    zone = ZoneInfo(payload["timezone"])
    for key in ("occurred_at", "observed_at"):
        if payload.get(key):
            payload[key] = (
                dt.datetime.fromisoformat(payload[key]).astimezone(zone).isoformat()
            )
    return json.dumps(payload)
