"""A durable visual production task. No paid fallback in the standard path."""

import json
import copy
import datetime as dt
from .store import ROOT, new_job, config, worker_lock
from . import scenarios, scout, cloudflare, content

VOICE_SEGMENTS = ("intro", "reveal_voice", "fix_voice")


def narration_started(db, job, labels):
    cloudflare_ledger = db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='cf_calls'"
    ).fetchone()
    return any(
        db.execute(
            "SELECT 1 FROM charges WHERE job=? AND kind IN (?,?)",
            (job, "premium_voice:" + label, "fish_voice:" + label),
        ).fetchone()
        or (
            cloudflare_ledger
            and db.execute(
                "SELECT 1 FROM cf_calls WHERE operation=?", (job + ":voice:" + label,)
            ).fetchone()
        )
        for label in labels
    )


def narrate(db, job, p, folder, cfg):
    segments = [
        (label, p[label], folder / (label + ".wav")) for label in VOICE_SEGMENTS
    ]
    missing = [item for item in segments if not item[2].is_file()]
    if not missing:
        return
    provider = p.get("voice_provider", cfg.get("voice_provider"))
    if provider == "fish":
        from .fish_voice import narrate as fish_narrate

        if "voice_provider" not in p and (
            len(missing) != len(segments) or narration_started(db, job, VOICE_SEGMENTS)
        ):
            raise ValueError("Saved narration must finish with its original voice")
        fish_narrate(
            db,
            job,
            p.get("fish_voice_reference_id", cfg.get("fish_voice_reference_id")),
            missing,
            cfg,
        )
    elif provider == "elevenlabs":
        from .premium_voice import generate, preflight

        if len(missing) == len(segments):
            preflight(db, [script for _, script, _ in missing])
        for label, script, path in missing:
            generate(
                db, job, label, script, cfg.get("premium_voice_speaker", "Chris"), path
            )
    else:
        for label, script, path in missing:
            cloudflare.voice(db, job, label, script, path)


def make(db, slot=None, scene_key=None, attempt=0):
    with worker_lock():
        return _make(db, slot, scene_key, attempt)


