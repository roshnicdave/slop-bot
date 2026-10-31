"""Independent, text-only pipeline health checks and durable owner alerts."""

import datetime as dt
import json
import subprocess
from zoneinfo import ZoneInfo

from .store import connect, config, now


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
                    "SELECT status,error FROM readiness_attempts ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='readiness_attempts'"
                ).fetchone()
                else None
            )
            issues.append(
                {
                    "kind": "queue_empty",
                    "failure": dict(recent) if recent else None,
                }
            )
    if enabled and cfg.get("publishing_enabled"):
        local = clock.astimezone(ZoneInfo(cfg["timezone"]))
        for slot in cfg["slots"][: cfg["posts_per_day"]]:
            hour, minute = map(int, slot.split(":"))
            due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if (local - due).total_seconds() < 3600:
                continue
            end = due + dt.timedelta(hours=1)
            posted = any(
                due <= dt.datetime.fromisoformat(r[0]).astimezone(local.tzinfo) < end
                for r in db.execute(
                    "SELECT published_at FROM jobs WHERE published_at IS NOT NULL"
                )
            )
            if not posted:
                issues.append({"kind": "missed_post", "slot": due.isoformat()})
    for row in db.execute(
        "SELECT component,phase,message FROM incidents WHERE resolved IS NULL"
    ):
        issues.append({"kind": "open_incident", **dict(row)})
    return issues


def check(db, *, services=None):
    from .telegram import notify

    db.execute(
        "CREATE TABLE IF NOT EXISTS health_state(id INTEGER PRIMARY KEY,issues TEXT,changed TEXT)"
    )
    cfg = config()
    current = list(findings(db, cfg, services=services))
    old = db.execute("SELECT issues,changed FROM health_state WHERE id=1").fetchone()
    previous = json.loads(old["issues"]) if old else []
    if services is None:
        current.extend(i for i in previous if i["kind"] == "service_down")
    encoded = json.dumps(current, sort_keys=True)
    if old and old["issues"] == encoded:
        return current
    stamp = now()
    db.execute("INSERT OR REPLACE INTO health_state VALUES(1,?,?)", (encoded, stamp))
    db.commit()
    missed = [i for i in current if i["kind"] == "missed_post"]
    old_missed = {i["slot"] for i in previous if i["kind"] == "missed_post"}
    for issue in missed:
        if issue["slot"] not in old_missed:
            notify(
                db,
                "missed-post:" + issue["slot"],
                json.dumps({"event": "scheduled_post_missed", "slot": issue["slot"]}),
            )
    blockers = [i for i in current if i["kind"] != "missed_post"]
    old_blockers = [i for i in previous if i["kind"] != "missed_post"]
    # Detail changes are stored, but one continuing outage does not need another message.
    if bool(blockers) != bool(old_blockers):
        notify(
            db,
            "health:" + stamp,
            json.dumps(
                {
                    "event": "pipeline_blocked" if blockers else "pipeline_recovered",
                    "issues": blockers,
                }
            ),
        )
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

    retry_notifications(db)
    issues = check(db, services=services)
    if (
        any(i["kind"] == "queue_empty" for i in issues)
        and services["cyberquiz-worker"] == "active"
    ):
        from .wakeup import signal

        signal()
    db.close()


if __name__ == "__main__":
    main()
