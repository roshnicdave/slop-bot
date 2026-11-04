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
VISION = "@cf/meta/llama-3.2-11b-vision-instruct"
ASR = "@cf/openai/whisper"
EDITOR = "@cf/mistralai/mistral-small-3.1-24b-instruct"
REVIEW = "@cf/qwen/qwen3-30b-a3b-fp8"
AGENT_OUTPUT_TOKENS = 180


class CloudflareRequestError(RuntimeError):
    """Transient provider failure; any reservation remains accounted."""


class FreeQuotaDeferred(ValueError):
    """No provider request was submitted; safe to defer until allowance resets."""


class ModelOutputError(ValueError):
    """A completed inference returned unusable structured output."""


def parse_llm_response(data):
    if not data.get("success"):
        raise RuntimeError("Cloudflare inference did not report success")
    result = data["result"]
    value = result.get("response")
    if value is None:
        value = (result.get("choices") or [{}])[0].get("message", {}).get("content", "")
    if isinstance(value, dict):
        return value
    try:
        text = re.sub(r"^<think>.*?</think>\s*", "", value.strip(), flags=re.S)
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Expected a JSON object")
        return parsed
    except (ValueError, AttributeError, TypeError) as exc:
        raise ModelOutputError(
            "Completed model response is not a valid JSON object"
        ) from exc


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
        if total + neurons > int(c.get("cf_daily_neuron_limit", 10000)):
            raise FreeQuotaDeferred(
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
            "chat": c.get(
                "cf_chat_neuron_limit", c.get("cf_daily_neuron_limit", 10000)
            ),
            "voice": 3000,
            "research": c.get("cf_research_neuron_limit", 3000),
        }[category]
        kinds = categories[category]
        used = db.execute(
            "SELECT COALESCE(SUM(COALESCE(accounted_neurons,neurons)),0) FROM cf_calls WHERE day=? AND kind IN ("
            + ",".join("?" for _ in kinds)
            + ")",
            [day, *kinds],
        ).fetchone()[0]
        if used + neurons > limit:
            raise FreeQuotaDeferred(
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
    if model not in (LLM, EDITOR, REVIEW, VOICE, VISION, ASR):
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
            timeout=(5, 30 if kind in ("chat", "control") else 90),
        )
    except requests.RequestException:
        raise CloudflareRequestError(
            "Cloudflare request outcome unknown; reservation retained"
        ) from None
    if not r.ok:
        raise CloudflareRequestError(
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


def llm(db, operation, messages, kind="research", max_tokens=1000, *, model=None):
    if max_tokens > 1400:
        raise ValueError("Output exceeds bounded profile")
    size = len(json.dumps(messages, ensure_ascii=False).encode()) + 512
    if size > 18000:
        raise ValueError("Research context exceeds bounded profile")
    # At published 4,119 neurons/M input, 34,868/M output. Add 25% headroom.
    model = model or (EDITOR if kind in ("editorial", "chat", "control") else LLM)
    input_rate, output_rate = {
        EDITOR: (31876, 50488),
        LLM: (4119, 34868),
        REVIEW: (4625, 30475),
    }[model]
    if model == REVIEW:
        messages = [dict(m) for m in messages]
        messages[-1]["content"] += "\n/no_think"
    neurons = (
        math.ceil((size * input_rate + max_tokens * output_rate) / 1e6 * 1.25) + 10
    )
    r = request(
        db,
        operation,
        kind,
        model,
        {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.35,
            "response_format": {"type": "json_object"},
        },
        neurons,
    )
    return parse_llm_response(r.json())


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


def agent_turn(db, operation, messages, tools, *, model=REVIEW):
    # Workers AI's Qwen schema requires string content on assistant tool calls.
    # Preserve the provider-neutral durable transcript, normalize only on send.
    messages = [
        dict(m, content="" if m.get("content") is None else m["content"])
        for m in messages
    ]
    if model == REVIEW:
        messages = [dict(m) for m in messages]
        messages[0]["content"] += "\n/no_think"
    body = {
        "messages": messages,
        "max_tokens": AGENT_OUTPUT_TOKENS,
        "temperature": 0.2,
    }
    if tools:
        body["tools"] = tools
    require_tool = bool(tools) and not any(m.get("role") == "tool" for m in messages)
    if require_tool:
        body["tool_choice"] = "required"
    size = len(json.dumps(body).encode())
    if size > 44000:
        raise ValueError("Agent context limit reached")
    input_rate, output_rate = (4625, 30475) if model == REVIEW else (31876, 50488)
    neurons = (
        math.ceil((size * input_rate + AGENT_OUTPUT_TOKENS * output_rate) / 1e6 * 1.25)
        + 10
    )
    response = request(db, operation, "control", model, body, neurons).json()
    if not response.get("success"):
        raise RuntimeError("Agent provider did not report success")
    result = response["result"]
    choice = (result.get("choices") or [{}])[0].get("message", {})
    calls = choice.get("tool_calls") or result.get("tool_calls") or []
    if require_tool and not calls:
        raise CloudflareRequestError("Cloudflare omitted the required capability call")
    return {
        "content": choice.get("content") or result.get("response") or "",
        "tool_calls": calls,
    }
