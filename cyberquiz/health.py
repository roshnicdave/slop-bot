"""Independent, text-only pipeline health checks and durable owner alerts."""

import datetime as dt
import json
import subprocess
from zoneinfo import ZoneInfo

from .store import connect, config, now


def publication_context(db, cfg, clock=None):
    """Delivery-time facts, counted and displayed in the operator's local day."""
    clock = clock or dt.datetime.now(dt.timezone.utc)
    zone = ZoneInfo(cfg["timezone"])
    published = [
        dt.datetime.fromisoformat(r[0])
        for r in db.execute(
            "SELECT published_at FROM jobs WHERE published_at IS NOT NULL"
        )
    ]
    from .schedule import next_post_at

    due = next_post_at(cfg, published, clock)
    completed = sum(
        p.astimezone(zone).date() == clock.astimezone(zone).date() for p in published
    )
    return {
        "local_date": clock.astimezone(zone).date().isoformat(),
        "confirmed_posts_today": completed,
        "daily_target": cfg["posts_per_day"],
        "daily_target_met": completed >= cfg["posts_per_day"],
        "last_published_at": max(published).astimezone(zone).isoformat()
        if published
        else None,
        "ready_reels": db.execute(
            "SELECT count(*) FROM jobs WHERE approved=1 AND status IN ('rendered','container_created')"
        ).fetchone()[0],
        "next_post_at": due.astimezone(zone).isoformat() if due else None,
        "timezone": cfg["timezone"],
    }


def findings(db, cfg, clock=None, services=None):
    clock = clock or dt.datetime.now(dt.timezone.utc)
    issues = []
    if services:
        for service, state in services.items():
            if state != "active":
                issues.append(
                    {"kind": "service_down", "service": service, "state": state}
                )
    enabled = not cfg.get("emergency_pause")
    if enabled and cfg.get("generation_enabled"):
        ready = db.execute(
            "SELECT 1 FROM jobs WHERE approved=1 AND status IN ('rendered','container_created') LIMIT 1"
        ).fetchone()
        active = db.execute(
            "SELECT 1 FROM jobs WHERE status IN ('drafting','voice','rendering') LIMIT 1"
        ).fetchone()
        if not ready and not active:
            recent = (
                db.execute(
                    "SELECT * FROM readiness_attempts ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='readiness_attempts'"
                ).fetchone()
                else None
            )
            context = publication_context(db, cfg, clock)
            due = context["next_post_at"]
            preparation_due = (
                due is not None
                and (dt.datetime.fromisoformat(due) - clock).total_seconds()
                <= cfg.get("buffer_warning_lead_minutes", 120) * 60
            )
            # Consuming a completed buffer is normal. Warn about an actual
            # unsuccessful refill or an approaching unprepared publication.
            failed = recent and (
                recent["status"] not in ("complete", "started") or recent["error"]
            )
            if failed and "created" in recent.keys() and context["last_published_at"]:
                failed = dt.datetime.fromisoformat(
                    recent["created"]
                ) > dt.datetime.fromisoformat(context["last_published_at"])
            issues.append(
                {
                    "kind": "queue_empty",
                    "failure": {k: recent[k] for k in ("status", "error")}
                    if recent
                    else None,
                    "actionable": bool(preparation_due or failed),
                }
            )
    if enabled and cfg.get("publishing_enabled"):
        local = clock.astimezone(ZoneInfo(cfg["timezone"]))
        published = [
            dt.datetime.fromisoformat(r[0])
            for r in db.execute(
                "SELECT published_at FROM jobs WHERE published_at IS NOT NULL"
            )
        ]
        completed = sum(
            p.astimezone(local.tzinfo).date() == local.date() for p in published
        )
        from .schedule import next_post_at

        next_due = next_post_at(cfg, published, clock)
        for index, slot in enumerate(cfg["slots"][: cfg["posts_per_day"]]):
            if index < completed or (next_due and clock < next_due):
                continue
            hour, minute = map(int, slot.split(":"))
            due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if (local - due).total_seconds() < 3600:
                continue
            issues.append({"kind": "missed_post", "slot": due.isoformat()})
    for row in db.execute(
        "SELECT component,phase,message FROM incidents WHERE resolved IS NULL"
    ):
        issues.append({"kind": "open_incident", **dict(row)})
    return issues


