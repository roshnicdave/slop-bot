"""Selected premium male voice with durable reservations; never a fallback."""

import json
import subprocess
import time
import requests
from .store import reserve, charge_update, config
from .providers import secrets, checked, valid_fal_url, download, check_runner

ENDPOINT = "fal-ai/elevenlabs/tts/eleven-v3"


def preflight(db, scripts):
    """Reject the whole narration before buying any segment."""
    import datetime as dt

    cfg = config()
    amount = sum(len(x) for x in scripts) * 100
    if amount > round(cfg["per_job_budget_usd"] * 1e6):
        raise ValueError("Narration exceeds per-video spending cap")
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=31)).isoformat()
    spent = db.execute(
        "SELECT COALESCE(SUM(reserved),0) FROM charges WHERE created>=?", (cutoff,)
    ).fetchone()[0]
    if spent + amount > round(cfg["monthly_budget_usd"] * 1e6):
        raise ValueError("Monthly narration allowance exhausted")


def generate(db, job, label, text, speaker, path):
    if path.exists():
        return
    check_runner()
    row = db.execute("SELECT status FROM jobs WHERE id=?", (job,)).fetchone()
    if not row or row[0] not in ("preview", "voice"):
        raise ValueError("Premium voice requires an unpublished production job")
    preview = row[0] == "preview"
    if not preview and config().get("voice_provider") != "elevenlabs":
        raise ValueError("Premium production voice is not selected")
    if speaker not in ("Chris", "George") or not text.isascii() or len(text) > 350:
        raise ValueError("Preview voice profile invalid")
    cfg = config()
    cap = round(cfg.get("preview_voice_experiment_cap_usd", 0) * 1e6)
    amount = len(text) * 100
    spent = db.execute(
        'SELECT COALESCE(SUM(reserved),0) FROM charges WHERE kind LIKE "preview_voice:%"'
    ).fetchone()[0]
    if preview and spent + amount > cap:
        raise ValueError("Authorized preview experiment cap reached")
    headers = {"Authorization": "Key " + secrets()["FAL_KEY"]}
    pricing = checked(
        requests.get(
            "https://api.fal.ai/v1/models/pricing",
            headers=headers,
            params={"endpoint_id": ENDPOINT},
            timeout=25,
        )
    )["prices"][0]
    if (
        pricing["unit_price"] > 0.1
        or pricing["unit"] != "1000 characters"
        or pricing["currency"] != "USD"
    ):
        raise ValueError("Premium voice pricing changed")
    ident = reserve(
        db,
        job,
        ("preview_voice:" if preview else "premium_voice:") + label,
        amount,
        {**cfg, "per_job_budget_usd": min(0.04, cfg["monthly_budget_usd"])}
        if preview
        else cfg,
    )
    response = checked(
        requests.post(
            "https://queue.fal.run/" + ENDPOINT,
            headers=headers,
            json={
                "text": text,
                "voice": speaker,
                "stability": 0.5,
                "language_code": "en",
                "timestamps": True,
            },
            timeout=45,
        )
    )
    charge_update(
        db,
        ident,
        status="submitted",
        request_id=response["request_id"],
        result=json.dumps(response),
    )
    if not all(valid_fal_url(response[k]) for k in ("status_url", "response_url")):
        raise ValueError("Unexpected premium queue URL")
    until = time.monotonic() + 180
    while time.monotonic() < until:
        status = checked(
            requests.get(response["status_url"], headers=headers, timeout=25)
        )
        if status["status"] == "COMPLETED":
            result = checked(
                requests.get(response["response_url"], headers=headers, timeout=25)
            )
            charge_update(db, ident, status="complete", result=json.dumps(result))
            raw = path.with_suffix(".mp3")
            download(result["audio"]["url"], raw)
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(raw),
                    "-ar",
                    "24000",
                    "-ac",
                    "1",
                    str(path),
                ],
                check=True,
            )
            raw.unlink()
            return
        if status["status"] not in ("IN_QUEUE", "IN_PROGRESS"):
            raise RuntimeError("Premium voice failed; reservation retained")
        time.sleep(2)
    raise RuntimeError("Premium voice outcome pending; no automatic resubmission")