def _make(db, slot=None, scene_key=None, attempt=0):
    cfg = config()
    if cfg.get("emergency_pause"):
        raise ValueError("Pipeline is paused")
    if not cloudflare.available():
        raise ValueError("Cloudflare connection missing; no paid fallback")
    try:
        research = scout.daily(db)
    except Exception:
        research = {
            "day": dt.datetime.now(dt.timezone.utc).date().isoformat(),
            "ideas": [],
            "evidence": {},
            "research_deferred": True,
        }
    from .experiments import ensure

    try:
        ensure(db, research)
    except Exception as exc:
        # An optional experiment proposal is not a prerequisite for a Reel.
        db.execute(
            "INSERT OR IGNORE INTO experiment_decisions VALUES(?,?)",
            (
                dt.datetime.now(dt.timezone.utc).date().isoformat(),
                json.dumps(
                    {"hold_reason": "Proposal unavailable", "error": type(exc).__name__}
                ),
            ),
        )
        db.commit()
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
    if scene["family"] == "source-grounded":
        db.execute(
            "UPDATE source_attempts SET status='claimed' WHERE id=?", (scene["key"],)
        )
        db.commit()
    folder = ROOT / "out" / ident
    folder.mkdir()
    try:
        from .quality import REVIEW_VERSION, layout

        ready = scene.get("ready_plan", {})
        prepared = (
            ready.get("quality", {}).get("passed")
            and ready.get("quality", {}).get("review_version") == REVIEW_VERSION
        )
        p = (
            copy.deepcopy(ready)
            if prepared
            else scenarios.plan(
                {k: v for k, v in scene.items() if k != "ready_plan"},
                {"research_day": research["day"], "ideas": research["ideas"]},
                ident,
            )
        )
        p["id"] = ident
        p["account"] = cfg["account"]
        p["evidence"] = evidence
        from .visual import PRESENTATION_VERSION

        p["design_version"] = PRESENTATION_VERSION
        p["sound_cues"] = True
        p["narration_speed"] = cfg.get("narration_speed", 1.08)
        p["palette"] = cfg.get("palette", "ink")
        if cfg.get("reel_mascot"):
            p["reel_mascot"] = True
        elif crop := cfg.get("reel_badge_crop"):
            p["reel_badge_crop"] = crop
        p["countdown_style"] = cfg.get("countdown_style", "dial")
        p["tick_level_dbfs"] = cfg.get("tick_level_dbfs", -24)
        authored_hook = p.get("hook_strategy", "short diagnostic contrast")
        p["hook_strategy"] = cfg.get("hook_strategy", "short diagnostic contrast")
        from .learning import experiment

        p.update(experiment(db, p, ident))
        from .editorial import craft

        hook_changed = p.get("hook_strategy") != authored_hook
        craft_research = research
        if hook_changed:
            craft_research = {
                **research,
                "editorial_feedback": {
                    "issues": [
                        "Apply the assigned hook strategy while preserving the verified scenario."
                    ]
                },
            }
        if not prepared or hook_changed:
            original_question = p["question"]
            p = craft(db, ident, p, craft_research)
            if p["question"] != original_question:
                prepared = False  # A changed opening needs a fresh blind review.
            elif hook_changed:
                # An unchanged title is not evidence that a challenger was applied.
                if p.get("experiment", {}).get("parameter") == "hook_strategy":
                    p.pop("experiment", None)
                p["hook_strategy"] = authored_hook
        (folder / "plan.json").write_text(json.dumps(p, indent=2))
        db.execute("UPDATE jobs SET plan=? WHERE id=?", (json.dumps(p), ident))
        db.commit()
        novelty.record(db, ident, p)
        from .editorial import review_opening

        if prepared:
            scenarios.validate(p)
            layout(p)
            quality = p["quality"]
        else:
            p, quality = review_opening(db, ident, p, research)
        from .captions import caption

        p["caption"] = caption(p)  # Also refresh older, fully reviewed text reserves.
        p["voice_provider"] = cfg.get("voice_provider", "cloudflare")
        if p["voice_provider"] == "fish":
            p["fish_voice_reference_id"] = cfg.get("fish_voice_reference_id")
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
                try:
                    return make(
                        db, slot=(slot + ":fallback") if slot else None, attempt=1
                    )
                except ValueError as exc:
                    if "No sufficiently novel verified candidate" not in str(exc):
                        raise
                    # Keep the original review outcome rather than relabeling a
                    # held draft as a failed production with no associated job.
                    return ident
            return ident
        from .visual import preview, render

        preview(p, folder)
        narrate(db, ident, p, folder, cfg)
        db.execute('UPDATE jobs SET status="rendering" WHERE id=?', (ident,))
        db.commit()
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
        try:
            (ROOT / "data" / "research-wake").touch()
        except OSError:
            pass  # The periodic research timer is the fallback.
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
    narrate(db, ident, p, folder, config())
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
        missing = [
            label
            for label in VOICE_SEGMENTS
            if not (folder / (label + ".wav")).is_file()
        ]
        if narration_started(db, ident, missing):
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
    from .quality import layout, artifact, review, REVIEW_VERSION
    from .visual import render, PRESENTATION_VERSION

    with worker_lock():
        rows = db.execute(
            "SELECT * FROM jobs WHERE status='rendered' AND approved=1"
            + (" AND id=?" if job else ""),
            (job,) if job else (),
        ).fetchall()
        for row in rows:
            p = json.loads(row["plan"] or "{}")
            if not p.get("visual"):
                continue
            try:
                layout(p)
            except ValueError as exc:
                if row["container_id"] or row["media_id"]:
                    continue
                db.execute(
                    "UPDATE jobs SET status='held_quality',approved=0,error=? WHERE id=?",
                    (str(exc), row["id"]),
                )
                db.commit()
                continue
            if (
                p.get("quality", {}).get("review_version") != REVIEW_VERSION
                and not row["container_id"]
                and not row["media_id"]
            ):
                try:
                    revised = review(
                        db, row["id"] + ":policy:" + str(REVIEW_VERSION), p
                    )
                except ValueError as exc:
                    revised = {
                        "passed": False,
                        "review_version": REVIEW_VERSION,
                        "editorial": {"issues": [str(exc)]},
                    }
                revised["artifact"] = p.get("quality", {}).get("artifact", {})
                p["quality"] = revised
                if not revised["passed"]:
                    db.execute(
                        "UPDATE jobs SET status='held_quality',approved=0,plan=?,error=? WHERE id=?",
                        (
                            json.dumps(p),
                            "Current editorial review rejected: "
                            + str(revised.get("editorial", {}).get("issues", []))[:240],
                            row["id"],
                        ),
                    )
                    db.commit()
                    continue
                db.execute(
                    "UPDATE jobs SET plan=? WHERE id=?", (json.dumps(p), row["id"])
                )
                db.commit()
            saved = p.get("quality", {}).get("artifact", {})
            old_diagram = (
                p.get("diagram", {}).get("kind") == "config"
                and saved.get("diagram_renderer_version", 0) < VERSION
            )
            old_presentation = (
                saved.get("presentation_version", 0) < PRESENTATION_VERSION
            )
            if not (old_diagram or old_presentation):
                continue
            if row["container_id"] or row["media_id"]:
                continue  # Meta may already be consuming this exact media file.
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
                p["design_version"] = PRESENTATION_VERSION
                p["countdown_style"] = p.get(
                    "countdown_style", config().get("countdown_style", "dial")
                )
                p["tick_level_dbfs"] = p.get(
                    "tick_level_dbfs", config().get("tick_level_dbfs", -24)
                )
                (folder / "plan.json").write_text(json.dumps(p, indent=2))
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
