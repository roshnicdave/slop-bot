import argparse
import datetime as dt
import json
import shutil
import sys
from zoneinfo import ZoneInfo

from .store import ROOT, connect, config, now, worker_lock
from . import providers, content


def make(db, recent=False, slot=None):
    from .production import make as visual_make

    return visual_make(db, slot=slot)


def continue_publication(db, cfg):
    """Complete known containers across window boundaries without fresh submissions."""
    if not cfg["publishing_enabled"] or cfg.get("emergency_pause"):
        return
    from .instagram import publish

    for pending in db.execute(
        "SELECT id FROM jobs WHERE approved=1 AND status='container_created'"
    ).fetchall():
        publish(db, pending["id"])


def tick(db):
    try:
        return _tick(db)
    finally:
        from .health import check

        check(db)


def _tick(db):
    with worker_lock(blocking=False) as locked:
        if not locked:
            return
        from .maintenance import cleanup, backup

        cleanup(db)
        from .telegram import retry_notifications

        retry_notifications(db)
        backup(db)
        from .timing_plan import apply

        apply(db)
        cfg = config()
        if not cfg.get("emergency_pause"):
            from .production import recover

            recover(db)
        local = dt.datetime.now(ZoneInfo(cfg["timezone"]))
        sources = db.execute("SELECT MAX(fetched) FROM sources").fetchone()[0]
        if (
            not sources
            or (
                dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(sources)
            ).total_seconds()
            > 43200
        ):
            try:
                content.refresh_sources(db)
            except Exception:
                pass  # primary-source outage must not block verified queued posts
        research_ok = True
        if cfg.get("generation_enabled") and not cfg.get("emergency_pause"):
            from .scout import daily

            try:
                daily(db)
            except Exception:
                research_ok = False
        if cfg["publishing_enabled"]:
            from .instagram import refresh_token_if_due, insights

            refresh_token_if_due()
            cfg = config()
            marker = ROOT / "data" / "last-insights.txt"
            if cfg["publishing_enabled"] and (
                not marker.exists()
                or (
                    dt.datetime.now(dt.timezone.utc)
                    - dt.datetime.fromisoformat(marker.read_text())
                ).total_seconds()
                > 21600
            ):
                insights(db)
                marker.write_text(now())
        active_slot = any(
            0
            <= (
                local
                - local.replace(
                    hour=int(clock.split(":")[0]),
                    minute=int(clock.split(":")[1]),
                    second=0,
                    microsecond=0,
                )
            ).total_seconds()
            < 3600
            for clock in cfg["slots"][: cfg["posts_per_day"]]
        )
        continue_publication(db, cfg)
        published = [
            dt.datetime.fromisoformat(r[0])
            for r in db.execute(
                "SELECT published_at FROM jobs WHERE published_at IS NOT NULL"
            )
        ]
        today_count = sum(
            p.astimezone(ZoneInfo(cfg["timezone"])).date() == local.date()
            for p in published
        )
        spaced = (
            not published
            or (dt.datetime.now(dt.timezone.utc) - max(published)).total_seconds()
            >= 21600
        )
        uncertain = (
            db.execute(
                'SELECT COUNT(*) FROM jobs WHERE status IN ("publish_unknown","container_submitting")'
            ).fetchone()[0]
            > 0
        )
        if cfg.get("generation_enabled", False) and research_ok:
            slots = cfg["slots"][: cfg["posts_per_day"]]
            for clock in slots:
                hour, minute = map(int, clock.split(":"))
                due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
                # Skip missed days and old slots; do not generate a catch-up burst.
                if not 0 <= (local - due).total_seconds() < 3600:
                    continue
                slot = due.isoformat()
                if db.execute("SELECT 1 FROM jobs WHERE slot=?", (slot,)).fetchone():
                    continue
                if db.execute(
                    "SELECT 1 FROM jobs WHERE approved=1 AND status IN ('rendered','container_created') LIMIT 1"
                ).fetchone():
                    continue
                count = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
                make(db, recent=count % 3 == 2, slot=slot)
                # Next tick will publish, provided approval and connection are ready.
        if (
            cfg["publishing_enabled"]
            and not uncertain
            and active_slot
            and today_count < cfg["posts_per_day"]
            and spaced
        ):
            from .instagram import publish

            for row in db.execute(
                'SELECT id FROM jobs WHERE approved=1 AND status IN ("rendered","container_created") ORDER BY created LIMIT 1'
            ).fetchall():
                publish(db, row["id"])
        from .readiness import ensure

        ensure(db)


