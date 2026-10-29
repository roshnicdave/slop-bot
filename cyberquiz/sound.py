"""Quiet synthesized decision ticks and a reveal cue; no music downloads."""

from array import array
import math
import wave


def mix(path, intro, decision):
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

    for n in range(int(decision)):
        tone(intro + n, 850, 0.055, 250)
    tone(intro + decision, 660, 0.17, 350)
    tone(intro + decision + 0.09, 880, 0.17, 300)
    with wave.open(str(path), "wb") as w:
        w.setparams(params)
        w.writeframes(samples.tobytes())
