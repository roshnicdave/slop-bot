import json
import math
import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from unittest.mock import patch

from PIL import ImageChops

from cyberquiz.clean_visual import frame
from cyberquiz.editorial import craft
from cyberquiz.experiments import acceptable
from cyberquiz.scenarios import plan, vlan
from cyberquiz.sound import clock_state, mix
from cyberquiz.visual import scene_times
from cyberquiz.store import connect
from cyberquiz.cloudflare import FreeQuotaDeferred


class CountdownTests(unittest.TestCase):
    def test_non_frame_aligned_voice_and_reveal_get_their_own_frames(self):
        events = [2.2797916667, 3.2797916667, 7.2797916667, 12.19123]
        times = scene_times(16.765333, 8, events)
        self.assertTrue(all(t in times for t in events))
        self.assertTrue(
            all(0 < b - a <= 1 / 8 + 1e-9 for a, b in zip(times, times[1:]))
        )

    def test_clock_changes_match_audio_event_times_without_rounding_drift(self):
        for intro in (0.217, 1.3333333, 3.4399583333333332):
            for seconds in (3, 5, 7):
                self.assertEqual(clock_state(intro - 0.01, intro, seconds), (None, 0.0))
                for n in range(seconds):
                    count, progress = clock_state(intro + n, intro, seconds)
                    self.assertEqual(count, seconds - n)
                    self.assertAlmostEqual(progress, n / seconds)
                self.assertEqual(
                    clock_state(intro + seconds, intro, seconds), (None, 1.0)
                )
                self.assertEqual(
                    clock_state(intro + seconds - 1e-12, intro, seconds)[0], 1
                )

    def test_ticks_are_audible_only_at_the_displayed_seconds_and_preserve_speech(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "speech.wav"
            rate, intro, seconds = 16000, 1.375, 5
            samples = array("h", [0] * int((intro + seconds + 1) * rate) * 2)
            # Real nonzero speech before the countdown must remain unchanged.
            for i in range(int(intro * rate) * 2):
                samples[i] = round(2000 * math.sin(i / 20))
            with wave.open(str(path), "wb") as out:
                out.setparams((2, 2, rate, 0, "NONE", "not compressed"))
                out.writeframes(samples.tobytes())
            info = mix(path, intro, seconds)
            with wave.open(str(path), "rb") as result:
                self.assertEqual(result.getnchannels(), 2)
                audio = array("h", result.readframes(result.getnframes()))
            start = round(intro * rate) * 2
            self.assertEqual(audio[:start], samples[:start])
            for n, at in enumerate(info["tick_times"]):
                self.assertEqual(clock_state(at, intro, seconds)[0], seconds - n)
                onset = round(at * rate) * 2
                self.assertGreater(
                    max(abs(x) for x in audio[onset : onset + round(0.04 * rate) * 2]),
                    900,
                )
                gap = audio[
                    onset + round(0.08 * rate) * 2 : onset + round(0.90 * rate) * 2
                ]
                self.assertFalse(any(gap))
            self.assertEqual(info["reveal_at"], intro + seconds)
            self.assertLessEqual(max(map(abs, audio)), 32767)

    def test_dial_keeps_the_diagram_and_answers_and_bottom_safe_area_unchanged(self):
        p = plan(vlan(), {}, "test")
        p["palette"] = "ink"
        dial = frame({**p, "countdown_style": "dial"}, "question", 3, progress=0.4)
        bar = frame({**p, "countdown_style": "bar"}, "question", 3, progress=0.4)
        self.assertIsNone(
            ImageChops.difference(
                dial.crop((0, 0, 720, 990)), bar.crop((0, 0, 720, 990))
            ).getbbox()
        )
        self.assertIsNotNone(ImageChops.difference(dial, bar).getbbox())
        self.assertIsNone(
            ImageChops.difference(
                dial.crop((0, 1140, 720, 1280)), bar.crop((0, 1140, 720, 1280))
            ).getbbox()
        )

    def test_direct_question_and_wrapped_question_are_spoken_verbatim(self):
        for lines in (
            ["Why can't these PCs communicate?"],
            ["Why can't these PCs", "communicate?"],
        ):
            p = plan(vlan(), {}, "test")
            original = json.dumps(p["diagram"], sort_keys=True)
            with patch(
                "cyberquiz.editorial.cloudflare.llm", return_value={"hook_lines": lines}
            ):
                result = craft(
                    None,
                    "test",
                    p,
                    {"editorial_feedback": {"issues": ["Simplify opening"]}},
                )
            self.assertEqual(result["question"], "\n".join(lines))
            self.assertEqual(result["intro"], " ".join(lines))
            self.assertEqual(json.dumps(result["diagram"], sort_keys=True), original)

    def test_clock_experiments_cannot_raise_sound_to_unsafe_levels(self):
        self.assertTrue(acceptable("countdown_style", "dial"))
        self.assertTrue(acceptable("tick_level_dbfs", -24))
        self.assertFalse(acceptable("countdown_style", "flashing"))
        self.assertFalse(acceptable("tick_level_dbfs", -3))

    def test_fallback_opening_polish_is_optional_when_free_quota_is_reserved(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            p = plan(vlan(), {}, "test")
            original = p["question"]
            with patch(
                "cyberquiz.editorial.cloudflare.llm",
                side_effect=FreeQuotaDeferred("Reserved for publication"),
            ):
                result = craft(db, "test", p, {"ideas": []})
            self.assertEqual(result["question"], original)
            self.assertEqual(
                result["creative_draft"]["copy_status"], "deferred:FreeQuotaDeferred"
            )
            db.close()

    def test_fallback_gets_a_direct_opening_without_waiting_for_a_quality_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            p = plan(vlan(), {}, "test")
            with patch(
                "cyberquiz.editorial.cloudflare.llm",
                return_value={"hook_lines": ["Why can't these PCs communicate?"]},
            ) as model:
                result = craft(db, "test", p, {"ideas": []})
            model.assert_called_once()
            self.assertEqual(result["question"], "Why can't these PCs communicate?")
            self.assertEqual(result["creative_draft"]["copy_status"], "revised")
            db.close()