def alert_scopes(issues):
    """A chat error is not a publishing outage; a refill is not a failed post."""
    groups = {"publishing": [], "content": [], "chat": []}
    empty = any(
        i["kind"] == "queue_empty" and i.get("actionable", True) for i in issues
    )
    missed = any(i["kind"] == "missed_post" for i in issues)
    for issue in issues:
        kind = issue["kind"]
        if kind == "missed_post":
            groups["publishing"].append(issue)
        elif kind == "queue_empty":
            if issue.get("actionable", True) or missed:
                groups["publishing" if missed else "content"].append(issue)
        elif kind == "service_down":
            groups[
                "publishing" if issue["service"] == "cyberquiz-worker" else "chat"
            ].append(issue)
        elif kind == "open_incident":
            component = issue["component"]
            if component in ("conversation", "telegram"):
                groups["chat"].append(issue)
            elif component in ("instagram", "auth"):
                groups["publishing"].append(issue)
            elif empty and component in (
                "research",
                "readiness",
                "production",
                "worker",
            ):
                groups["publishing" if missed else "content"].append(issue)
    return groups


def check(db, *, services=None):
    from .telegram import notify, tables
    from .notice_policy import prepare, prune

    tables(db)
    prepare(db)
    db.execute(
        "CREATE TABLE IF NOT EXISTS health_state(id INTEGER PRIMARY KEY,issues TEXT,changed TEXT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS health_outages(scope TEXT PRIMARY KEY,since TEXT,event TEXT,facts TEXT)"
    )
    cfg = config()
    current = list(findings(db, cfg, services=services))
    old = db.execute("SELECT issues FROM health_state WHERE id=1").fetchone()
    previous = json.loads(old[0]) if old else []
    if services is None:
        current.extend(i for i in previous if i["kind"] == "service_down")
    stamp = now()
    clock = dt.datetime.fromisoformat(stamp)
    db.execute(
        "INSERT OR REPLACE INTO health_state VALUES(1,?,?)",
        (json.dumps(current, sort_keys=True), stamp),
    )
    context = publication_context(db, cfg, clock)
    due = (
        dt.datetime.fromisoformat(context["next_post_at"])
        if context["next_post_at"]
        else None
    )
    db.commit()
    for scope, issues in alert_scopes(current).items():
        prior = db.execute(
            "SELECT * FROM health_outages WHERE scope=?", (scope,)
        ).fetchone()
        if not issues:
            if prior:
                prior_issues = json.loads(prior["facts"])["issues"]
                # Retire legacy false alarms without following them with an
                # equally misleading "recovered" message. Keep sent receipts.
                obsolete_buffer_alarm = scope == "content" and all(
                    i["kind"] == "queue_empty"
                    and isinstance(i.get("failure"), dict)
                    and i["failure"].get("status") == "complete"
                    and not i["failure"].get("error")
                    for i in prior_issues
                )
                delivered = db.execute(
                    "SELECT 1 FROM notices WHERE event=? AND status='sent'",
                    (prior["event"],),
                ).fetchone()
                db.execute("DELETE FROM health_outages WHERE scope=?", (scope,))
                if obsolete_buffer_alarm:
                    db.execute(
                        "UPDATE notice_texts SET state='superseded' WHERE event=?",
                        (prior["event"],),
                    )
                db.commit()
                prune(db)
                if delivered and not obsolete_buffer_alarm:
                    notify(
                        db,
                        "health:" + scope + ":recovered:" + stamp,
                        json.dumps(
                            {
                                "event": "workflow_recovered",
                                "scope": scope,
                                "resolved_issues": prior_issues,
                                **context,
                            }
                        ),
                    )
            continue
        event = prior["event"] if prior else "health:" + scope + ":" + stamp
        since = prior["since"] if prior else stamp
        payload = json.dumps(
            {
                "event": "buffer_needs_attention"
                if scope == "content"
                else "workflow_delayed",
                "scope": scope,
                "issues": issues,
                **context,
            }
        )
        db.execute(
            "INSERT OR REPLACE INTO health_outages VALUES(?,?,?,?)",
            (scope, since, event, payload),
        )
        if prior and prior["facts"] != payload:
            db.execute(
                "UPDATE notice_texts SET facts=?,text=NULL WHERE event=? AND state='pending'",
                (payload, event),
            )
        db.commit()
        urgent = scope == "publishing" or (
            scope == "content" and due is not None and due <= clock
        )
        delivered = db.execute(
            "SELECT 1 FROM notices WHERE event=?", (event,)
        ).fetchone()
        if not delivered and (
            urgent or (clock - dt.datetime.fromisoformat(since)).total_seconds() >= 600
        ):
            notify(db, event, payload)
    prune(db)
    return current


def main():
    db = connect()
    services = {}
    for service in ("cyberquiz-worker", "cyberquiz-conversation", "cyberquiz-telegram"):
        result = subprocess.run(
            ["systemctl", "is-active", service], capture_output=True, text=True
        )
        services[service] = result.stdout.strip()
    from .telegram import retry_notifications

    issues = check(db, services=services)
    retry_notifications(db)
    if (
        any(i["kind"] == "queue_empty" for i in issues)
        and services["cyberquiz-worker"] == "active"
    ):
        from .wakeup import signal

        signal()
    db.close()


if __name__ == "__main__":
    main()
