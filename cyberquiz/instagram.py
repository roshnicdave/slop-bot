"""Supported Instagram API. Unknown publish outcomes are held, never reposted."""

import json
import time
from urllib.parse import urlparse

import requests

from .providers import secrets, checked
from .store import ROOT, config, now, worker_lock


class MetaAPIError(RuntimeError):
    def __init__(self, status, code=None, subcode=None):
        self.http_status, self.code, self.subcode = status, code, subcode
        reason = (
            "Meta denied the app's account access; reconnect Meta"
            if code in (10, 190, 200)
            else "Meta rejected the request"
        )
        super().__init__(f"{reason} (HTTP {status}, code {code}, subcode {subcode})")


def graph(method, path, **kwargs):
    cfg = config()
    keys = secrets()
    host = (
        "graph.facebook.com"
        if keys.get("IG_AUTH_MODE") == "facebook"
        else "graph.instagram.com"
    )
    response = requests.request(
        method,
        f"https://{host}/{cfg['graph_version']}/{path}",
        headers={"Authorization": "Bearer " + keys["IG_ACCESS_TOKEN"]},
        timeout=kwargs.pop("timeout", 45),
        **kwargs,
    )
    if not response.ok:
        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}
        raise MetaAPIError(
            response.status_code, error.get("code"), error.get("error_subcode")
        )
    return response.json()


def publish(db, job, *, immediate=False):
    with worker_lock():
        return _publish(db, job, immediate=immediate)


def _publish(db, job, *, immediate=False):
    cfg = config()
    keys = secrets()
    if not cfg["publishing_enabled"]:
        raise ValueError("Scheduled publishing is disabled")
    if not keys.get("IG_ACCESS_TOKEN") or not keys.get("IG_USER_ID"):
        raise ValueError("Connect Instagram professional account first")
    import datetime as dt

    hold = cfg.get("publishing_not_before")
    if (
        not immediate
        and hold
        and dt.datetime.now(dt.timezone.utc) < dt.datetime.fromisoformat(hold)
    ):
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
        try:
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
        except MetaAPIError as exc:
            from .incidents import record

            record(
                db,
                "instagram",
                "access" if exc.code in (10, 190, 200) else "container_creation",
                exc.code,
                str(exc),
                job,
            )
            # A definite client rejection of creation cannot publish a Reel.
            # Transport failures and 5xx retain the uncertain phase.
            if 400 <= exc.http_status < 500:
                db.execute(
                    "UPDATE jobs SET status='rendered',error=? WHERE id=?",
                    (str(exc), job),
                )
                db.commit()
            if exc.code in (10, 190, 200):
                from .telegram import update_config

                update_config({"publishing_enabled": False})
            raise
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
        "UPDATE jobs SET media_id=?,status=?,published_at=?,error=NULL WHERE id=?",
        (result["id"], "published", now(), job),
    )
    db.commit()
    from .incidents import resolve

    resolve(db, "instagram", job=job)
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
        from .telegram import notify

        notify(
            db,
            "published:" + job,
            "Posted: " + permalink,
        )
    except Exception:
        # Publishing success stays recorded even if notification transport fails.
        pass
    from .maintenance import erase_media

    erase_media(folder)
    from .wakeup import signal

    signal()  # Refill readiness on the worker, outside this publication call.
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
