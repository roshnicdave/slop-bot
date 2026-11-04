"""A durable visual production task. No paid fallback in the standard path."""

import json
from .store import ROOT, new_job, config, worker_lock
from . import scenarios, scout, cloudflare, content


def make(db, slot=None, scene_key=None, attempt=0):
    with worker_lock():
        return _make(db, slot, scene_key, attempt)


def _make(db, slot=None, scene_key=None, attempt=0):
    cfg = config()
    if cfg.get("emergency_pause"):
        raise ValueError("Pipeline is paused")
    if not cloudflare.available():
        raise ValueError("Cloudflare connection missing; no paid fallback")
    research = scout.daily(db)
    from .experiments import ensure

    ensure(db, research)
    scene = (
        next((s for s in scenarios.bank() if s["key"] == scene_key), None)
        if scene_key
        else scout.choose(db, research)
    )
    if scene is None:
        raise ValueError("Unknown visual scene")
    from . import novelty

    novelty.check(db, scene)
    evidence = content.source_evidence(scene)
    ident = new_job(db, "visual:" + scene["key"], slot)
    folder = ROOT / "out" / ident
    folder.mkdir()
    try:
        p = scenarios.plan(
            scene, {"research_day": research["day"], "ideas": research["ideas"]}, ident
        )
        p["evidence"] = evidence
        p["design_version"] = 3
        p["sound_cues"] = True
        p["narration_speed"] = cfg.get("narration_speed", 1.08)
        p["palette"] = cfg.get("palette", "ink")
        p["hook_strategy"] = cfg.get("hook_strategy", "short diagnostic contrast")
        from .learning import experiment

        p.update(experiment(db, p, ident))
        from .editorial import craft

        p = craft(db, ident, p, research)
        (folder / "plan.json").write_text(json.dumps(p, indent=2))
        db.execute("UPDATE jobs SET plan=? WHERE id=?", (json.dumps(p), ident))
        db.commit()
        novelty.record(db, ident, p)
        from .editorial import review_opening

        p, quality = review_opening(db, ident, p, research)
        (folder / "quality.json").write_text(json.dumps(quality, indent=2))
        p["quality"] = quality
        (folder / "plan.json").write_text(json.dumps(p, indent=2))
        db.execute(
            "UPDATE jobs SET plan=?,status=? WHERE id=?",
            (json.dumps(p), "voice", ident),
        )
        db.commit()
        if not quality["passed"]:
            db.execute('UPDATE jobs SET status="held_quality" WHERE id=?', (ident,))
            db.commit()
            if attempt < 1:
                return make(db, slot=(slot + ":fallback") if slot else None, attempt=1)
            return ident
        if cfg.get("voice_provider") == "elevenlabs":
            from .premium_voice import preflight

            preflight(db, [p[k] for k in ("intro", "reveal_voice", "fix_voice")])
        for label in ["intro", "reveal_voice", "fix_voice"]:
            if cfg.get("voice_provider") == "elevenlabs":
                from .premium_voice import generate

                generate(
                    db,
                    ident,
                    label,
                    p[label],
                    cfg.get("premium_voice_speaker", "Chris"),
                    folder / (label + ".wav"),
                )
            else:
                cloudflare.voice(db, ident, label, p[label], folder / (label + ".wav"))
        db.execute('UPDATE jobs SET status="rendering" WHERE id=?', (ident,))
        db.commit()
        from .visual import render

        render(folder)
        from .quality import artifact

        quality["artifact"] = artifact(folder)
        (folder / "quality.json").write_text(json.dumps(quality, indent=2))
        p["quality"] = quality
        db.execute("UPDATE jobs SET plan=? WHERE id=?", (json.dumps(p), ident))
        db.commit()
        db.execute(
            'UPDATE jobs SET status="rendered",error=NULL,approved=? WHERE id=?',
            (int(not cfg["require_approval"]), ident),
        )
        db.commit()
        return ident
    except BaseException as exc:
        from .incidents import record

        phase = db.execute("SELECT status FROM jobs WHERE id=?", (ident,)).fetchone()[0]
        detail = type(exc).__name__ + (
            ": " + str(exc)[:240] if isinstance(exc, (ValueError, RuntimeError)) else ""
        )
        record(db, "production", phase, None, detail, ident)
        db.execute(
            'UPDATE jobs SET status="failed",error=? WHERE id=?',
            (detail, ident),
        )
        db.commit()
        raise


def resume(db, ident):
    with worker_lock():
        return _resume(db, ident)


