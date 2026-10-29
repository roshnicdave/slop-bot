import datetime as dt
import json
import math
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from .store import ROOT, now, reserve, charge_update, config

FLASH_INPUT = 0.30  # USD / million tokens, peak, no cache discount assumed
FLASH_OUTPUT = 1.20
MAX_OUTPUT = 1400
ENDPOINTS = {"image": "fal-ai/flux/schnell", "voice": "fal-ai/kokoro"}


def secrets():
    path = Path(
        os.environ.get(
            "CYBERQUIZ_SECRETS",
            str(Path.home() / ".config/cyber-quiz/credentials.json"),
        )
    )
    keys = json.loads(path.read_text()) if path.exists() else {}
    for key in (
        "FAL_KEY",
        "DEEPSEEK_API_KEY",
        "IG_ACCESS_TOKEN",
        "IG_USER_ID",
        "FAL_REPORTING_KEY",
        "IG_AUTH_MODE",
    ):
        if os.environ.get(key):
            keys[key] = os.environ[key]
    return keys


def checked(response):
    # Do not expose URLs with tokens, request headers, or provider error bodies.
    if not response.ok:
        raise RuntimeError(
            f"Provider returned HTTP {response.status_code}; no paid retry"
        )
    return response.json()


def fal_prices():
    data = checked(
        requests.get(
            "https://api.fal.ai/v1/models/pricing",
            params={"endpoint_id": ",".join(ENDPOINTS.values())},
            headers={"Authorization": "Key " + secrets()["FAL_KEY"]},
            timeout=30,
        )
    )
    prices = {p["endpoint_id"]: p for p in data["prices"]}
    expected = {
        "fal-ai/flux/schnell": (0.003, "megapixels"),
        "fal-ai/kokoro": (0.02, "1000 characters"),
    }
    for endpoint, (price, unit) in expected.items():
        p = prices[endpoint]
        if p["currency"] != "USD" or p["unit"] != unit or p["unit_price"] > price:
            raise RuntimeError("Fal pricing changed: generation stopped for review")
    return prices


def verify_deepseek_price():
    """Fail closed on documentation changes; retain evidence with a timestamp."""
    import re
    import html

    url = "https://api-docs.deepseek.com/quick_start/pricing/"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    text = html.unescape(re.sub("<[^>]+>", " ", r.text))
    text = re.sub(r"\s+", " ", text)
    # Confirm Flash's peak rates in the provider's pricing table.
    if not re.search(
        r"CACHE MISS.{0,100}OFF.PEAK\s*\$0\.15.{0,50}PEAK\s*\$0\.3\b", text
    ):
        raise RuntimeError("DeepSeek input pricing could not be confirmed; stopped")
    if not re.search(
        r"OUTPUT TOKENS.{0,60}OFF.PEAK\s*\$0\.6.{0,50}PEAK\s*\$1\.2\b", text
    ):
        raise RuntimeError("DeepSeek output pricing could not be confirmed; stopped")
    path = ROOT / "data" / "pricing-evidence.json"
    path.write_text(
        json.dumps(
            {
                "checked_at": now(),
                "url": url,
                "input_per_million": FLASH_INPUT,
                "output_per_million": FLASH_OUTPUT,
                "excerpt": text,
            },
            indent=2,
        )
    )


def check_runner():
    import socket

    if config().get("emergency_pause"):
        raise RuntimeError("Emergency pause: no new paid submissions")
    host = config().get("runner_host")
    if host and socket.gethostname() != host:
        raise RuntimeError(
            "Paid generation is assigned to the AWS runner; use its shared budget ledger"
        )


