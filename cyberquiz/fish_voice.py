"""Explicit Fish Drama 3 narration with one paid request per segment."""

import re
import wave
from tempfile import TemporaryDirectory
from pathlib import Path

import requests

from .cloudflare import normalize_wav
from .providers import check_runner, secrets
from .store import charge_update, check_budget, reserve

# Reserve the published list rate, including while promotions are active.
MICRODOLLARS_PER_BYTE = 50


def narrate(db, job, reference, segments, cfg):
    if not isinstance(reference, str) or not re.fullmatch(r"[a-f0-9]{32}", reference):
        raise ValueError("Fish voice requires a configured reference ID")
    check_runner()
    key = secrets().get("FISH_AUDIO_API_KEY")
    if not key:
        raise ValueError("Fish Audio credentials are missing")
    amounts = [
        len(script.encode("utf-8")) * MICRODOLLARS_PER_BYTE for _, script, _ in segments
    ]
    if any(not 0 < amount <= 600 * MICRODOLLARS_PER_BYTE for amount in amounts):
        raise ValueError("Fish narration exceeds the segment size limit")
    for label, _, _ in segments:
        if db.execute(
            "SELECT 1 FROM charges WHERE job=? AND kind=?", (job, "fish_voice:" + label)
        ).fetchone():
            raise ValueError(
                "Fish narration was already requested; no automatic resubmission"
            )
    check_budget(db, job, sum(amounts), cfg)
    for (label, script, path), amount in zip(segments, amounts, strict=True):
        receipt = reserve(db, job, "fish_voice:" + label, amount, cfg)
        with TemporaryDirectory(prefix="fish-", dir=path.parent) as folder:
            candidate = Path(folder) / "speech.wav"
            try:
                with requests.post(
                    "https://api.fish.audio/v1/tts",
                    headers={"Authorization": "Bearer " + key, "model": "drama-3"},
                    json={
                        "text": script,
                        "reference_id": reference,
                        "format": "wav",
                        "sample_rate": 24000,
                        "latency": "normal",
                    },
                    timeout=(8, 45),
                    stream=True,
                    allow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        raise RuntimeError(
                            f"Fish Audio returned HTTP {response.status_code}"
                        )
                    charge_update(
                        db,
                        receipt,
                        status="submitted",
                        request_id=response.headers.get("x-request-id"),
                    )
                    with candidate.open("wb") as handle:
                        for block in response.iter_content(65536):
                            handle.write(block)
                            if handle.tell() > 1_500_000:
                                raise ValueError(
                                    "Fish audio exceeds the segment size limit"
                                )
            except requests.RequestException as exc:
                raise RuntimeError(
                    "Fish Audio request interrupted; charge outcome unconfirmed"
                ) from exc
            try:
                with wave.open(str(candidate)) as audio:
                    if audio.getparams()[:3] != (1, 2, 24000):
                        raise ValueError(
                            "Fish Audio returned an incompatible WAV format"
                        )
                if not 0.3 <= normalize_wav(candidate) <= 30:
                    raise ValueError(
                        "Fish Audio returned an unusable narration duration"
                    )
            except (wave.Error, EOFError) as exc:
                raise ValueError("Fish Audio returned an invalid WAV") from exc
            candidate.replace(path)
        charge_update(db, receipt, status="complete")
