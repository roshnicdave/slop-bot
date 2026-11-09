"""Locally synthesized clock ticks, aligned with the visible solve countdown."""

from array import array
import math
import wave


def clock_state(elapsed, start, seconds):
    if elapsed < start:
        return None, 0.0
    if elapsed >= start + seconds:
        return None, 1.0
    return max(1, math.ceil(start + seconds - elapsed - 1e-9)), (
        elapsed - start
    ) / seconds


def tick_times(start, seconds):
    return [start + n for n in range(seconds)]


def mix(path, intro, decision, *, tick_level_dbfs=-24):
    if not -32 <= tick_level_dbfs <= -18:
        raise ValueError("Tick level outside the audible, speech-safe range")
    with wave.open(str(path), "rb") as w:
        params = w.getparams()
        samples = array("h", w.readframes(w.getnframes()))
    if params.sampwidth != 2:
        raise ValueError("Cue mixing requires PCM16")

    def tone(at, frequency, seconds, amplitude):
        start = round(at * params.framerate)
        count = round(seconds * params.framerate)
        for n in range(count):
            envelope = math.sin(math.pi * n / count) ** 2
            value = round(
                amplitude
                * envelope
                * math.sin(2 * math.pi * frequency * n / params.framerate)
            )
            for channel in range(params.nchannels):
                i = (start + n) * params.nchannels + channel
                if i < len(samples):
                    samples[i] = max(-32768, min(32767, samples[i] + value))

    def tick(at):
        start = round(at * params.framerate)
        amplitude = 32767 * 10 ** (tick_level_dbfs / 20)
        for n in range(round(0.045 * params.framerate)):
            t = n / params.framerate
            envelope = min(1, t / 0.001) * math.exp(-t / 0.008)
            click = 0.7 * math.sin(2 * math.pi * 1700 * t) + 0.3 * math.sin(
                2 * math.pi * 3100 * t
            )
            value = round(amplitude * envelope * click)
            for channel in range(params.nchannels):
                i = (start + n) * params.nchannels + channel
                if i < len(samples):
                    samples[i] = max(-32768, min(32767, samples[i] + value))

    events = tick_times(intro, decision)
    for at in events:
        tick(at)
    tone(intro + decision, 660, 0.14, 1460)
    tone(intro + decision + 0.09, 880, 0.14, 1160)
    with wave.open(str(path), "wb") as w:
        w.setparams(params)
        w.writeframes(samples.tobytes())
    return {
        "profile": "clock-v2",
        "tick_level_dbfs": tick_level_dbfs,
        "tick_times": events,
        "reveal_at": intro + decision,
    }
