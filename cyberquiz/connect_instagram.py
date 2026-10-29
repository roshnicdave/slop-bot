"""Owner-run hidden token prompt. Never prints or logs the token."""

import datetime as dt
import getpass
import json
import os
from pathlib import Path
import tempfile

import requests

from .store import config
from .providers import checked


def save_keys(values):
    path = Path(
        os.environ.get(
            "CYBERQUIZ_SECRETS",
            str(Path.home() / ".config/cyber-quiz/credentials.json"),
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing = json.loads(path.read_text()) if path.exists() else {}
    existing.update(values)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".keys-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(existing, handle)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    import sys

    facebook = "--facebook" in sys.argv
    label = (
        "long-lived Facebook Page access token"
        if facebook
        else "long-lived Instagram access token"
    )
    print(
        "Paste the "
        + label
        + ". Input is hidden. This verifies the linked account without posting."
    )
    token = getpass.getpass("Page token: " if facebook else "Instagram token: ").strip()
    if not token or any(c.isspace() for c in token):
        raise ValueError("Token missing or contains whitespace")
    host = "graph.facebook.com" if facebook else "graph.instagram.com"
    fields = (
        "instagram_business_account{id,username}" if facebook else "user_id,username"
    )
    data = checked(
        requests.get(
            f"https://{host}/{config()['graph_version']}/me",
            headers={"Authorization": "Bearer " + token},
            params={"fields": fields},
            timeout=30,
        )
    )
    if facebook:
        data = data.get("instagram_business_account", {})
        if not data:
            raise ValueError("Page token has no linked Instagram professional account")
    if "data" in data and isinstance(data["data"], list):
        data = data["data"][0]
    if data["username"].lower() != config()["account"].lower():
        raise ValueError("Token belongs to another Instagram account; nothing saved")
    ident = data.get("user_id") or data.get("id")
    if not ident:
        raise ValueError("Instagram user ID missing; nothing saved")
    save_keys(
        {
            "IG_ACCESS_TOKEN": token,
            "IG_USER_ID": str(ident),
            "IG_AUTH_MODE": "facebook" if facebook else "instagram",
            "IG_TOKEN_REFRESHED_AT": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    )
    print(
        "Connected @"
        + data["username"]
        + ". Credentials saved securely. Publishing is still controlled by config.json."
    )


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("Cancelled; nothing saved.")
    except Exception as exc:
        print(
            "Connection failed: "
            + type(exc).__name__
            + ". No token printed. Check account and permissions."
        )
