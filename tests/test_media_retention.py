import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cyberquiz.store import connect, new_job
from cyberquiz.telegram import video


class TelegramRetentionTests(unittest.TestCase):
    def test_preview_deleted_after_delivery_and_resent_by_telegram_file_id(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            path = root / "data" / "s.db"
            db = connect(path)
            job = new_job(db, "test")
            plan = {"question": "Test question"}
            db.execute(
                'UPDATE jobs SET status="preview",plan=? WHERE id=?',
                (json.dumps(plan), job),
            )
            db.commit()
            db.close()
            out = root / "out" / job
            out.mkdir(parents=True)
            (out / "reel.mp4").write_bytes(b"video")
            (out / "plan.json").write_text(json.dumps(plan))
            with (
                patch("cyberquiz.telegram.ROOT", root),
                patch("cyberquiz.maintenance.ROOT", root),
                patch("cyberquiz.telegram.connect", side_effect=lambda: connect(path)),
                patch(
                    "cyberquiz.telegram.api",
                    return_value={"video": {"file_id": "telegram-file"}},
                ) as api,
            ):
                video(1, job)
                self.assertFalse((out / "reel.mp4").exists())
                self.assertTrue((out / "plan.json").exists())
                video(2, job)
                self.assertEqual(api.call_args.args[1]["video"], "telegram-file")
                self.assertNotIn("files", api.call_args.kwargs)
