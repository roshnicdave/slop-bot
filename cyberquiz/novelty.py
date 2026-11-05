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


def scenario_signature(p):
    # Actual visible values distinguish practice cases; wording alone does not.
    diagram = p.get("diagram") or {"question": p.get("question", "")}
    if p.get("model"):
        diagram = {
            k: v
            for k, v in p["model"].items()
            if k not in ("seed", "expected") and not k.startswith("fixed")
        }
    return hashlib.sha256(
        json.dumps(
            {"diagram": diagram, "answer": p.get("answer", "")}, sort_keys=True
        ).encode()
    ).hexdigest()


def sync(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS content_history(job TEXT PRIMARY KEY,topic TEXT,claim TEXT,signature TEXT,question TEXT,created TEXT)"
    )
    columns = {r[1] for r in db.execute("PRAGMA table_info(content_history)")}
    for field in ("scenario", "certification", "objective"):
        if field not in columns:
            db.execute("ALTER TABLE content_history ADD COLUMN " + field + " TEXT")
    for row in db.execute(
        "SELECT j.id,j.plan,j.created FROM jobs j LEFT JOIN content_history h ON h.job=j.id WHERE j.plan IS NOT NULL AND (h.scenario IS NULL OR h.certification IS NULL)"
    ).fetchall():
        p = json.loads(row["plan"])
        topic, claim, sig = identity(p)
        db.execute(
            "INSERT OR REPLACE INTO content_history(job,topic,claim,signature,question,created,scenario,certification,objective) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                row["id"],
                topic,
                claim,
                sig,
                p["question"],
                row["created"],
                scenario_signature(p),
                p.get("certification", ""),
                p.get("exam_objective", ""),
            ),
        )
    db.commit()


def recent(db):
    sync(db)
    limit = int(config().get("novelty_cooldown_reels", 50))
    published = [
        dict(r)
        for r in db.execute(
            'SELECT h.topic,h.claim,h.question,h.signature,h.scenario,j.status FROM content_history h JOIN jobs j ON j.id=h.job WHERE j.status="published" ORDER BY j.published_at DESC LIMIT ?',
            (limit,),
        )
    ]
    pending = [
        dict(r)
        for r in db.execute(
            'SELECT h.topic,h.claim,h.question,h.signature,h.scenario,j.status FROM content_history h JOIN jobs j ON j.id=h.job WHERE j.status IN ("voice","rendering","rendered","container_created","container_submitting","publish_unknown") AND (j.status!="rendered" OR j.approved=1)'
        )
    ]
    return published + pending


def check(db, p):
    history = recent(db)
    topic, claim, sig = identity(p)
    c = config()
    lesson_gap = int(c.get("lesson_cooldown_reels", 8))
    scenario = scenario_signature(p)
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
    for index, item in enumerate(history):
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
        if scenario == item["scenario"]:
            raise ValueError("This practice case is inside the Reel repetition window")
        recent_lesson = index < lesson_gap or item["status"] != "published"
        if recent_lesson and (
            sig == item["signature"]
            or normalized(topic) == normalized(item["topic"])
            or overlap >= 0.65
        ):
            raise ValueError(
                "Lesson was covered too recently; rotate to another objective"
            )
    return history


def record(db, job, p):
    sync(db)
    topic, claim, sig = identity(p)
    db.execute(
        "INSERT OR REPLACE INTO content_history(job,topic,claim,signature,question,created,scenario,certification,objective) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            job,
            topic,
            claim,
            sig,
            p["question"],
            now(),
            scenario_signature(p),
            p.get("certification", ""),
            p.get("exam_objective", ""),
        ),
    )
    db.commit()
