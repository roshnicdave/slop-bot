"""Supported Instagram API. Unknown publish outcomes are held, never reposted."""

import json
import time
from urllib.parse import urlparse

import requests

from .providers import secrets, checked
from .store import ROOT, config, now, worker_lock


def graph(method, path, **kwargs):
    cfg = config()
    keys = secrets()
    key = keys["IG_ACCESS_TOKEN"]
    host = (
        "graph.facebook.com"
        if keys.get("IG_AUTH_MODE") == "facebook"
        else "graph.instagram.com"
    )
    return checked(
        requests.request(
            method,
            f"https://{host}/{cfg['graph_version']}/{path}",
            headers={"Authorization": "Bearer " + key},
            timeout=45,
            **kwargs,
        )
    )


def publish(db, job):
    with worker_lock():
        return _publish(db, job)


def _publish(db, job):
    cfg = config()
    keys = secrets()
    if not cfg["publishing_enabled"]:
        raise ValueError("Scheduled publishing is disabled")
    if not keys.get("IG_ACCESS_TOKEN") or not keys.get("IG_USER_ID"):
        raise ValueError("Connect Instagram professional account first")
    import datetime as dt

    hold = cfg.get("publishing_not_before")
    if hold and dt.datetime.now(dt.timezone.utc) < dt.datetime.fromisoformat(hold):
        raise ValueError("Posting is held until the configured resume time")
    row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
    if (
        not row
        or not row["approved"]
        or row["status"] not in ("rendered", "container_created")
    ):
        raise ValueError(
            "Only approved, rendered jobs with a known publish state may publish"
        )
    if db.execute(
        'SELECT 1 FROM jobs WHERE id!=? AND status IN ("publish_unknown","container_submitting") LIMIT 1',
        (job,),
    ).fetchone():
        raise ValueError(
            "Another publication has an unknown result; reconcile it first"
        )
    base = cfg["public_media_base_url"].rstrip("/")
    if urlparse(base).scheme != "https":
        raise ValueError("Meta needs an HTTPS media URL; set public_media_base_url")
    folder = ROOT / "out" / job
    p = json.loads(row["plan"])
    if p.get("visual"):
        from .scenarios import validate
        from .quality import layout

        validate(p)
        layout(p)
        if not p.get("quality", {}).get("passed") or not p.get("quality", {}).get(
            "artifact", {}
        ).get("decode_ok"):
            raise ValueError("Automatic quality gates have not passed")
    if p["family"] == "recent-kev":
        from .content import validate, source_evidence

        validate(p)
        source_evidence(p)  # recheck dates/facts at posting time
    if not row["container_id"]:
        db.execute("UPDATE jobs SET status=? WHERE id=?", ("container_submitting", job))
        db.commit()
        # If the response is lost, do not automatically create another container.
        result = graph(
            "POST",
            keys["IG_USER_ID"] + "/media",
            data={
                "media_type": "REELS",
                "video_url": f"{base}/{job}/reel.mp4",
                "caption": p["caption"],
                "share_to_feed": "true",
            },
        )
        db.execute(
            "UPDATE jobs SET container_id=?,status=? WHERE id=?",
            (result["id"], "container_created", job),
        )
        db.commit()
    container = db.execute(
        "SELECT container_id FROM jobs WHERE id=?", (job,)
    ).fetchone()[0]
    for _ in range(12):
        data = graph("GET", container, params={"fields": "status_code"})
        if data["status_code"] == "FINISHED":
            break
        if data["status_code"] in ("ERROR", "EXPIRED", "PUBLISHED"):
            raise RuntimeError(
                "Container requires manual reconciliation: " + data["status_code"]
            )
        time.sleep(5)
    else:
        raise RuntimeError(
            "Container still processing. Safe to poll again later; no new submission."
        )
    # Commit BEFORE publishing. On timeout leave publish_unknown and reconcile manually.
    db.execute("UPDATE jobs SET status=? WHERE id=?", ("publish_unknown", job))
    db.commit()
    result = graph(
        "POST", keys["IG_USER_ID"] + "/media_publish", data={"creation_id": container}
    )
    db.execute(
        "UPDATE jobs SET media_id=?,status=?,published_at=? WHERE id=?",
        (result["id"], "published", now(), job),
    )
    db.commit()
    (folder / "receipt.json").write_text(
        json.dumps({"media_id": result["id"], "published_at": now()})
    )
    try:
        try:
            permalink = graph("GET", result["id"], params={"fields": "permalink"}).get(
                "permalink", ""
            )
        except Exception:
            permalink = "https://www.instagram.com/" + cfg["account"] + "/"
        from .telegram import notify, status_text

        notify(
            db,
            "published:" + job,
            "Posted: " + permalink + "\nVideo " + job + "\n" + status_text(db, True),
        )
    except Exception:
        # Publishing success stays recorded even if notification transport fails.
        pass
    from .maintenance import erase_media

    erase_media(folder)
    return result["id"]


def insights(db):
    import datetime as dt

    for row in db.execute('SELECT * FROM jobs WHERE status="published"').fetchall():
        age = (
            dt.datetime.now(dt.timezone.utc)
            - dt.datetime.fromisoformat(row["published_at"] or row["created"])
        ).total_seconds() / 3600
        targets = (6, 24, 72, 168, 336)
        due = next(
            (
                h
                for h in targets
                if h <= age < h + 12
                and not db.execute(
                    "SELECT 1 FROM metrics WHERE media_id=? AND age_hours>=? AND age_hours<?",
                    (row["media_id"], h, h + 12),
                ).fetchone()
            ),
            None,
        )
        if due is None:
            continue
        # Store available metrics; unsupported metrics fail independently.
        data = {}
        for name in [
            "reach",
            "views",
            "likes",
            "comments",
            "saved",
            "shares",
            "follows",
            "ig_reels_avg_watch_time",
        ]:
            try:
                data[name] = graph(
                    "GET", row["media_id"] + "/insights", params={"metric": name}
                )
            except RuntimeError:
                data[name] = {"unavailable": True}
        db.execute(
            "INSERT INTO metrics VALUES(?,?,?,?)",
            (row["media_id"], now(), age, json.dumps(data)),
        )
        db.commit()


def refresh_token_if_due():
    """Refresh a long-lived Instagram Login token weekly without an app secret."""
    import datetime as dt

    k = secrets()
    stamp = k.get("IG_TOKEN_REFRESHED_AT")
    if k.get("IG_AUTH_MODE") == "facebook":
        from .auth_health import check

        return check()
    if not k.get("IG_ACCESS_TOKEN") or not stamp:
        return
    if (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(stamp)).days < 7:
        return
    data = checked(
        requests.get(
            "https://graph.instagram.com/refresh_access_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": k["IG_ACCESS_TOKEN"],
            },
            timeout=30,
        )
    )
    from .connect_instagram import save_keys

    save_keys({"IG_ACCESS_TOKEN": data["access_token"], "IG_TOKEN_REFRESHED_AT": now()})
