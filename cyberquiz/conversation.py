"""Telegram transport for the single conversational agent loop."""

import concurrent.futures
import time

from .store import connect, config, transaction
from .telegram import tables, send, mark_replied
from . import chat


def process(ident):
    from .agent import run

    db = connect()
    tables(db)
    row = db.execute("SELECT * FROM telegram_updates WHERE id=?", (ident,)).fetchone()
    user = row["user_id"]
    message = row["command"]
    started = time.monotonic()
    try:
        if user not in config()["telegram_allowed_user_ids"]:
            raise ValueError("Unauthorized operator")
        reply = run(db, ident, user, message)
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
            'UPDATE telegram_updates SET status="done",result=? WHERE id=?',
            (reply, ident),
        )
        db.commit()
        send(user, reply)
        mark_replied(db, ident)
    except Exception as exc:
        # Never replay tool calls after a failed reply; their receipts survive.
        db.execute(
            'UPDATE telegram_updates SET status="failed",result=? WHERE id=?',
            (type(exc).__name__, ident),
        )
        db.commit()
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