def deepseek(db, job, messages, kind="script"):
    if not config().get("paid_providers_enabled", False):
        raise ValueError("Paid providers are disabled; free-only policy")
    check_runner()
    verify_deepseek_price()
    body = {
        "model": "deepseek-flash",
        "messages": messages,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "max_tokens": MAX_OUTPUT,
        "temperature": 0.8,
        "stream": False,
    }
    # UTF-8 bytes are a conservative token bound, plus 512 framing tokens.
    bound = len(json.dumps(messages, ensure_ascii=False).encode()) + 512
    amount = math.ceil(bound * FLASH_INPUT + MAX_OUTPUT * FLASH_OUTPUT)
    ident = reserve(db, job, kind, amount)
    result = checked(
        requests.post(
            "https://api.deepseek.com/chat/completions",
            json=body,
            headers={"Authorization": "Bearer " + secrets()["DEEPSEEK_API_KEY"]},
            timeout=120,
        )
    )
    usage = result["usage"]
    actual = math.ceil(
        usage["prompt_tokens"] * FLASH_INPUT + usage["completion_tokens"] * FLASH_OUTPUT
    )
    charge_update(
        db,
        ident,
        actual=actual,
        status="complete",
        request_id=result.get("id"),
        result=json.dumps(
            {"usage": usage, "content": result["choices"][0]["message"]["content"]}
        ),
    )
    if actual > amount:
        raise RuntimeError(
            "Token usage exceeded reservation; investigate before proceeding"
        )
    return json.loads(result["choices"][0]["message"]["content"])


def valid_fal_url(url):
    p = urlparse(url)
    return p.scheme == "https" and p.hostname == "queue.fal.run"


def fal(db, job, kind, body):
    if not config().get("paid_providers_enabled", False):
        raise ValueError("Paid providers are disabled; free-only policy")
    endpoint = ENDPOINTS["voice" if kind.startswith("voice") else "image"]
    fal_prices()  # live check before every submission
    if endpoint.endswith("schnell"):
        if (
            body.get("image_size") != {"width": 576, "height": 1024}
            or body.get("num_images") != 1
        ):
            raise ValueError("Image dimensions/count exceed allowed profile")
        amount = 3000  # rounded UP to one megapixel
    else:
        prompt = body["prompt"]
        if not prompt.isascii() or len(prompt) > 600:
            raise ValueError("Voice text exceeds allowed profile")
        amount = math.ceil(len(prompt) * 20)  # microdollars at $0.02/1000 characters
    check_runner()
    ident = reserve(db, job, kind, amount)
    headers = {"Authorization": "Key " + secrets()["FAL_KEY"]}
    response = checked(
        requests.post(
            "https://queue.fal.run/" + endpoint, headers=headers, json=body, timeout=45
        )
    )
    # Store the request ID before polling: a restart must not submit it twice.
    charge_update(
        db,
        ident,
        request_id=response["request_id"],
        status="submitted",
        result=json.dumps(response),
    )
    for name in ("status_url", "response_url"):
        if not valid_fal_url(response[name]):
            raise RuntimeError("Unexpected queue URL")
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        status = checked(
            requests.get(response["status_url"], headers=headers, timeout=30)
        )
        if status["status"] == "COMPLETED":
            result = checked(
                requests.get(response["response_url"], headers=headers, timeout=30)
            )
            charge_update(db, ident, status="complete", result=json.dumps(result))
            return result
        if status["status"] not in ("IN_QUEUE", "IN_PROGRESS"):
            raise RuntimeError("Fal request did not complete; reservation retained")
        time.sleep(3)
    raise RuntimeError("Fal queue timed out; request ID saved; no paid retry")


def download(url, target):
    p = urlparse(url)
    if p.scheme != "https" or not (
        p.hostname == "fal.media" or (p.hostname or "").endswith(".fal.media")
    ):
        raise ValueError("Unexpected media host")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    if len(r.content) > 25_000_000:
        raise ValueError("Unexpectedly large media")
    Path(target).write_bytes(r.content)


def balances():
    k = secrets()
    ds = checked(
        requests.get(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": "Bearer " + k["DEEPSEEK_API_KEY"]},
            timeout=30,
        )
    )
    fal_response = requests.get(
        "https://api.fal.ai/v1/models/usage",
        headers={"Authorization": "Key " + k.get("FAL_REPORTING_KEY", k["FAL_KEY"])},
        params={
            "endpoint_id": ",".join(ENDPOINTS.values()),
            "expand": "summary",
            "bound_to_timeframe": "false",
            "start": dt.datetime.now(dt.timezone.utc).date().isoformat(),
        },
        timeout=30,
    )
    fal_usage = (
        fal_response.json()
        if fal_response.ok
        else {
            "unavailable": True,
            "http_status": fal_response.status_code,
            "note": "This key cannot read usage; invoice reconciliation requires dashboard or a reporting-permitted key.",
        }
    )
    return {"checked_at": now(), "deepseek": ds, "fal": fal_usage}
