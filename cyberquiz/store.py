"""Durable budget reservations. Unknown/failed charges remain fully reserved."""

import contextlib
import datetime as dt
import json
import sqlite3
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def config():
    return json.loads((ROOT / "config.json").read_text())


def connect(path=None):
    p = Path(path) if path else ROOT / "data" / "state.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(p, timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY, created TEXT NOT NULL, topic TEXT NOT NULL,
      status TEXT NOT NULL, plan TEXT, approved INTEGER DEFAULT 0,
      container_id TEXT, media_id TEXT, slot TEXT UNIQUE, error TEXT, published_at TEXT);
    CREATE TABLE IF NOT EXISTS charges (
      id TEXT PRIMARY KEY, job TEXT NOT NULL, kind TEXT NOT NULL,
      created TEXT NOT NULL, reserved INTEGER NOT NULL, actual INTEGER,
      request_id TEXT, status TEXT NOT NULL, result TEXT,
      UNIQUE(job, kind));
    CREATE TABLE IF NOT EXISTS metrics (
      media_id TEXT, observed TEXT, age_hours REAL, payload TEXT,
      PRIMARY KEY(media_id, observed));
    CREATE TABLE IF NOT EXISTS incidents (
      id TEXT PRIMARY KEY,component TEXT,phase TEXT,code INTEGER,message TEXT,
      job TEXT,opened TEXT,resolved TEXT,state TEXT);
    CREATE TABLE IF NOT EXISTS job_events (
      id INTEGER PRIMARY KEY,job TEXT,previous_status TEXT,status TEXT,
      previous_error TEXT,error TEXT,observed TEXT);
    CREATE TRIGGER IF NOT EXISTS audit_job_transition AFTER UPDATE OF status,error ON jobs
    WHEN OLD.status != NEW.status OR COALESCE(OLD.error,'') != COALESCE(NEW.error,'')
    BEGIN
      INSERT INTO job_events(job,previous_status,status,previous_error,error,observed)
      VALUES(NEW.id,OLD.status,NEW.status,OLD.error,NEW.error,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
    END;
    CREATE TABLE IF NOT EXISTS sources (
      id TEXT PRIMARY KEY, fetched TEXT, published TEXT, url TEXT, payload TEXT);
    """)
    columns = {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
    if "published_at" not in columns:
        db.execute("ALTER TABLE jobs ADD COLUMN published_at TEXT")
        db.commit()
    return db


@contextlib.contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def reserve(db, job, kind, amount, cfg=None):
    """Integer microdollars; never refund based on an unconfirmed estimate."""
    cfg = cfg or config()
    if amount <= 0:
        raise ValueError("Reservation must be positive")
    with transaction(db):
        if db.execute(
            "SELECT 1 FROM charges WHERE job=? AND kind=?", (job, kind)
        ).fetchone():
            raise ValueError(
                "This paid operation already exists; no automatic resubmission"
            )
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=31)).isoformat()
        month = db.execute(
            "SELECT COALESCE(SUM(reserved),0) FROM charges WHERE created>=?", (cutoff,)
        ).fetchone()[0]
        total = db.execute(
            "SELECT COALESCE(SUM(reserved),0) FROM charges WHERE job=?", (job,)
        ).fetchone()[0]
        if month + amount > round(cfg["monthly_budget_usd"] * 1e6):
            raise ValueError("31-day budget exhausted; paid calls stopped")
        if total + amount > round(cfg["per_job_budget_usd"] * 1e6):
            raise ValueError("Per-job budget exhausted; paid call stopped")
        ident = uuid.uuid4().hex
        db.execute(
            "INSERT INTO charges(id,job,kind,created,reserved,status) VALUES(?,?,?,?,?,?)",
            (ident, job, kind, now(), amount, "reserved"),
        )
    return ident


def charge_update(db, ident, **fields):
    allowed = {"actual", "request_id", "status", "result"}
    if not fields or not set(fields) <= allowed:
        raise ValueError("Invalid charge update")
    db.execute(
        "UPDATE charges SET " + ",".join(k + "=?" for k in fields) + " WHERE id=?",
        [*fields.values(), ident],
    )
    db.commit()


def new_job(db, topic, slot=None):
    ident = uuid.uuid4().hex[:12]
    db.execute(
        "INSERT INTO jobs(id,created,topic,status,slot) VALUES(?,?,?,?,?)",
        (ident, now(), topic, "drafting", slot),
    )
    db.commit()
    return ident


import threading

_worker_lease = threading.local()


@contextlib.contextmanager
def worker_lock(blocking=True):
    """One production/publishing owner, reentrant for nested local calls."""
    import fcntl

    depth = getattr(_worker_lease, "depth", 0)
    if depth:
        _worker_lease.depth = depth + 1
        try:
            yield True
        finally:
            _worker_lease.depth = depth
        return
    with (ROOT / "data" / "worker.lock").open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        _worker_lease.depth = 1
        try:
            yield True
        finally:
            _worker_lease.depth = 0
