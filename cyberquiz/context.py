"""Read-only operational queries available to the conversational orchestrator."""

import json
from .store import config, now, ROOT

CATALOG = {
    "queue": "Ready/published job counts, recent jobs and current production stages.",
    "preferences": "Persisted operator advice with IDs, timestamps and how production uses it.",
    "activity": "Queued/running operator work, recent outcomes and readiness refill attempts.",
    "research": "Latest topic-wide Reel discovery, sampled visual findings, and primary-source editorial research.",
    "experiments": "Current content experiments and recorded outcomes.",
    "budget": "Live paid reservations and free quota accounting.",
}


def rows(db, table, sql, params=()):
    if not db.execute(
        'SELECT 1 FROM sqlite_master WHERE type="table" AND name=?', (table,)
    ).fetchone():
        return []
    return [dict(r) for r in db.execute(sql, params).fetchall()]


def read(db, resource):
    if resource not in CATALOG:
        raise ValueError("Unknown read resource")
    if resource == "queue":
        jobs = rows(
            db,
            "jobs",
            "SELECT id,status,approved,created,published_at FROM jobs WHERE status IN ('drafting','voice','rendering','container_submitting','container_created','publish_unknown') ORDER BY created DESC LIMIT 8",
        )
        ready = rows(
            db,
            "jobs",
            "SELECT id,created,plan FROM jobs WHERE approved=1 AND status IN ('rendered','container_created') ORDER BY created LIMIT 3",
        )
        published = rows(
            db, "jobs",
            "SELECT id,published_at,plan FROM jobs WHERE status='published' ORDER BY published_at DESC LIMIT 2",
        )
        for item in ready + published:
            plan = json.loads(item.pop("plan") or "{}")
            item.update(
                {key: plan.get(key) for key in ("question", "topic", "explanation")}
            )
        return {
            "ready_count": db.execute(
                "SELECT COUNT(*) FROM jobs WHERE approved=1 AND status IN ('rendered','container_created')"
            ).fetchone()[0],
            "published_total": db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='published'"
            ).fetchone()[0],
            "published": published,
            "recent_jobs": jobs,
            "ready": ready,
        }
    if resource == "preferences":
        return {
            "saved": rows(
                db,
                "preferences",
                "SELECT id,user_id,text,created FROM preferences ORDER BY id DESC LIMIT 8",
            ),
            "storage": "SQLite preferences table on AWS; persisted across restarts. Daily research reads the latest preference and script drafting reads the latest eight. Advice guides later candidates; it does not rewrite already rendered videos.",
        }
    if resource == "activity":
        return {
            "active": rows(
                db,
                "telegram_updates",
                "SELECT id,status,command FROM telegram_updates WHERE status IN ('queued','running') ORDER BY id LIMIT 5",
            ),
            "execution_receipts": rows(
                db,
                "action_receipts",
                "SELECT action,phase,result,created FROM action_receipts ORDER BY created DESC LIMIT 5",
            ),
            "work_results": rows(
                db,
                "telegram_updates",
                "SELECT id,status,command,result FROM telegram_updates WHERE command LIKE '/%' ORDER BY id DESC LIMIT 5",
            ),
            "publication_requests": rows(
                db,
                "operator_requests",
                "SELECT id,job,created FROM operator_requests ORDER BY created DESC LIMIT 3",
            ),
            "job_history": rows(
                db,
                "job_events",
                "SELECT job,previous_status,status,previous_error,error,observed FROM job_events ORDER BY id DESC LIMIT 8",
            ),
            "incidents": rows(
                db,
                "incidents",
                "SELECT component,phase,code,message,job,opened,resolved,state FROM incidents ORDER BY opened DESC LIMIT 8",
            ),
            "historical_job_errors": rows(
                db,
                "jobs",
                "SELECT id,status,error,created FROM jobs WHERE error IS NOT NULL ORDER BY created DESC LIMIT 5",
            ),
            "recent_outcomes": rows(
                db,
                "chat_turns",
                "SELECT request,reply,action,created FROM chat_turns ORDER BY update_id DESC LIMIT 5",
            ),
            "refill": rows(
                db,
                "readiness_attempts",
                "SELECT * FROM readiness_attempts ORDER BY id DESC LIMIT 3",
            ),
        }
    if resource == "research":
        paths = sorted((ROOT / "data" / "research").glob("*-v2.json"))
        latest = json.loads(paths[-1].read_text()) if paths else {}
        from .social_signals import analyze
        from .trends import brief as trend_brief

        return {
            "topic_wide_reel_discovery": trend_brief(db),
            "social_observations": analyze(db),
            "day": latest.get("day"),
            "ideas": latest.get("ideas", [])[:2],
            "limitations": latest.get("limitations"),
            "discovery": rows(
                db,
                "source_attempts",
                "SELECT day,source_url,status FROM source_attempts ORDER BY rowid DESC LIMIT 4",
            ),
        }
    if resource == "experiments":
        return rows(
            db,
            "experiments",
            "SELECT id,state,parameter,hypothesis,outcome FROM experiments ORDER BY created DESC LIMIT 3",
        )
    from .telegram import status_text

    return status_text(db, True)


def snapshot(db):
    cfg = config()
    queue = read(db, "queue")
    marker = ROOT / "data" / "meta-auth-health.json"
    auth = json.loads(marker.read_text()) if marker.exists() else {}
    blockers = []
    if cfg.get("emergency_pause"):
        blockers.append("emergency_pause")
    if not cfg.get("publishing_enabled"):
        blockers.append("publishing_disabled")
    if auth.get("valid") is False:
        blockers.append("instagram_access_invalid")
    if db.execute(
        "SELECT 1 FROM jobs WHERE status IN ('publish_unknown','container_submitting')"
    ).fetchone():
        blockers.append("publication_outcome_unknown")
    if queue["ready_count"] == 0:
        blockers.append("no_staged_reel")
    return {
        "observed_at": now(),
        "current_publication_blockers": blockers,
        "open_incidents": rows(
            db,
            "incidents",
            "SELECT component,phase,code,message,job,opened FROM incidents WHERE resolved IS NULL ORDER BY opened DESC LIMIT 5",
        ),
        "schedule": {
            "timezone": cfg.get("timezone"),
            "slots": cfg.get("slots"),
            "posts_per_day": cfg.get("posts_per_day"),
        },
        "instagram_access": {k: auth.get(k) for k in ("valid", "reason", "checked_at")},
        "generation_enabled": cfg.get("generation_enabled"),
        "publishing_enabled": cfg.get("publishing_enabled"),
        "emergency_pause": cfg.get("emergency_pause"),
        "readiness_policy": {
            "target_ready": 1,
            "refill": "After consumption, on worker wakes; subject to budget, quality, novelty, daily attempt cap and failure backoff.",
        },
        "queue": queue,
        "activity": {
            "active": read(db, "activity")["active"],
            "refill": read(db, "activity")["refill"],
        },
        "latest_preferences": read(db, "preferences")["saved"][:3],
        "preference_storage_and_use": read(db, "preferences")["storage"],
    }
