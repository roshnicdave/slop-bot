"""Private design refinement: reuse purchased speech when only visuals change."""

import json
import subprocess
from .store import ROOT, connect, new_job, worker_lock, config
from .providers import download
from .premium_voice import generate
from .quality import review, artifact
from .visual import render
from .telegram import video


def clone(db, base, palette, scripts=None):
    original = db.execute("SELECT plan FROM jobs WHERE id=?", (base,)).fetchone()
    if not original:
        raise ValueError("Preview not found")
    p = json.loads(original[0])
    job = new_job(db, "private-refinement:" + p["key"])
    folder = ROOT / "out" / job
    folder.mkdir()
    p.update(
        id=job,
        palette=palette,
        narration_speed=config().get("narration_speed", 1.08),
        voice_speaker="Chris",
    )
    if p["family"] == "visual-vlan":
        p["question"] = "Green links. No ping.\nWhat's blocking it?"
    if scripts:
        p.update(
            question="Which host gets\nthis login request?",
            clue="",
            intro=scripts[0],
            reveal_voice=scripts[1],
            fix_voice=scripts[2],
        )
        p["outro"] = p["reveal_voice"] + " " + p["fix_voice"]
        p["quality"] = review(db, job, p)
        if not p["quality"]["passed"]:
            raise ValueError("Refinement failed factual review")
    db.execute(
        'UPDATE jobs SET status="preview",approved=0,plan=? WHERE id=?',
        (json.dumps(p), job),
    )
    db.commit()
    (folder / "plan.json").write_text(json.dumps(p, indent=2))
    for label in ("intro", "reveal_voice", "fix_voice"):
        target = folder / (label + ".wav")
        if scripts:
            generate(db, job, label, p[label], "Chris", target)
        else:
            charge = db.execute(
                'SELECT result FROM charges WHERE job=? AND kind=? AND status="complete"',
                (base, "preview_voice:" + label),
            ).fetchone()
            if not charge:
                raise ValueError("No completed speech to reuse")
            raw = target.with_suffix(".mp3")
            download(json.loads(charge[0])["audio"]["url"], raw)
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(raw),
                    "-ar",
                    "24000",
                    "-ac",
                    "1",
                    str(target),
                ],
                check=True,
            )
            raw.unlink()
            p["reused_voice_from"] = base
    (folder / "plan.json").write_text(json.dumps(p, indent=2))
    render(folder)
    p["quality"]["artifact"] = artifact(folder)
    (folder / "plan.json").write_text(json.dumps(p, indent=2))
    (folder / "quality.json").write_text(json.dumps(p["quality"], indent=2))
    db.execute("UPDATE jobs SET plan=? WHERE id=?", (json.dumps(p), job))
    db.commit()
    video(config()["telegram_owner_user_id"], job)
    return {"job": job, "palette": palette, "quality": p["quality"]["artifact"]}


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("base")
    parser.add_argument("--palette", choices=("ink", "paper"), default="ink")
    parser.add_argument("--short-url", action="store_true")
    args = parser.parse_args()
    db = connect()
    scripts = None
    if args.short_url:
        p = json.loads(
            db.execute("SELECT plan FROM jobs WHERE id=?", (args.base,)).fetchone()[0]
        )
        scripts = (
            "Which host gets this request? Comment your answer.",
            "ABCD"[p["correct"]]
            + ". The host is login dot example dot com dot evil dot test.",
            "The familiar name is just a subdomain.",
        )
    with worker_lock():
        print(json.dumps(clone(db, args.base, args.palette, scripts)))


if __name__ == "__main__":
    main()
