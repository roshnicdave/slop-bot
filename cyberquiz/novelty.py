"""Persistent content history, independent of disposable media files."""

import hashlib
import json
import re
from .store import now, config


def normalized(text):
    text = re.sub(r"https?://\S+", " URL ", text.lower())
    text = re.sub(r"\d+(?:[.:/]\d+)*", " # ", text)
    return " ".join(re.findall(r"[a-z]+|#", text))


def identity(p):
    topic = p.get("topic") or p["family"]
    claim = p.get("core_claim") or (p["answer"] + " " + p["explanation"])
    signature = hashlib.sha256(normalized(claim).encode()).hexdigest()
    return str(topic)[:240], str(claim)[:600], signature


def sync(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS content_history(job TEXT PRIMARY KEY,topic TEXT,claim TEXT,signature TEXT,question TEXT,created TEXT)"
    )
    for row in db.execute(
        "SELECT id,plan,created FROM jobs WHERE plan IS NOT NULL AND id NOT IN (SELECT job FROM content_history)"
    ).fetchall():
        p = json.loads(row["plan"])
        topic, claim, sig = identity(p)
        db.execute(
            "INSERT INTO content_history VALUES(?,?,?,?,?,?)",
            (row["id"], topic, claim, sig, p["question"], row["created"]),
        )
    db.commit()


def recent(db):
    sync(db)
    limit = int(config().get("novelty_cooldown_reels", 50))
    published = [
        dict(r)
        for r in db.execute(
            'SELECT h.topic,h.claim,h.question,h.signature FROM content_history h JOIN jobs j ON j.id=h.job WHERE j.status="published" ORDER BY j.published_at DESC LIMIT ?',
            (limit,),
        )
    ]
    pending = [
        dict(r)
        for r in db.execute(
            'SELECT h.topic,h.claim,h.question,h.signature FROM content_history h JOIN jobs j ON j.id=h.job WHERE j.status IN ("voice","rendering","rendered","container_created","container_submitting","publish_unknown")'
        )
    ]
    return published + pending


def check(db, p):
    history = recent(db)
    topic, claim, sig = identity(p)
    # Exact learning claims remain blocked across all publication history.
    duplicate = db.execute(
        'SELECT 1 FROM content_history h JOIN jobs j ON j.id=h.job WHERE h.signature=? AND j.status="published" LIMIT 1',
        (sig,),
    ).fetchone()
    if duplicate:
        raise ValueError(
            "Previously published claim; wording or number changes are not novelty"
        )
    words = set(normalized(topic + " " + claim).split()) - {
        "#",
        "the",
        "a",
        "an",
        "is",
        "of",
        "to",
        "in",
        "and",
        "for",
        "this",
        "that",
    }
    for item in history:
        other = set(normalized(item["topic"] + " " + item["claim"]).split()) - {
            "#",
            "the",
            "a",
            "an",
            "is",
            "of",
            "to",
            "in",
            "and",
            "for",
            "this",
            "that",
        }
        overlap = len(words & other) / max(1, len(words | other))
        if (
            sig == item["signature"]
            or normalized(topic) == normalized(item["topic"])
            or overlap >= 0.65
        ):
            raise ValueError("Concept is inside the 50-Reel cooldown")
    return history


def record(db, job, p):
    sync(db)
    topic, claim, sig = identity(p)
    db.execute(
        "INSERT OR REPLACE INTO content_history VALUES(?,?,?,?,?,?)",
        (job, topic, claim, sig, p["question"], now()),
    )
    db.commit()
