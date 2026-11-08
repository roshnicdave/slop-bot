import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from collections import Counter
from cyberquiz.scenarios import bank, plan
from cyberquiz.clean_visual import frame
from cyberquiz.lab_visual import evidence, VERSION
from cyberquiz.quality import layout, REVIEW_VERSION
from cyberquiz.store import connect, new_job


class DiagramTests(unittest.TestCase):
    def test_all_micro_labs_render_pictorial_evidence(self):
        for scene in bank():
            if not scene["family"].startswith("lab-"):
                continue
            p = plan(scene, {}, "visual-test")
            p["palette"] = "ink"
            for stage in ("question", "fix"):
                image = frame(p, stage, 5).crop((60, 366, 660, 623))
                raw = image.tobytes()
                pixels = Counter(zip(raw[0::3], raw[1::3], raw[2::3]))
                if p["model"]["kind"] == "url":
                    self.assertGreater(pixels[(233, 238, 242)], 1000)
                else:
                    hardware = pixels[(41, 78, 101)] + pixels[(33, 62, 84)]
                    self.assertGreater(hardware, 1000, (scene["key"], stage))

    def test_solver_receives_picture_data_without_hidden_answer_or_repair(self):
        scene = next(s for s in bank() if s["key"] == "longest-prefix")
        data = evidence(scene)["data"]
        self.assertEqual(data["routes"], scene["model"]["routes"])
        self.assertNotIn("expected", data)
        self.assertNotIn("kind", data)
        scene = next(s for s in bank() if s["key"] == "trunk-allow")
        self.assertNotIn("fixed_b", evidence(scene)["data"])

    def test_unsupported_visual_is_held_instead_of_text_fallback(self):
        p = plan(next(s for s in bank() if s["key"] == "dns-cache"), {}, "test")
        p["model"]["kind"] = "unsupported"
        with self.assertRaisesRegex(ValueError, "No technical visual"):
            layout(p)

    def test_solver_knows_which_devices_have_the_displayed_addresses(self):
        scene = next(s for s in bank() if s["key"] == "duplicate-ip")
        diagram = evidence(scene)
        self.assertEqual(
            diagram["nodes"][0],
            {"type": "PC", "label": "PC A", "ip": scene["model"]["a"]},
        )
        self.assertEqual(diagram["nodes"][1]["ip"], scene["model"]["b"])
        self.assertIn("same VLAN", diagram["connection"])
        self.assertNotIn("expected", diagram["data"])

    def test_cache_visual_reads_verified_model_not_legacy_text_panel(self):
        from cyberquiz.lab_visual import label

        p = plan(next(s for s in bank() if s["key"] == "dns-cache"), {}, "test")
        p["model"].update(authoritative="203.0.113.77", cached="203.0.113.55", ttl=321)
        with patch("cyberquiz.lab_visual.label", wraps=label) as drawn:
            frame(p, "question", 5)
        labels = [str(call.args[1]) for call in drawn.call_args_list]
        self.assertIn("203.0.113.77", labels)
        self.assertIn("203.0.113.55", labels)
        self.assertIn("TTL 321 sec", labels)
        self.assertNotIn("203.0.113.10", labels)