def _resume(db, ident):
    row = db.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
    if not row or not row["plan"]:
        raise ValueError("No saved visual plan")
    if (
        row["status"] not in ("voice", "rendering", "failed")
        or row["container_id"]
        or row["media_id"]
    ):
        raise ValueError("Only interrupted unpublished production may resume")
    p = json.loads(row["plan"])
    scenarios.validate(p)
    if not p.get("quality", {}).get("passed"):
        raise ValueError("Saved job has not passed automatic editorial checks")
    folder = ROOT / "out" / ident
    for label in ["intro", "reveal_voice", "fix_voice"]:
        if config().get("voice_provider") == "elevenlabs":
            from .premium_voice import generate

            generate(
                db,
                ident,
                label,
                p[label],
                config().get("premium_voice_speaker", "Chris"),
                folder / (label + ".wav"),
            )
        else:
            cloudflare.voice(db, ident, label, p[label], folder / (label + ".wav"))
    from .visual import render

    render(folder)
    from .quality import artifact

    p["quality"]["artifact"] = artifact(folder)
    (folder / "quality.json").write_text(json.dumps(p["quality"], indent=2))
    (folder / "plan.json").write_text(json.dumps(p, indent=2))
    db.execute(
        'UPDATE jobs SET status="rendered",error=NULL,plan=?,approved=? WHERE id=?',
        (json.dumps(p), int(not config()["require_approval"]), ident),
    )
    db.commit()
    from .incidents import resolve

    resolve(db, "production", job=ident)
    return ident


def recover(db):
    """Resume saved safe steps; hold an uncertain provider result without replay."""
    from .telegram import notify

    for row in db.execute(
        'SELECT id,plan FROM jobs WHERE status IN ("voice","rendering") ORDER BY created LIMIT 1'
    ).fetchall():
        ident = row["id"]
        p = json.loads(row["plan"] or "{}")
        if not p.get("quality", {}).get("passed"):
            continue
        folder = ROOT / "out" / ident
        uncertain = False
        for label in ("intro", "reveal_voice", "fix_voice"):
            if not (folder / (label + ".wav")).exists():
                if (
                    db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='cf_calls'"
                    ).fetchone()
                    and db.execute(
                        "SELECT 1 FROM cf_calls WHERE operation=?",
                        (ident + ":voice:" + label,),
                    ).fetchone()
                ):
                    uncertain = True
        if uncertain:
            db.execute('UPDATE jobs SET status="held_provider" WHERE id=?', (ident,))
            db.commit()
            notify(
                db,
                "provider-hold:" + ident,
                json.dumps(
                    {
                        "event": "voice_outcome_unknown",
                        "content_type": "Instagram Reel",
                        "question": json.loads(row["plan"] or "{}").get("question"),
                        "request_retried": False,
                    }
                ),
            )
        else:
            resume(db, ident)


def refresh_visuals(db, job=None):
    """Upgrade unsubmitted queued media using its existing narration, never a paid call."""
    from .lab_visual import VERSION
    from .quality import layout, artifact
    from .visual import render

    with worker_lock():
        rows = db.execute(
            "SELECT * FROM jobs WHERE status='rendered' AND approved=1"
            + (" AND id=?" if job else ""),
            (job,) if job else (),
        ).fetchall()
        for row in rows:
            p = json.loads(row["plan"] or "{}")
            if (
                p.get("diagram", {}).get("kind") != "config"
                or p.get("quality", {})
                .get("artifact", {})
                .get("diagram_renderer_version", 0)
                >= VERSION
            ):
                continue
            if row["container_id"] or row["media_id"]:
                raise ValueError(
                    "Submitted media needs reconciliation before its visual can change"
                )
            folder = ROOT / "out" / row["id"]
            try:
                scenarios.validate(p)
                layout(p)
                if not all(
                    (folder / (name + ".wav")).exists()
                    for name in ("intro", "reveal_voice", "fix_voice")
                ):
                    raise ValueError("Saved narration unavailable for visual refresh")
                db.execute(
                    "UPDATE jobs SET approved=0,status='rendering' WHERE id=?",
                    (row["id"],),
                )
                db.commit()
                render(folder)
                p["quality"]["artifact"] = artifact(folder)
                (folder / "plan.json").write_text(json.dumps(p, indent=2))
                (folder / "quality.json").write_text(json.dumps(p["quality"], indent=2))
                db.execute(
                    "UPDATE jobs SET plan=?,approved=1,status='rendered',error=NULL WHERE id=?",
                    (json.dumps(p), row["id"]),
                )
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='telegram_media'"
                ).fetchone():
                    db.execute("DELETE FROM telegram_media WHERE job=?", (row["id"],))
                db.commit()
            except Exception as exc:
                db.execute(
                    "UPDATE jobs SET approved=0,status='held_quality',error=? WHERE id=?",
                    (
                        "Visual refresh: " + type(exc).__name__ + ": " + str(exc)[:160],
                        row["id"],
                    ),
                )
                db.commit()
                raise
