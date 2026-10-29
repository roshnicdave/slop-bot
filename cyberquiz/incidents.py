"""Phase-specific failure history; resolved incidents never become live blockers."""

import uuid
from .store import now


def record(db, component, phase, code, message, job=None):
    existing = db.execute(
        "SELECT id FROM incidents WHERE component=? AND phase=? AND code IS ? AND job IS ? AND resolved IS NULL",
        (component, phase, code, job),
    ).fetchone()
    if existing:
        return existing[0]
    ident = uuid.uuid4().hex
    db.execute(
        "INSERT INTO incidents VALUES(?,?,?,?,?,?,?,?,?)",
        (ident, component, phase, code, message, job, now(), None, "open"),
    )
    db.commit()
    return ident


def resolve(db, component, *, phase=None, job=None):
    query = "UPDATE incidents SET resolved=?,state='resolved' WHERE component=? AND resolved IS NULL"
    args = [now(), component]
    if phase is not None:
        query += " AND phase=?"
        args.append(phase)
    if job is not None:
        query += " AND job=?"
        args.append(job)
    db.execute(query, args)
    db.commit()
