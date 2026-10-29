"""Workers Free only. One shared, durable neuron allowance; no paid fallback."""

import datetime as dt
import json
import math
import re
import wave

import requests

from .store import config, now, transaction
from .providers import secrets, check_runner
from .network import http

LLM = "@cf/meta/llama-3.1-8b-instruct-fp8-fast"
VOICE = "@cf/deepgram/aura-1"
EDITOR = "@cf/mistralai/mistral-small-3.1-24b-instruct"


def available():
    k = secrets()
    return bool(
        (k.get("CF_WORKER_URL") and k.get("CF_WORKER_TOKEN"))
        or (k.get("CLOUDFLARE_ACCOUNT_ID") and k.get("CLOUDFLARE_API_TOKEN"))
    )


def reserve(db, operation, kind, neurons):
    c = config()
    if not c.get("cf_free_plan_confirmed"):
        raise ValueError("Cloudflare Free plan must be confirmed by owner")
    if c.get("emergency_pause") and kind not in ("chat", "control"):
        raise ValueError("Pipeline is paused")
    db.execute(
        "CREATE TABLE IF NOT EXISTS cf_calls(operation TEXT PRIMARY KEY,day TEXT,kind TEXT,neurons INTEGER,status TEXT,created TEXT)"
    )
    db.commit()
    with transaction(db):
        columns = {r[1] for r in db.execute("PRAGMA table_info(cf_calls)")}
        for col, typ in [
            ("result", "TEXT"),
            ("usage", "TEXT"),
            ("latency_ms", "INTEGER"),
            ("accounted_neurons", "INTEGER"),
        ]:
            if col not in columns:
                db.execute("ALTER TABLE cf_calls ADD COLUMN " + col + " " + typ)
    day = dt.datetime.now(dt.timezone.utc).date().isoformat()
    with transaction(db):
        total = db.execute(
            "SELECT COALESCE(SUM(COALESCE(accounted_neurons,neurons)),0) FROM cf_calls WHERE day=?",
            (day,),
        ).fetchone()[0]
        if total + neurons > int(c.get("cf_daily_neuron_limit", 8000)):
            raise ValueError(
                "Shared Cloudflare free allowance reserved; wait until UTC reset"
            )
        categories = {
            "chat": ["chat", "control"],
            "voice": ["voice"],
            "research": ["research", "editorial"],
        }
        category = next(
            (name for name, kinds in categories.items() if kind in kinds), None
        )
        if category is None:
            raise ValueError("Unknown quota category")
        limit = {
            "chat": c.get("cf_chat_neuron_limit", 3000),
            "voice": 3000,
            "research": c.get("cf_research_neuron_limit", 4500),
        }[category]
        kinds = categories[category]
        used = db.execute(
            "SELECT COALESCE(SUM(COALESCE(accounted_neurons,neurons)),0) FROM cf_calls WHERE day=? AND kind IN ("
            + ",".join("?" for _ in kinds)
            + ")",
            [day, *kinds],
        ).fetchone()[0]
        if used + neurons > limit:
            raise ValueError(
                "Free "
                + category
                + " quota reserved; production/control allowance is protected"
            )
        if db.execute(
            "SELECT 1 FROM cf_calls WHERE operation=?", (operation,)
        ).fetchone():
            raise ValueError(
                "Operation already submitted; no automatic inference retry"
            )
        db.execute(
            "INSERT INTO cf_calls(operation,day,kind,neurons,status,created) VALUES(?,?,?,?,?,?)",
            (operation, day, kind, neurons, "reserved", now()),
        )


