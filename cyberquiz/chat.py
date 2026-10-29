"""Persistent conversation memory and operator preferences."""

from .store import now


def tables(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS chat_turns(update_id INTEGER PRIMARY KEY,user_id INTEGER,request TEXT,reply TEXT,action TEXT,created TEXT,latency_ms INTEGER)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS preferences(id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT,created TEXT)"
    )
    db.commit()


def history(db, user, limit=6, *, verified=False):
    tables(db)
    rows = db.execute(
        "SELECT request,reply,action FROM chat_turns WHERE user_id=? ORDER BY update_id DESC LIMIT ?",
        (user, limit),
    ).fetchall()
    return [
        {
            "user": r[0][:220],
            "assistant": r[1][:350]
            if not verified or r[2] == "agent"
            else "[legacy response not authoritative]",
        }
        for r in reversed(rows)
    ]


def remember(db, ident, user, message, reply, action, latency_ms):
    tables(db)
    db.execute(
        "INSERT OR REPLACE INTO chat_turns VALUES(?,?,?,?,?,?,?)",
        (ident, user, message[:1500], reply[:1800], action, now(), latency_ms),
    )
    db.commit()


def preference(db, user, text):
    tables(db)
    saved = db.execute(
        "INSERT INTO preferences(user_id,text,created) VALUES(?,?,?)",
        (user, text[:700], now()),
    )
    db.execute(
        "INSERT OR REPLACE INTO control VALUES(?,?)", ("topic_preference", text[:700])
    )
    db.commit()
    return saved.lastrowid
