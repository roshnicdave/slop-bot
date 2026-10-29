import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cyberquiz.store import connect, new_job
from cyberquiz.context import snapshot, read
from cyberquiz.incidents import record, resolve


class RecoveryStateTests(unittest.TestCase):
    def test_meta_recovery_does_not_turn_stale_error_into_render_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            (root / "data" / "meta-auth-health.json").write_text(
                json.dumps({"valid": True})
            )
            b = connect(root / "db")
            job = new_job(b, "test")
            b.execute(
                "UPDATE jobs SET status='rendered',approved=1,error=?,plan=? WHERE id=?",
                (
                    "Old Meta account checkpoint",
                    json.dumps({"question": "ARP works. Why no ping reply?"}),
                    job,
                ),
            )
            b.commit()
            record(b, "instagram", "access", 200, "Old Meta checkpoint", job)
            resolve(b, "instagram", phase="access")
            cfg = {
                "publishing_enabled": False,
                "generation_enabled": True,
                "emergency_pause": False,
            }
            with (
                patch("cyberquiz.context.ROOT", root),
                patch("cyberquiz.context.config", return_value=cfg),
            ):
                state = snapshot(b)
                self.assertEqual(state["queue"]["ready_count"], 1)
                self.assertEqual(
                    state["current_publication_blockers"], ["publishing_disabled"]
                )
                self.assertEqual(state["open_incidents"], [])
                self.assertNotIn("Old Meta", json.dumps(state))
                self.assertTrue(read(b, "activity")["incidents"][0]["resolved"])
            self.assertGreater(
                b.execute("SELECT COUNT(*) FROM job_events").fetchone()[0], 0
            )
            b.close()

    def test_cached_valid_access_resolves_incident_without_resuming(self):
        from cyberquiz.auth_health import check
        from cyberquiz.store import now
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            (root / "data/meta-auth-health.json").write_text(json.dumps({
                "checked_at": now(), "credential_revision": "test", "valid": True
            }))
            dbpath = root / "db"
            db = connect(dbpath)
            record(db, "instagram", "access", 200, "Denied")
            db.close()
            with (
                patch("cyberquiz.auth_health.ROOT", root),
                patch("cyberquiz.auth_health.secrets", return_value={"IG_TOKEN_REFRESHED_AT": "test"}),
                patch("cyberquiz.auth_health.connect", side_effect=lambda: connect(dbpath)),
                patch("cyberquiz.telegram.update_config") as update,
                patch("cyberquiz.auth_health.requests.get") as request,
            ):
                self.assertTrue(check())
                update.assert_not_called()
                request.assert_not_called()
            db = connect(dbpath)
            self.assertEqual(db.execute("SELECT state FROM incidents").fetchone()[0], "resolved")
            db.close()

    def test_agent_does_not_replay_previous_ai_operational_claims(self):
        from cyberquiz.agent import run
        from cyberquiz.telegram import tables
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "db")
            tables(db)
            def model(db, op, messages, tools):
                self.assertNotIn("stale invented checkpoint", json.dumps(messages))
                return {"content": "Ready."}
            with (
                patch("cyberquiz.agent.snapshot", return_value={"ready_count": 1}),
                patch("cyberquiz.agent.history", return_value=[{"user": "what happened?", "reply": "stale invented checkpoint"}]),
            ):
                self.assertEqual(run(db, 1, 1001, "can you publish it", turn=model), "Ready.")
            db.close()
