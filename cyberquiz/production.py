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
        from .quality import review

        quality = review(db, ident, p)
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
            from .telegram import notify

            if attempt < 1:
                return make(db, slot=(slot + ":fallback") if slot else None, attempt=1)
            notify(
                db,
                "quality:" + ident,
                "Skipped "
                + ident
                + ": both candidate drafts failed quality checks. I’ll try another concept next run.",
            )
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
                "Held "
                + ident
                + ": a voice request has an unknown result. No duplicate request was sent.",
            )
        else:
            resume(db, ident)
