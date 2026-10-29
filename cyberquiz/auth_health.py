"""Check Meta credential health daily and alert through the operating interface."""

import datetime as dt
import json
import requests
from .store import ROOT, connect, now, config
from .providers import secrets


def check(*, force=False):
    k = secrets()
    stamp = k.get("IG_TOKEN_REFRESHED_AT")
    marker = ROOT / "data" / "meta-auth-health.json"
    if marker.exists() and not force:
        cached = json.loads(marker.read_text())
        if (
            cached.get("credential_revision") == stamp
            and (
                dt.datetime.now(dt.timezone.utc)
                - dt.datetime.fromisoformat(cached["checked_at"])
            ).total_seconds()
            < 86400
        ):
            valid = cached.get("valid", False)
            if not valid:
                from .telegram import update_config

                update_config({"publishing_enabled": False})
            return valid
    token = k.get("IG_ACCESS_TOKEN")
    if not token:
        return False
    response = requests.get(
        "https://graph.facebook.com/" + config()["graph_version"] + "/debug_token",
        headers={"Authorization": "Bearer " + token},
        params={"input_token": token},
        timeout=(5, 15),
    )
    data = response.json().get("data")
    if not isinstance(data, dict):
        error = response.json().get("error", {})
        if error.get("code") in (10, 190, 200):
            reason = "Meta denied account access; complete account confirmation or reconnect Meta."
            marker.write_text(
                json.dumps(
                    {
                        "checked_at": now(),
                        "credential_revision": stamp,
                        "valid": False,
                        "reason": reason,
                    }
                )
            )
            from .telegram import update_config

            update_config({"publishing_enabled": False})
            return False
        raise RuntimeError("Meta credential health check unavailable")
    expiry = [
        x
        for x in (data.get("expires_at"), data.get("data_access_expires_at"))
        if isinstance(x, (int, float)) and x > 0
    ]
    remaining = (
        (min(expiry) - dt.datetime.now(dt.timezone.utc).timestamp()) if expiry else None
    )
    valid = bool(data.get("is_valid")) and (remaining is None or remaining > 0)
    marker.write_text(
        json.dumps(
            {
                "checked_at": now(),
                "credential_revision": stamp,
                "valid": valid,
                "expires_at": min(expiry) if expiry else None,
            }
        )
    )
    from .telegram import notify, update_config

    db = connect()
    try:
        if not valid:
            update_config({"publishing_enabled": False})
            notify(
                db,
                "meta-invalid:" + str(stamp),
                "Instagram authorization expired or was revoked. Posting paused; generation continues. Reconnect Meta to resume posting.",
            )
        elif remaining is not None and remaining < 7 * 86400:
            days = max(0, int(remaining // 86400))
            notify(
                db,
                "meta-expiring:" + str(stamp),
                "Instagram authorization needs renewal within "
                + str(days)
                + " days. Reconnect Meta before it expires.",
            )
    finally:
        db.close()
    return valid
