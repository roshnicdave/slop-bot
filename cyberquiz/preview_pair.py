"""Create two private refinement previews, with a six-cent total voice ceiling."""

import json
from .store import ROOT, connect, new_job, worker_lock, config
from . import scenarios
from .labs import bank
from .quality import review, artifact
from .visual import render
from .premium_voice import generate
from .telegram import video, send, tables


def main():
    db = connect()
    tables(db)
    samples = [
        (
            scenarios.vlan(),
            "Chris",
            "Both links are green.\nWhy can't these PCs ping?",
            "Both links are up. Same IP subnet. Access ports. No router.",
            "Both links are green. Why can't these PCs ping? Comment your answer.",
            "They are in different VLANs. A Layer two switch does not route between them.",
            "Put both access ports in the same VLAN.",
        ),
        (
            next(x for x in bank() if x["key"] == "url-host"),
            "George",
            "This login page looks real.\nWhere does your request go?",
            "No redirects. Read the address bar.",
            "This login page looks real. Where does your request go? Comment your answer.",
            None,
            None,
        ),
    ]
    with worker_lock():
        for scene, speaker, question, clue, intro, reveal, fix in samples:
            job = new_job(db, "private-refinement:" + scene["key"])
            folder = ROOT / "out" / job
            folder.mkdir()
            p = scenarios.plan(scene, {}, job)
            p.update(
                question=question,
                clue=clue,
                intro=intro,
                design_version=3,
                sound_cues=True,
                voice_speaker=speaker,
            )
            if reveal:
                p["reveal_voice"] = reveal
            if fix:
                p["fix_voice"] = fix
            p["outro"] = p["reveal_voice"] + " " + p["fix_voice"]
            p["caption"] = (
                question.replace("\n", " ")
                + "\n\nComment A, B, C or D before the reveal.\n\n"
                + p["explanation"]
                + "\n"
                + p["fix"]
                + "\nSource: "
                + p["source_url"]
            )
            quality = review(db, job, p)
            p["quality"] = quality
            if not quality["passed"]:
                raise ValueError("Preview failed editorial review")
            (folder / "plan.json").write_text(json.dumps(p, indent=2))
            db.execute(
                'UPDATE jobs SET status="preview",approved=0,plan=? WHERE id=?',
                (json.dumps(p), job),
            )
            db.commit()
            for label in ("intro", "reveal_voice", "fix_voice"):
                generate(db, job, label, p[label], speaker, folder / (label + ".wav"))
            render(folder)
            p["quality"]["artifact"] = artifact(folder)
            (folder / "plan.json").write_text(json.dumps(p, indent=2))
            (folder / "quality.json").write_text(json.dumps(p["quality"], indent=2))
            db.execute("UPDATE jobs SET plan=? WHERE id=?", (json.dumps(p), job))
            db.commit()
            for chat in db.execute(
                "SELECT chat_id FROM telegram_chats WHERE user_id=?",
                (config()["telegram_owner_user_id"],),
            ).fetchall():
                send(
                    chat[0],
                    "Private preview: " + speaker + " voice. Posting is paused.",
                )
                video(chat[0], job)
            print(
                json.dumps(
                    {
                        "job": job,
                        "voice": speaker,
                        "quality": p["quality"]["artifact"],
                        "sent": True,
                    }
                )
            )


if __name__ == "__main__":
    main()