def report(db):
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=31)).isoformat()
    reserved = db.execute(
        "SELECT COALESCE(SUM(reserved),0) FROM charges WHERE created>=?", (cutoff,)
    ).fetchone()[0]
    rows = []
    for r in db.execute(
        "SELECT id,status,approved,topic,created FROM jobs ORDER BY created DESC LIMIT 20"
    ):
        job = dict(r)
        charges = [
            dict(x)
            for x in db.execute(
                "SELECT kind,reserved,actual,status,request_id FROM charges WHERE job=?",
                (r["id"],),
            )
        ]
        job["charges"] = charges
        rows.append(job)
    return {
        "budget_usd": config()["monthly_budget_usd"],
        "reserved_31_days_usd": reserved / 1e6,
        "remaining_usd": round(config()["monthly_budget_usd"] - reserved / 1e6, 6),
        "jobs": rows,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Low-cost, source-backed cyber quiz Reels"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("sources")
    sub.add_parser("report")
    sub.add_parser("tick")
    sub.add_parser("insights")
    sub.add_parser("audit")
    sub.add_parser("analyze")
    p = sub.add_parser("make")
    p.add_argument("--recent", action="store_true")
    for command in ["approve", "publish", "render"]:
        p = sub.add_parser(command)
        p.add_argument("job")
    args = parser.parse_args()
    db = connect()
    if args.command == "doctor":
        print(
            json.dumps(
                {
                    "ffmpeg": bool(shutil.which("ffmpeg")),
                    "ffprobe": bool(shutil.which("ffprobe")),
                    "cloudflare_connected": bool(
                        providers.secrets().get("CF_WORKER_URL")
                    ),
                    "paid_providers_enabled": config().get(
                        "paid_providers_enabled", False
                    ),
                    "instagram_connected": bool(
                        providers.secrets().get("IG_ACCESS_TOKEN")
                    ),
                },
                indent=2,
            )
        )

    elif args.command == "sources":
        print(content.refresh_sources(db))
    elif args.command == "make":
        make(db, args.recent)
    elif args.command == "analyze":
        from .learning import analyze

        print(json.dumps(analyze(db), indent=2))
    elif args.command == "report":
        print(json.dumps(report(db), indent=2))
    elif args.command == "audit":
        data = providers.balances()
        p = ROOT / "data" / "latest-usage.json"
        p.write_text(json.dumps(data, indent=2))
        print(str(p))
    elif args.command == "tick":
        tick(db)
    elif args.command == "approve":
        row = db.execute("SELECT status FROM jobs WHERE id=?", (args.job,)).fetchone()
        if not row or row[0] != "rendered":
            raise ValueError("Approve only rendered videos after review")
        db.execute("UPDATE jobs SET approved=1 WHERE id=?", (args.job,))
        db.commit()
        print("Approved " + args.job)
    elif args.command == "render":
        with worker_lock():
            row = db.execute("SELECT * FROM jobs WHERE id=?", (args.job,)).fetchone()
            if (
                not row
                or row["media_id"]
                or row["container_id"]
                or row["status"] not in ("rendered", "rendering", "failed", "voice")
            ):
                raise ValueError("Rerender only unpublished production jobs")
            p = json.loads(row["plan"])
            folder = ROOT / "out" / args.job
            if p.get("visual"):
                if not p.get("quality", {}).get("passed"):
                    raise ValueError("Quality review has not passed")
                from .visual import render
                from .quality import artifact

                path = render(folder)
                p["quality"]["artifact"] = artifact(folder)
                (folder / "plan.json").write_text(json.dumps(p, indent=2))
                (folder / "quality.json").write_text(json.dumps(p["quality"], indent=2))
            else:
                from .render import render

                path = render(folder)
            db.execute(
                "UPDATE jobs SET status=?,plan=? WHERE id=?",
                ("rendered", json.dumps(p), args.job),
            )
            db.commit()
            print(path)
    elif args.command == "publish":
        from .instagram import publish

        print(publish(db, args.job))
    elif args.command == "insights":
        from .instagram import insights

        insights(db)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Keep credentials, provider responses and URLs out of normal service logs.
        print(
            f"Stopped: {type(exc).__name__}: {str(exc) if isinstance(exc, (ValueError, AssertionError, RuntimeError)) else 'see saved job state; no paid retry'}",
            file=sys.stderr,
        )
        sys.exit(1)
