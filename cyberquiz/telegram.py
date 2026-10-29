"""Fast allowlisted control process. Expensive work is durably queued elsewhere."""

import json
import os
import random
import sqlite3
import tempfile
import time


from .store import ROOT, connect, config, now
from .providers import secrets
from .network import http


def tables(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS telegram_updates(id INTEGER PRIMARY KEY, user_id INTEGER, command TEXT, status TEXT, result TEXT, created TEXT);
    CREATE TABLE IF NOT EXISTS telegram_chats(user_id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS notices(event TEXT, chat_id INTEGER, status TEXT, PRIMARY KEY(event,chat_id));
    CREATE TABLE IF NOT EXISTS control(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE IF NOT EXISTS telegram_media(job TEXT PRIMARY KEY,file_id TEXT NOT NULL,created TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS telegram_latency(update_id INTEGER PRIMARY KEY,received REAL,replied REAL,seconds REAL);
    """)
    db.commit()


def api(method, payload=None, files=None, timeout=35):
    token = secrets()["TELEGRAM_BOT_TOKEN"]
    # Never include the token-bearing URL in errors or logs.
    try:
        r = http().post(
            "https://api.telegram.org/bot" + token + "/" + method,
            data=payload or {},
            files=files,
            timeout=timeout,
        )
        data = r.json()
    except Exception:
        raise RuntimeError("Telegram transport failed") from None
    if not r.ok or not data.get("ok"):
        raise RuntimeError("Telegram request failed (HTTP " + str(r.status_code) + ")")
    return data["result"]


def send(chat, text):
    return api(
        "sendMessage",
        {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"},
        timeout=(3, 6),
    )


def video(chat, job):
    import re

    if not re.fullmatch("[a-f0-9]{12}", job):
        return send(chat, "No video found.")
    path = ROOT / "out" / job / "reel.mp4"
    db = connect()
    tables(db)
    cached = db.execute(
        "SELECT file_id FROM telegram_media WHERE job=?", (job,)
    ).fetchone()
    row = db.execute("SELECT plan,status FROM jobs WHERE id=?", (job,)).fetchone()
    caption = (
        json.loads(row["plan"])["question"].replace("\n", " ")
        if row and row["plan"]
        else "Quiz preview"
    )
    payload = {"chat_id": chat, "caption": caption, "supports_streaming": "true"}
    if cached:
        result = api("sendVideo", {**payload, "video": cached[0]}, timeout=30)
    elif path.exists():
        with path.open("rb") as handle:
            result = api("sendVideo", payload, files={"video": handle}, timeout=90)
        db.execute(
            "INSERT OR REPLACE INTO telegram_media VALUES(?,?,?)",
            (job, result["video"]["file_id"], now()),
        )
        db.commit()
    else:
        from .agent import event_reply

        message = event_reply(
            db,
            "missing-preview:" + job + ":" + str(chat),
            {
                "preview_job": job,
                "available": False,
                "reason": "No local media or Telegram file ID remains.",
            },
        )
        db.close()
        return send(chat, message)
    db.execute(
        "INSERT OR REPLACE INTO control VALUES(?,?)", ("last_preview:" + str(chat), job)
    )
    db.commit()
    if row and row["status"] == "preview":
        from .maintenance import erase_media

        erase_media(ROOT / "out" / job)
    db.close()
    return result


def notify(db, event, message):
    tables(db)
    db.execute(
        "CREATE TABLE IF NOT EXISTS notice_texts(event TEXT PRIMARY KEY,facts TEXT,text TEXT,attempts INTEGER DEFAULT 0)"
    )
    db.execute(
        "INSERT OR IGNORE INTO notice_texts(event,facts) VALUES(?,?)", (event, message)
    )
    db.commit()
    cached = db.execute(
        "SELECT text,attempts FROM notice_texts WHERE event=?", (event,)
    ).fetchone()
    if cached[0]:
        message = cached[0]
    else:
        if cached[1] >= 3:
            return
        db.execute(
            "UPDATE notice_texts SET attempts=attempts+1 WHERE event=?", (event,)
        )
        db.commit()
        try:
            import hashlib
            from .agent import event_reply

            message = event_reply(
                db,
                "notice:"
                + hashlib.sha256(event.encode()).hexdigest()[:20]
                + ":"
                + str(cached[1]),
                message,
            )
        except Exception:
            return  # Facts remain pending; no fabricated fallback response.
        db.execute("UPDATE notice_texts SET text=? WHERE event=?", (message, event))
        db.commit()
    owner = config().get("telegram_owner_user_id")
    for row in db.execute("SELECT chat_id FROM telegram_chats").fetchall():
        chat = row[0]
        if not event.startswith("published:") and chat != owner:
            continue
        try:
            db.execute("INSERT INTO notices VALUES(?,?,?)", (event, chat, "sending"))
            db.commit()
        except sqlite3.IntegrityError:
            continue
        try:
            send(chat, message)
            db.execute(
                'UPDATE notices SET status="sent" WHERE event=? AND chat_id=?',
                (event, chat),
            )
            db.commit()
        except RuntimeError:
            # Unknown send outcomes are recorded; do not create a message storm.
            db.execute(
                'UPDATE notices SET status="uncertain" WHERE event=? AND chat_id=?',
                (event, chat),
            )
            db.commit()


def retry_notifications(db):
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='notice_texts'"
    ).fetchone():
        return
    for row in db.execute(
        "SELECT event,facts FROM notice_texts WHERE text IS NULL AND attempts<3 LIMIT 2"
    ).fetchall():
        notify(db, row[0], row[1])


def update_config(values):
    import fcntl

    with (ROOT / "data" / "config.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cfg = config()
        cfg.update(values)
        fd, temp = tempfile.mkstemp(dir=ROOT, prefix=".config-")
        with os.fdopen(fd, "w") as handle:
            json.dump(cfg, handle, indent=2)
        os.replace(temp, ROOT / "config.json")
    from .wakeup import signal

    signal()


HELP = "Ask me about the system, suggest a topic, or tell me to pause. /budget shows spending."


def status_text(db, budget_only=False):
    from .__main__ import report

    r = report(db)
    c = config()
    from .accounting import report as accounting

    usage = accounting(db)
    free = usage.get("neurons_budgeted_today", usage["neurons_reserved_today"])
    if budget_only:
        return (
            f"Paid AI: ${r['reserved_31_days_usd']:.4f} reserved / ${c['monthly_budget_usd']:.2f} monthly cap\n"
            f"Free AI today: {free:,}/{c.get('cf_daily_neuron_limit', 10000):,} quota used/reserved (UTC)"
        )
    generation = (
        "paused"
        if c.get("emergency_pause") or not c.get("generation_enabled")
        else "scheduled"
    )
    connected = bool(secrets().get("IG_ACCESS_TOKEN"))
    publication = (
        "enabled"
        if c["publishing_enabled"]
        else ("paused" if connected else "blocked: Meta authorization missing")
    )
    auth_path = ROOT / "data" / "meta-auth-health.json"
    auth = json.loads(auth_path.read_text()) if auth_path.exists() else {}
    if auth.get("valid") is False and auth.get("reason"):
        publication = "blocked: " + auth["reason"]
    latest = db.execute(
        "SELECT id,status FROM jobs ORDER BY created DESC LIMIT 1"
    ).fetchone()
    ready = db.execute(
        "SELECT COUNT(*) FROM jobs WHERE approved=1 AND status IN ('rendered','container_created')"
    ).fetchone()[0]
    uncertain = db.execute(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('publish_unknown','container_submitting')"
    ).fetchone()[0]
    active = db.execute(
        "SELECT command,status FROM telegram_updates WHERE status IN ('queued','running') ORDER BY id LIMIT 1"
    ).fetchone()
    result = f"Generation: {generation}. Posting: {publication}."
    result += (
        f"\nReady to post: {ready}. Schedule: "
        + ", ".join(c["slots"][: c["posts_per_day"]])
        + " ("
        + c["timezone"]
        + ")."
    )
    if uncertain:
        result += "\nPosting blocked: an earlier publication needs reconciliation."
    if active:
        labels = {
            "/publish-next": "Post next Reel",
            "/next": "Make preview",
            "/research": "Research",
            "/preview": "Send preview",
        }
        result += (
            "\nCurrent request: "
            + labels.get(active["command"].split()[0], "Background task")
            + " ("
            + active["status"]
            + ")."
        )
    elif latest:
        result += f"\nLatest video: {latest['id']} ({latest['status']})."
    return result


def handle(db, update):
    msg = update.get("message", {})
    user = msg.get("from", {}).get("id")
    chat = msg.get("chat", {})
    if (
        user not in config().get("telegram_allowed_user_ids", [])
        or chat.get("type") != "private"
        or chat.get("id") != user
    ):
        return
    text = msg.get("text", "").strip()[:1500]
    if not text:
        return
    db.execute("INSERT OR REPLACE INTO telegram_chats VALUES(?,?)", (user, chat["id"]))
    db.commit()
    if db.execute(
        "SELECT 1 FROM telegram_updates WHERE id=?", (update["update_id"],)
    ).fetchone():
        return
    db.execute(
        "INSERT OR IGNORE INTO telegram_latency(update_id,received) VALUES(?,?)",
        (update["update_id"], time.time()),
    )
    db.commit()
    import re

    credential = re.search(
        r"\bsk-[A-Za-z0-9_-]{20,}|\b\d{7,}:[A-Za-z0-9_-]{25,}|\bEAA[A-Za-z0-9]{40,}|\bIGQ[A-Za-z0-9_-]{40,}|(?i:api[_ -]?key|access[_ -]?token|client[_ -]?secret)\s*[:=]\s*[A-Za-z0-9_:-]{20,}",
        text,
    )
    if credential:
        from .agent import event_reply

        message = event_reply(
            db,
            "credential-warning:" + str(update["update_id"]),
            {
                "credential_detected": True,
                "stored": False,
                "required_handling": "Use the private connection workflow, not Telegram chat.",
            },
        )
        send(user, message)
        return
    db.execute(
        "INSERT INTO telegram_updates VALUES(?,?,?,?,?,?)",
        (update["update_id"], user, text, "received", None, now()),
    )
    db.commit()
    db.execute(
        'UPDATE telegram_updates SET status="queuedchat" WHERE id=?',
        (update["update_id"],),
    )
    db.commit()


def mark_replied(db, ident):
    replied = time.time()
    db.execute(
        "UPDATE telegram_latency SET replied=?,seconds=?-received WHERE update_id=?",
        (replied, replied, ident),
    )
    db.commit()


def main():
    db = connect()
    tables(db)
    delay = 2
    while True:
        row = db.execute(
            'SELECT value FROM control WHERE key="telegram_offset"'
        ).fetchone()
        offset = int(row[0]) if row else 0
        try:
            updates = api(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 25,
                    "allowed_updates": json.dumps(["message"]),
                },
                timeout=32,
            )
            for item in updates:
                handle(db, item)
                db.execute(
                    "INSERT OR REPLACE INTO control VALUES(?,?)",
                    ("telegram_offset", str(item["update_id"] + 1)),
                )
                db.commit()
            db.execute(
                "INSERT OR REPLACE INTO control VALUES(?,?)",
                ("telegram_last_poll", now()),
            )
            db.commit()
            delay = 2
        except Exception as exc:
            db.execute(
                "INSERT OR REPLACE INTO control VALUES(?,?)",
                ("telegram_poll_error", type(exc).__name__ + ":" + now()),
            )
            db.commit()
            # Never log token-bearing exception text. Telegram READ retry is safe.
            time.sleep(delay + random.random())
            delay = min(delay * 2, 60)


if __name__ == "__main__":
    main()
