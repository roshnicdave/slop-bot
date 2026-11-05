"""Public exam topic maps and coverage, independent of the question inventory."""

import datetime as dt
import hashlib
import io
import json
import re
from urllib.parse import urlparse
import requests
from .store import config, now, ROOT

BLUEPRINTS = {
    "CCNA": "https://learningcontent.cisco.com/documents/marketing/exam-topics/200-301-CCNA-v1.1.pdf",
    "Network+": "https://comptiacdn.azureedge.net/webcontent/docs/default-source/exam-objectives/comptia-network-n10-009-exam-objectives-%284-0%29-%281%29.pdf",
    "Security+": "https://comptiacdn.azureedge.net/webcontent/docs/default-source/exam-objectives/comptia-security-sy0-701-exam-objectives-%286-0%29.pdf",
}


def parse(text):
    result = {}
    for line in text.splitlines():
        match = re.match(
            r"^\s*(?:\d+%\s*)?(\d+\s*\.\s*\d+(?:\s*\.\s*[a-z])?)\s+(.{4,})", line
        )
        if match:
            ident, title = match.groups()
            ident = re.sub(r"\s+", "", ident)
            title = re.sub(r"\s*\d+%\s*$", "", title.lstrip("| "))
            if "Copyright" not in title:
                result[ident] = " ".join(title.split())[:180]
    return result


def refresh(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS curriculum_documents(cert TEXT PRIMARY KEY,url TEXT,sha TEXT,checked TEXT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS curriculum_topics(cert TEXT,objective TEXT,title TEXT,source TEXT,PRIMARY KEY(cert,objective))"
    )
    db.commit()
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
    for cert, url in config().get("exam_blueprints", BLUEPRINTS).items():
        prior = db.execute(
            "SELECT checked FROM curriculum_documents WHERE cert=?", (cert,)
        ).fetchone()
        if prior and prior[0] > cutoff:
            continue
        if urlparse(url).hostname not in (
            "learningcontent.cisco.com",
            "comptiacdn.azureedge.net",
            "assets.ctfassets.net",
        ):
            continue
        try:
            from pypdf import PdfReader

            with requests.get(
                url, timeout=(5, 20), allow_redirects=False, stream=True
            ) as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_content(16384):
                    raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raise ValueError(
                            "Blueprint exceeds text-only ingestion profile"
                        )
            reader = PdfReader(io.BytesIO(raw))
            if len(reader.pages) > 30:
                raise ValueError("Blueprint has too many pages")
            topics = parse(
                "\n".join(
                    p.extract_text(extraction_mode="layout") or "" for p in reader.pages
                )
            )
            if len(topics) < 10:
                raise ValueError("Blueprint did not yield a usable topic map")
            db.execute("DELETE FROM curriculum_topics WHERE cert=?", (cert,))
            db.executemany(
                "INSERT INTO curriculum_topics VALUES(?,?,?,?)",
                [(cert, k, v, url) for k, v in topics.items()],
            )
            db.execute(
                "INSERT OR REPLACE INTO curriculum_documents VALUES(?,?,?,?)",
                (cert, url, hashlib.sha256(raw).hexdigest(), now()),
            )
            db.commit()
        except (ImportError, ValueError, requests.RequestException):
            continue  # Retain the last known topic map; never block a post.


def goals(db, limit=24):
    refresh(db)
    counts = {}
    from .novelty import sync

    sync(db)
    for row in db.execute(
        "SELECT h.certification,h.objective FROM content_history h JOIN jobs j ON j.id=h.job WHERE j.status IN ('published','voice','rendering','rendered','container_created','publish_unknown')"
    ):
        key = (row[0], row[1])
        counts[key] = counts.get(key, 0) + 1
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='source_attempts'"
    ).fetchone():
        for row in db.execute("SELECT id FROM source_attempts WHERE status='ready'"):
            path = ROOT / "data" / "discovery" / (row[0] + ".json")
            if path.exists():
                p = json.loads(path.read_text())
                key = (p.get("certification"), p.get("exam_objective"))
                counts[key] = counts.get(key, 0) + 1
    groups = {}
    for row in db.execute(
        "SELECT cert,objective,title FROM curriculum_topics ORDER BY cert,objective"
    ):
        if row["objective"].count(".") != 1 or row["objective"].endswith(".0"):
            continue
        key = (row["cert"], row["objective"].split(".")[0])
        groups.setdefault(key, []).append(dict(row))
    day = now()[:10]
    for entries in groups.values():
        entries.sort(
            key=lambda r: (
                counts.get((r["cert"], r["objective"]), 0),
                hashlib.sha256((day + r["objective"]).encode()).hexdigest(),
            )
        )
    ordered = sorted(
        groups,
        key=lambda k: (
            sum(counts.get((r["cert"], r["objective"]), 0) for r in groups[k]),
            k[0] != "CCNA",
            k,
        ),
    )
    selected = []
    while len(selected) < limit and any(groups.values()):
        for group in ordered:
            if groups[group]:
                row = groups[group].pop(0)
                row["id"] = row["cert"] + ":" + row["objective"]
                selected.append(row)
                if len(selected) == limit:
                    break
    return selected


def for_source(db, title, passages, limit=8):
    """Retrieve relevant objectives without excluding a whole domain by daily rotation."""
    import math
    from collections import Counter

    objectives = goals(db, limit=200)
    words = lambda text: set(re.findall(r"[a-z]{4,}", text.lower()))
    source = words(title + " " + " ".join(p["text"] for p in passages))
    terms = [words(o["title"]) for o in objectives]
    frequency = Counter(w for group in terms for w in group)
    ranked = sorted(
        zip(objectives, terms),
        key=lambda pair: (
            -sum(math.log(1 + len(objectives) / frequency[w]) for w in pair[1] & source)
        ),
    )
    return [item for item, _ in ranked[:limit]]