def request(db, operation, kind, model, body, neurons):
    # No Gateway credits, paid models, model switching, or external paid fallback.
    if model not in (LLM, EDITOR, VOICE):
        raise ValueError("Model is outside the free-only allowlist")
    reserve(db, operation, kind, neurons)
    k = secrets()
    account = k.get("CLOUDFLARE_ACCOUNT_ID")
    if k.get("CF_WORKER_URL"):
        url = k["CF_WORKER_URL"] + "/run"
        token = k["CF_WORKER_TOKEN"]
        payload = {"model": model, "input": body}
    else:
        url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
        token = k["CLOUDFLARE_API_TOKEN"]
        payload = body
    import time

    started = time.monotonic()
    try:
        r = http().post(
            url,
            headers={"Authorization": "Bearer " + token},
            json=payload,
            timeout=(5, 8 if kind in ("chat", "control") else 90),
        )
    except requests.RequestException:
        raise RuntimeError(
            "Cloudflare request outcome unknown; reservation retained"
        ) from None
    if not r.ok:
        raise RuntimeError(
            "Cloudflare returned HTTP "
            + str(r.status_code)
            + "; no fallback or paid retry"
        )
    cached = r.text[:20000] if "json" in r.headers.get("content-type", "") else None
    usage = None
    accounted = None
    if cached:
        try:
            provider_usage = r.json().get("result", {}).get("usage")
            usage = json.dumps(provider_usage)
            actual = (
                provider_usage.get("neurons")
                if isinstance(provider_usage, dict)
                else None
            )
            if (
                isinstance(actual, (int, float))
                and actual > 0
                and math.isfinite(actual)
            ):
                accounted = math.ceil(actual * 1.1) + 1
        except (ValueError, AttributeError):
            pass
    db.execute(
        'UPDATE cf_calls SET status="complete",result=?,usage=?,latency_ms=?,accounted_neurons=? WHERE operation=?',
        (
            cached,
            usage,
            round((time.monotonic() - started) * 1000),
            accounted,
            operation,
        ),
    )
    db.commit()
    return r


def llm(db, operation, messages, kind="research", max_tokens=1000):
    if max_tokens > 1400:
        raise ValueError("Output exceeds bounded profile")
    size = len(json.dumps(messages, ensure_ascii=False).encode()) + 512
    if size > 18000:
        raise ValueError("Research context exceeds bounded profile")
    # At published 4,119 neurons/M input, 34,868/M output. Add 25% headroom.
    model = EDITOR if kind in ("editorial", "chat", "control") else LLM
    input_rate, output_rate = (31876, 50488) if model == EDITOR else (4119, 34868)
    neurons = (
        math.ceil((size * input_rate + max_tokens * output_rate) / 1e6 * 1.25) + 10
    )
    r = request(
        db,
        operation,
        kind,
        model,
        {"messages": messages, "max_tokens": max_tokens, "temperature": 0.35},
        neurons,
    )
    data = r.json()
    if not data.get("success"):
        raise RuntimeError("Cloudflare inference did not report success")
    value = data["result"].get("response", "")
    if isinstance(value, dict):
        return value
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


def normalize_wav(path):
    # Streaming TTS can use an open-ended WAV length in its header. Measure
    # actual decoded PCM bytes, then finalize a normal seekable WAV locally.
    with wave.open(str(path)) as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        rate = source.getframerate()
        pcm = source.readframes(60 * rate + 1)
    seconds = len(pcm) / (channels * width * rate)
    if seconds > 60:
        raise RuntimeError("Narration exceeds 60-second per-segment bound")
    temp = path.with_suffix(".normalized.wav")
    with wave.open(str(temp), "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(width)
        target.setframerate(rate)
        target.writeframes(pcm)
    temp.replace(path)
    return seconds


def voice(db, job, label, text, path):
    check_runner()
    if not text.isascii() or len(text) > 600:
        raise ValueError("Voice exceeds bounded profile")
    if path.exists():
        normalize_wav(path)
        return path  # saved completed audio, no second inference
    speaker = config().get("voice_speaker", "orion")
    if speaker not in (
        "orion",
        "arcas",
        "angus",
        "orpheus",
        "perseus",
        "helios",
        "zeus",
    ):
        raise ValueError("Choose a supported male voice")
    neurons = math.ceil(len(text) * 1.36364 * 1.25) + 10
    r = request(
        db,
        job + ":voice:" + label,
        "voice",
        VOICE,
        {
            "text": text,
            "speaker": speaker,
            "encoding": "linear16",
            "container": "wav",
            "sample_rate": 24000,
        },
        neurons,
    )
    if len(r.content) > 10_000_000:
        raise RuntimeError("Audio response unexpectedly large")
    path.write_bytes(r.content)
    normalize_wav(path)
    return path


def agent_turn(db, operation, messages, tools):
    body = {"messages": messages, "tools": tools, "max_tokens": 360, "temperature": 0.2}
    size = len(json.dumps(body).encode())
    if size > 44000:
        raise ValueError("Agent context limit reached")
    neurons = math.ceil((size * 31876 + 360 * 50488) / 1e6 * 1.25) + 10
    response = request(db, operation, "control", EDITOR, body, neurons).json()
    if not response.get("success"):
        raise RuntimeError("Agent provider did not report success")
    result = response["result"]
    choice = (result.get("choices") or [{}])[0].get("message", {})
    return {
        "content": choice.get("content") or result.get("response") or "",
        "tool_calls": choice.get("tool_calls") or result.get("tool_calls") or [],
    }
