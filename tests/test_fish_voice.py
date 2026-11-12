import contextlib
import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

from cyberquiz.production import narrate
from cyberquiz.store import connect, new_job


class FishVoiceTests(unittest.TestCase):
    def test_saved_voice_is_used_and_a_missing_paid_segment_is_never_resubmitted(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            contextlib.closing(connect(":memory:")) as db,
        ):
            folder = Path(tmp)
            job = new_job(db, "voice-test")
            p = {
                "voice_provider": "fish",
                "fish_voice_reference_id": "a" * 32,
                "intro": "Why?",
                "reveal_voice": "It is on a different subnet.",
                "fix_voice": "Check the mask.",
            }
            cfg = {
                "voice_provider": "cloudflare",
                "monthly_budget_usd": 0.10,
                "per_job_budget_usd": 0.03,
            }
            wav = io.BytesIO()
            with wave.open(wav, "wb") as audio:
                audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\xff\x00" * 24000)
            response = MagicMock(
                status_code=200, headers={"x-request-id": "test-request"}
            )
            response.__enter__.return_value = response
            response.iter_content.side_effect = lambda _: iter([wav.getvalue()])
            with (
                patch("cyberquiz.fish_voice.check_runner"),
                patch(
                    "cyberquiz.fish_voice.secrets",
                    return_value={"FISH_AUDIO_API_KEY": "test"},
                ),
                patch(
                    "cyberquiz.fish_voice.requests.post", return_value=response
                ) as post,
            ):
                narrate(db, job, p, folder, cfg)
                self.assertEqual(post.call_count, 3)
                self.assertEqual(post.call_args.kwargs["headers"]["model"], "drama-3")
                self.assertEqual(
                    post.call_args.kwargs["json"]["reference_id"], "a" * 32
                )
                narrate(db, job, p, folder, cfg)
                (folder / "reveal_voice.wav").unlink()
                with self.assertRaisesRegex(ValueError, "already requested"):
                    narrate(db, job, p, folder, cfg)
                self.assertEqual(post.call_count, 3)
            reserved = db.execute("SELECT SUM(reserved) FROM charges").fetchone()[0]
            self.assertEqual(
                reserved,
                50 * sum(len(p[k]) for k in ("intro", "reveal_voice", "fix_voice")),
            )
