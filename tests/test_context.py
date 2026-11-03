from pathlib import Path
import tempfile
import unittest
from cyberquiz.store import connect, new_job
from cyberquiz.context import snapshot, read
from cyberquiz.chat import tables, preference
from cyberquiz.telegram import tables as telegram_tables


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = connect(Path(self.temp.name) / "db")
        self.addCleanup(self.db.close)
        telegram_tables(self.db)
        tables(self.db)

    def test_live_queue_includes_ready_older_than_last_eight_jobs(self):
        ready = new_job(self.db, "ready")
        self.db.execute(
            "UPDATE jobs SET approved=1,status='rendered' WHERE id=?", (ready,)
        )
        self.db.commit()
        for _ in range(12):
            new_job(self.db, "draft")
        snap = snapshot(self.db)
        self.assertEqual(snap["queue"]["ready"][0]["id"], ready)
        self.assertEqual(snap["queue"]["ready_count"], 1)
        self.assertEqual(snap["readiness_policy"]["target_ready"], 1)

    def test_saved_advice_is_retrievable_without_resaving(self):
        preference(self.db, 1, "Mention relevant certifications.")
        result = read(self.db, "preferences")
        self.assertEqual(result["saved"][0]["text"], "Mention relevant certifications.")
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM preferences").fetchone()[0], 1
        )
        with self.assertRaises(ValueError):
            read(self.db, "credentials")

    def test_agent_can_distinguish_pictorial_video_from_legacy_text(self):
        import json
        from cyberquiz.scenarios import plan, bank

        scene = next(s for s in bank() if s["key"] == "dns-cache")
        for version, representation in [(0, "text_panel"), (2, "technical_diagram")]:
            job = new_job(self.db, "visual")
            p = plan(scene, {}, job)
            p["quality"] = {"artifact": {"diagram_renderer_version": version}}
            self.db.execute(
                "UPDATE jobs SET status='rendered',approved=1,plan=? WHERE id=?",
                (json.dumps(p), job),
            )
            self.db.commit()
            entry = next(r for r in read(self.db, "queue")["ready"] if r["id"] == job)
            self.assertEqual(entry["visual"]["representation"], representation)
            self.assertEqual(
                entry["visual"]["model"]["cached"], scene["model"]["cached"]
            )