class QueuedVisualUpgradeTests(unittest.TestCase):
    def test_upgrade_reuses_audio_and_preserves_paid_ledger(self):
        from cyberquiz.production import refresh_visuals

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = connect(root / "state.sqlite")
            job = new_job(db, "queued")
            p = plan(next(s for s in bank() if s["key"] == "dns-cache"), {}, job)
            p["quality"] = {"passed": True, "artifact": {"decode_ok": True}}
            folder = root / "out" / job
            folder.mkdir(parents=True)
            (folder / "plan.json").write_text(json.dumps(p))
            for name in ("intro", "reveal_voice", "fix_voice"):
                (folder / (name + ".wav")).write_bytes(b"existing")
            db.execute(
                "UPDATE jobs SET plan=?,status='rendered',approved=1 WHERE id=?",
                (json.dumps(p), job),
            )
            db.commit()
            with (
                patch("cyberquiz.production.ROOT", root),
                patch(
                    "cyberquiz.production.worker_lock",
                    side_effect=contextlib.nullcontext,
                ),
                patch("cyberquiz.visual.render") as render,
                patch(
                    "cyberquiz.quality.review",
                    return_value={"passed": True, "review_version": REVIEW_VERSION},
                ) as editorial,
                patch(
                    "cyberquiz.quality.artifact",
                    return_value={
                        "decode_ok": True,
                        "diagram_renderer_version": VERSION,
                    },
                ),
                patch("cyberquiz.cloudflare.voice") as free_voice,
                patch("cyberquiz.premium_voice.generate") as paid_voice,
            ):
                refresh_visuals(db)
                refresh_visuals(db)
                render.assert_called_once_with(folder)
                editorial.assert_called_once()
                free_voice.assert_not_called()
                paid_voice.assert_not_called()
            saved = db.execute(
                "SELECT status,approved,plan FROM jobs WHERE id=?", (job,)
            ).fetchone()
            self.assertEqual(saved["status"], "rendered")
            self.assertEqual(saved["approved"], 1)
            self.assertEqual(
                json.loads(saved["plan"])["quality"]["artifact"][
                    "diagram_renderer_version"
                ],
                VERSION,
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM charges").fetchone()[0], 0
            )
            db.close()

    def test_submitted_text_media_cannot_bypass_visual_gate(self):
        from cyberquiz.instagram import publish

        with tempfile.TemporaryDirectory() as temp:
            db = connect(Path(temp) / "state.sqlite")
            job = new_job(db, "submitted")
            p = plan(next(s for s in bank() if s["key"] == "dns-cache"), {}, job)
            p["quality"] = {"passed": True, "artifact": {"decode_ok": True}}
            db.execute(
                "UPDATE jobs SET plan=?,status='container_created',approved=1,container_id='known' WHERE id=?",
                (json.dumps(p), job),
            )
            db.commit()
            with (
                patch(
                    "cyberquiz.instagram.config",
                    return_value={
                        "publishing_enabled": True,
                        "public_media_base_url": "https://example.com/media",
                    },
                ),
                patch(
                    "cyberquiz.instagram.secrets",
                    return_value={"IG_ACCESS_TOKEN": "hidden", "IG_USER_ID": "test"},
                ),
                patch("cyberquiz.instagram.graph") as graph,
            ):
                with self.assertRaisesRegex(ValueError, "visual reconciliation"):
                    publish(db, job, immediate=True)
                graph.assert_not_called()
            self.assertEqual(
                db.execute(
                    "SELECT container_id FROM jobs WHERE id=?", (job,)
                ).fetchone()[0],
                "known",
            )
            db.close()

    def test_old_approval_cannot_publish_a_statement_as_a_quiz(self):
        from cyberquiz.instagram import publish

        with tempfile.TemporaryDirectory() as temp:
            db = connect(Path(temp) / "state.sqlite")
            job = new_job(db, "statement")
            p = plan(next(s for s in bank() if s["key"] == "pool-exhausted"), {}, job)
            p["question"] = "Pool addresses all leased\nNew client gets no offer"
            p["intro"] = p["question"].replace("\n", " ")
            p["quality"] = {
                "passed": True,
                "artifact": {"decode_ok": True, "diagram_renderer_version": VERSION},
            }
            db.execute(
                "UPDATE jobs SET plan=?,status='rendered',approved=1 WHERE id=?",
                (json.dumps(p), job),
            )
            db.commit()
            with (
                patch(
                    "cyberquiz.instagram.config",
                    return_value={
                        "publishing_enabled": True,
                        "public_media_base_url": "https://example.com/media",
                    },
                ),
                patch(
                    "cyberquiz.instagram.secrets",
                    return_value={
                        "IG_ACCESS_TOKEN": "hidden",
                        "IG_USER_ID": "test",
                    },
                ),
                patch("cyberquiz.instagram.graph") as graph,
            ):
                with self.assertRaisesRegex(ValueError, "ask a question"):
                    publish(db, job, immediate=True)
                graph.assert_not_called()
            db.close()
