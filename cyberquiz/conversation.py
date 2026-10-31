"""Telegram transport for the single conversational agent loop."""

import concurrent.futures
import datetime as dt
import json
import time

from .store import connect, config, transaction, now
from .telegram import tables, send, mark_replied
from . import chat


def process(ident):
    from .agent import run

    db = connect()
    tables(db)
    row = db.execute("SELECT * FROM telegram_updates WHERE id=?", (ident,)).fetchone()
    user = row["user_id"]
    message = row["command"]
    db.execute(
        "CREATE TABLE IF NOT EXISTS chat_recovery(update_id INTEGER PRIMARY KEY,attempts INTEGER DEFAULT 0,retry_at TEXT,error TEXT)"
    )
    recovery = db.execute(
        "SELECT attempts FROM chat_recovery WHERE update_id=?", (ident,)
    ).fetchone()
    attempt = recovery[0] if recovery else 0
    started = time.monotonic()
    try:
        if user not in config()["telegram_allowed_user_ids"]:
            raise ValueError("Unauthorized operator")
        reply = run(db, ident, user, message, attempt=attempt)
        chat.remember(
            db,
            ident,
            user,
            message,
            reply,
            "agent",
            round((time.monotonic() - started) * 1000),
        )
        db.execute(
            'UPDATE telegram_updates SET status="reply_ready",result=? WHERE id=?',
            (reply, ident),
        )
        db.commit()
        send(user, reply)
        mark_replied(db, ident)
        db.execute("UPDATE telegram_updates SET status='done' WHERE id=?", (ident,))
        db.commit()
        from .incidents import resolve

        resolve(db, "conversation", phase="reply", job=str(ident))
    except Exception as exc:
        from .cloudflare import FreeQuotaDeferred, CloudflareRequestError

        if isinstance(exc, FreeQuotaDeferred):
            reset = (
                dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=1)
            ).isoformat() + "T00:00:00+00:00"
            db.execute(
                'UPDATE telegram_updates SET status="chat_deferred",result=? WHERE id=?',
                (json.dumps({"reason": str(exc), "retry_at": reset}), ident),
            )
            db.commit()
            return
        detail = type(exc).__name__ + (
            ": " + str(exc)[:180] if isinstance(exc, (ValueError, RuntimeError)) else ""
        )
        # Retry inference only. Agent sessions resume after durable tool receipts.
        if isinstance(exc, CloudflareRequestError) and attempt < 2:
            retry_at = (
                dt.datetime.now(dt.timezone.utc)
                + dt.timedelta(seconds=30 * (attempt + 1))
            ).isoformat()
            db.execute(
                "INSERT OR REPLACE INTO chat_recovery VALUES(?,?,?,?)",
                (ident, attempt + 1, retry_at, detail),
            )
            db.execute(
                "UPDATE telegram_updates SET status='chat_retry',result=? WHERE id=?",
                (detail, ident),
            )
            db.commit()
            return
        # Never replay tool calls after a failed reply; their receipts survive.
        db.execute(
            'UPDATE telegram_updates SET status="failed",result=? WHERE id=?',
            (detail, ident),
        )
        db.commit()
        from .incidents import record

        record(db, "conversation", "reply", None, detail, job=str(ident))
        from .telegram import notify

        notify(
            db,
            "chat-failed:" + str(ident),
            json.dumps(
                {
                    "event": "chat_reply_failed",
                    "request_received_at": row["created"],
                    "error": detail,
                    "effect": "The message was received but no reply completed. Any completed actions retain receipts.",
                }
            ),
        )
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
    db.execute(
        "CREATE TABLE IF NOT EXISTS chat_recovery(update_id INTEGER PRIMARY KEY,attempts INTEGER DEFAULT 0,retry_at TEXT,error TEXT)"
    )
    db.commit()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pending = {}
        while True:
            pending = {p: u for p, u in pending.items() if not p.done()}
            db.execute(
                "UPDATE telegram_updates SET status='queuedchat' WHERE status='chat_deferred' AND json_extract(result,'$.retry_at')<=?",
                (dt.datetime.now(dt.timezone.utc).isoformat(),),
            )
            db.commit()
            db.execute(
                "UPDATE telegram_updates SET status='queuedchat' WHERE status='chat_retry' AND id IN (SELECT update_id FROM chat_recovery WHERE retry_at<=?)",
                (now(),),
            )
            db.commit()
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
