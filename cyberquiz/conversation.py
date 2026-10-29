"""Small-model action proposal + typed executor, separate from production."""

import concurrent.futures
import json
import time

from .store import connect, config, transaction
from .telegram import tables, send, status_text, update_config, mark_replied
from . import chat
from .providers import secrets

ACTIONS = [
    "answer",
    "status",
    "budget",
    "request_video",
    "publish_next",
    "show_preview",
    "explain",
    "pause",
    "resume",
    "idea",
    "approve",
    "reject",
    "research",
    "posting",
    "schedule",
    "set_budget",
]


def process(ident):
    db = connect()
    tables(db)
    row = db.execute("SELECT * FROM telegram_updates WHERE id=?", (ident,)).fetchone()
    user = row["user_id"]
    message = row["command"]
    try:
        if user not in config()["telegram_allowed_user_ids"]:
            raise ValueError("Unauthorized")
        jobs = [
            dict(r)
            for r in db.execute(
                "SELECT id,status,approved,plan FROM jobs WHERE plan IS NOT NULL ORDER BY created DESC LIMIT 5"
            )
        ]
        summary = [
            {
                "id": j["id"],
                "status": j["status"],
                "approved": bool(j["approved"]),
                "question": json.loads(j["plan"])["question"],
                "explanation": json.loads(j["plan"])["explanation"],
            }
            for j in jobs
        ]
        viewed = db.execute(
            "SELECT value FROM control WHERE key=?", ("last_preview:" + str(user),)
        ).fetchone()
        last_preview = viewed[0] if viewed else None
        pref = db.execute(
            'SELECT value FROM control WHERE key="topic_preference"'
        ).fetchone()
        from .scenarios import bank

        scene_keys = [s["key"] for s in bank()]
        context = {
            "timezone": config()["timezone"],
            "schedule": config()["slots"][: config()["posts_per_day"]],
            "monthly_budget_usd": config()["monthly_budget_usd"],
            "scene_keys": scene_keys,
            "editorial_preference": pref[0][:500] if pref else "",
            "last_preview": last_preview,
            "status": status_text(db),
            "jobs": summary,
            "policy": "Cloudflare LLMs use the free daily quota. The selected premium male voice is metered within the shared monthly spending cap; no paid model fallback. Both users share the queue. Posting requires Instagram authorization and automatic quality gates. No routine human approvals. No guarantee of virality. New visuals show a diagram, 4 choices, AI voice, answer and fix.",
            "capabilities": "daily primary-source discovery of new topics, 50-Reel concept cooldown and persistent history; executable or source-grounded fact checks; selected male narration; local rendering; no automatic competitor video vision yet",
        }
        from .context import snapshot

        context["live"] = snapshot(db)
        started = time.monotonic()
        out = chat.propose(db, "chat:" + str(ident), message, context, user)
        feedback = out.get("feedback")
        action = out.get("action")
        job = str(out.get("job_id", "")).strip()
        reply = ""
        if action not in ACTIONS:
            raise ValueError("Model proposed an unsupported action")
        if action == "answer":
            reply = str(out.get("reply", "I need a little more detail."))[:400]
        elif action == "status":
            reply = status_text(db)
        elif action == "budget":
            reply = status_text(db, True)
        elif action == "pause":
            update_config(
                {
                    "emergency_pause": True,
                    "generation_enabled": False,
                    "publishing_enabled": False,
                }
            )
            reply = "Paused generation and posting."
        elif action == "resume":
            connected = bool(secrets().get("IG_ACCESS_TOKEN"))
            update_config(
                {
                    "emergency_pause": False,
                    "generation_enabled": True,
                    "publishing_enabled": connected,
                }
            )
            reply = "Resumed. " + status_text(db)
        elif action in ("posting", "schedule", "set_budget"):
            from .control import execute

            try:
                reply = execute(action, out)
            except ValueError as exc:
                reply = str(exc)
        elif action in ("request_video", "show_preview", "research", "publish_next"):
            if (
                action in ("request_video", "publish_next")
                and db.execute(
                    'SELECT COUNT(*) FROM telegram_updates WHERE status IN ("queued","running") AND command IN ("/next", "/publish-next")'
                ).fetchone()[0]
            ):
                reply = "A video request is already in progress. Ask for status to follow it."
            else:
                cmd = {
                    "request_video": "/next",
                    "publish_next": "/publish-next",
                    "show_preview": "/preview",
                    "research": "/research",
                }[action]
                idea = str(out.get("idea", ""))[:500]
                if action == "request_video" and idea:
                    db.execute(
                        "INSERT OR REPLACE INTO control VALUES(?,?)",
                        ("topic_preference", idea),
                    )
                if action == "show_preview":
                    if not job:
                        job = last_preview or next(
                            (
                                j["id"]
                                for j in summary
                                if j["status"] in ("preview", "rendered", "published")
                            ),
                            "",
                        )
                    cmd += " " + job
                db.execute(
                    'UPDATE telegram_updates SET command=?,status="queued",result=? WHERE id=?',
                    (
                        cmd,
                        json.dumps(
                            {
                                "user_request": message,
                                "idea": idea,
                                "scene_key": str(out.get("scene_key", ""))
                                if out.get("scene_key") in scene_keys
                                else None,
                            }
                        ),
                        ident,
                    ),
                )
                db.commit()
                from .wakeup import signal

                signal()
                reply = "I will " + (
                    "post the next eligible Reel; if the queue is empty, make one first."
                    if action == "publish_next"
                    else "make the video and send it here."
                    if action == "request_video"
                    else "send that here shortly."
                )
                chat.remember(
                    db,
                    ident,
                    user,
                    message,
                    reply,
                    action,
                    round((time.monotonic() - started) * 1000),
                )
                try:
                    send(user, reply)
                    mark_replied(db, ident)
                except RuntimeError:
                    pass  # accepted work survives an acknowledgement failure
                return
        elif action == "idea":
            chat.preference(
                db,
                user,
                feedback if isinstance(feedback, str) and feedback.strip() else message,
            )
            reply = "Saved as a preference for future research and scripts. Already rendered videos stay as they are."
        elif action == "explain":
            if not job:
                job = next((j["id"] for j in summary if j["status"] == "rendered"), "")
            item = next((j for j in jobs if j["id"] == job), None)
            if item:
                p = json.loads(item["plan"])
                reply = (
                    p["explanation"]
                    + "\n\n"
                    + p.get("clue", "")
                    + "\nSource: "
                    + p["source_url"]
                )
            else:
                reply = "Which video do you want me to explain?"
        elif action in ("approve", "reject"):
            if not job:
                job = last_preview or ""
            if job != last_preview and job not in message:
                send(
                    user,
                    "Which preview do you mean? I need to identify it before changing approval.",
                )
                db.execute(
                    'UPDATE telegram_updates SET status="done" WHERE id=?', (ident,)
                )
                db.commit()
                return
            item = next(
                (j for j in jobs if j["id"] == job and j["status"] == "rendered"), None
            )
            if not item:
                reply = "Which rendered video do you mean? Ask me to show the preview first."
            else:
                db.execute(
                    "UPDATE jobs SET approved=?,status=? WHERE id=?",
                    (
                        int(action == "approve"),
                        "rendered" if action == "approve" else "rejected",
                        job,
                    ),
                )
                db.commit()
                reply = (
                    ("Approved " if action == "approve" else "Rejected ")
                    + job
                    + ". Publishing still follows the configured connection and schedule."
                )
        chat.remember(
            db,
            ident,
            user,
            message,
            reply,
            action,
            round((time.monotonic() - started) * 1000),
        )
        send(user, reply or "I could not safely interpret that. Please rephrase.")
        mark_replied(db, ident)
        db.execute(
            'UPDATE telegram_updates SET status="done",result=? WHERE id=?',
            (reply, ident),
        )
        db.commit()
    except Exception as exc:
        db.execute(
            'UPDATE telegram_updates SET status="failed",result=? WHERE id=?',
            (type(exc).__name__, ident),
        )
        db.commit()
        try:
            send(
                user,
                "Couldn’t reach the AI right now. /budget still works."
                if not isinstance(exc, ValueError)
                else "Couldn’t complete that. " + status_text(db),
            )
        except Exception:
            pass
    finally:
        db.close()


def main():
    db = connect()
    tables(db)
    # Interrupted inference is not replayed blindly; its reservation remains.
    db.execute(
        'UPDATE telegram_updates SET status="interrupted" WHERE status="chat_running"'
    )
    db.commit()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pending = {}
        while True:
            pending = {p: u for p, u in pending.items() if not p.done()}
            if len(pending) < 2:
                with transaction(db):
                    rows = db.execute(
                        'SELECT id,user_id FROM telegram_updates WHERE status="queuedchat" ORDER BY id'
                    ).fetchall()
                    row = next(
                        (r for r in rows if r["user_id"] not in pending.values()), None
                    )
                    if row:
                        db.execute(
                            'UPDATE telegram_updates SET status="chat_running" WHERE id=?',
                            (row[0],),
                        )
                if row:
                    pending[pool.submit(process, row[0])] = row["user_id"]
            time.sleep(0.1)


if __name__ == "__main__":
    main()
