import concurrent.futures
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cyberquiz.store import connect, reserve, new_job
from cyberquiz import content
from cyberquiz.providers import fal

CFG = {"monthly_budget_usd": 0.05, "per_job_budget_usd": 0.03}


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.db"
        self.db = connect(self.path)
        self.job = new_job(self.db, "a")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_job_cap_and_duplicate(self):
        reserve(self.db, self.job, "a", 20000, CFG)
        with self.assertRaises(ValueError):
            reserve(self.db, self.job, "a", 1, CFG)
        with self.assertRaises(ValueError):
            reserve(self.db, self.job, "b", 10001, CFG)
        reserve(self.db, self.job, "c", 10000, CFG)

    def test_failed_and_unknown_still_count(self):
        reserve(self.db, self.job, "a", 30000, CFG)
        job = new_job(self.db, "b")
        reserve(self.db, job, "b", 20000, CFG)
        with self.assertRaises(ValueError):
            reserve(self.db, job, "c", 1, CFG)

    def test_concurrent_workers_cannot_overspend(self):
        jobs = [new_job(self.db, str(i)) for i in range(5)]

        def work(job):
            db = connect(self.path)
            try:
                reserve(db, job, "test", 20000, CFG)
                return True
            except ValueError:
                return False
            finally:
                db.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            self.assertEqual(sum(pool.map(work, jobs)), 2)

    def test_high_voice_length_rejected_before_request(self):
        with patch("cyberquiz.providers.fal_prices", return_value={}):
            with self.assertRaises(ValueError):
                fal(self.db, self.job, "voice-intro", {"prompt": "a" * 601})


class ContentTests(unittest.TestCase):
    def test_all_computed_questions_and_unique_choices(self):
        for fact in content.evergreen():
            content.validate(fact)

    def test_recent_content_excludes_old_and_stale_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            day = dt.datetime.now(dt.timezone.utc).date().isoformat()
            for i, p in enumerate(["Router", "Firewall", "Mail Server"]):
                v = {
                    "cveID": f"CVE-2026-{1000 + i}",
                    "product": p,
                    "vendorProject": "Example",
                    "dateAdded": day,
                }
                db.execute(
                    "INSERT INTO sources VALUES(?,?,?,?,?)",
                    (
                        str(i),
                        dt.datetime.now(dt.timezone.utc).isoformat(),
                        day,
                        content.KEV,
                        json.dumps(v),
                    ),
                )
            db.commit()
            self.assertEqual(len(content.candidates(db, True)), 3)
            db.execute("UPDATE sources SET fetched=?", ("2020-01-01T00:00:00+00:00",))
            db.commit()
            self.assertEqual(content.candidates(db, True), [])
            db.close()

    def test_narration_caps_and_answer_alignment(self):
        for fact in content.evergreen():
            p = content.plan(
                fact, {"image_prompt": "abstract network", "hook": "Try this"}, "test"
            )
            self.assertEqual(p["options"][p["correct"]], fact["answer"])
            self.assertLessEqual(len(p["intro"]) + len(p["outro"]), 600)


class PublicationTests(unittest.TestCase):
    def test_publishing_disabled_blocks_network(self):
        from cyberquiz.instagram import publish

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            with (
                patch(
                    "cyberquiz.instagram.config",
                    return_value={"publishing_enabled": False},
                ),
                patch("cyberquiz.instagram.graph") as graph,
            ):
                with self.assertRaises(ValueError):
                    publish(db, "missing")
                graph.assert_not_called()
            db.close()

    def test_unknown_publish_outcome_cannot_be_retried(self):
        from cyberquiz.instagram import publish

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            j = new_job(db, "topic")
            db.execute(
                'UPDATE jobs SET approved=1,status="publish_unknown" WHERE id=?', (j,)
            )
            db.commit()
            with (
                patch(
                    "cyberquiz.instagram.config",
                    return_value={"publishing_enabled": True},
                ),
                patch(
                    "cyberquiz.instagram.secrets",
                    return_value={"IG_ACCESS_TOKEN": "test", "IG_USER_ID": "123"},
                ),
                patch("cyberquiz.instagram.graph") as graph,
            ):
                with self.assertRaises(ValueError):
                    publish(db, j)
                graph.assert_not_called()
            db.close()


class LayoutTests(unittest.TestCase):
    def test_small_source_label_font_renders(self):
        from cyberquiz.render import panel

        with tempfile.TemporaryDirectory() as folder:
            fact = content.evergreen()[0]
            plan = content.plan(fact, {"image_prompt": "abstract"}, "test")
            path = Path(folder) / "panel.png"
            panel(plan, path)
            self.assertTrue(path.exists())


class AgentSafetyTests(unittest.TestCase):
    def test_supported_visual_scenes_have_working_fixes(self):
        from cyberquiz.scenarios import bank, validate, plan

        for scene in bank():
            validate(scene)
            p = plan(scene, {}, "test")
            self.assertEqual(len(p["options"]), 4)
            self.assertEqual(p["options"][p["correct"]], scene["answer"])
            self.assertLess(len(p["intro"]) + len(p["outro"]), 600)

    def test_wrong_vlan_fix_rejected(self):
        from cyberquiz.scenarios import vlan, validate

        s = vlan()
        s["fix_diagram"]["right_vlan"] = 999
        with self.assertRaises(ValueError):
            validate(s)

    def test_cloudflare_shared_free_ceiling_and_idempotency(self):
        from cyberquiz.cloudflare import reserve as free_reserve

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            with patch(
                "cyberquiz.cloudflare.config",
                return_value={
                    "cf_free_plan_confirmed": True,
                    "cf_daily_neuron_limit": 100,
                },
            ):
                free_reserve(db, "a", "chat", 60)
                with self.assertRaises(ValueError):
                    free_reserve(db, "a", "chat", 1)
                with self.assertRaises(ValueError):
                    free_reserve(db, "b", "research", 41)
                free_reserve(db, "c", "voice", 40)
            db.close()

    def test_unauthorized_telegram_user_cannot_queue_work(self):
        from cyberquiz.telegram import handle, tables

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            tables(db)
            with (
                patch(
                    "cyberquiz.telegram.config",
                    return_value={"telegram_allowed_user_ids": [1001, 1002]},
                ),
                patch("cyberquiz.telegram.send") as send,
            ):
                handle(
                    db,
                    {
                        "update_id": 1,
                        "message": {
                            "from": {"id": 999},
                            "chat": {"id": 999, "type": "private"},
                            "text": "/next",
                        },
                    },
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM telegram_updates").fetchone()[0], 0
                )
                send.assert_not_called()
            db.close()

    def test_group_cannot_control_even_with_authorized_sender(self):
        from cyberquiz.telegram import handle, tables

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            tables(db)
            with (
                patch(
                    "cyberquiz.telegram.config",
                    return_value={"telegram_allowed_user_ids": [1001]},
                ),
                patch("cyberquiz.telegram.send"),
            ):
                handle(
                    db,
                    {
                        "update_id": 1,
                        "message": {
                            "from": {"id": 1001},
                            "chat": {"id": -1, "type": "group"},
                            "text": "/resume",
                        },
                    },
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM telegram_updates").fetchone()[0], 0
                )
            db.close()


class StreamingAudioTests(unittest.TestCase):
    def test_open_ended_tts_wav_is_finalized_without_new_inference(self):
        import wave, struct
        from cyberquiz.cloudflare import normalize_wav

        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "tts.wav"
            with wave.open(str(p), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(bytes(4800))
            data = bytearray(p.read_bytes())
            data[4:8] = struct.pack("<I", 0x7FFFFFFF)
            data[40:44] = struct.pack("<I", 0x7FFFFFFF)
            p.write_bytes(data)
            seconds = normalize_wav(p)
            self.assertAlmostEqual(seconds, 0.1)
            with wave.open(str(p)) as w:
                self.assertEqual(w.getnframes(), 2400)


class FreeProviderTests(unittest.TestCase):
    def test_paid_or_unknown_cloudflare_model_is_denied(self):
        from cyberquiz.cloudflare import request

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            with patch("cyberquiz.cloudflare.requests.post") as post:
                with self.assertRaises(ValueError):
                    request(
                        db,
                        "test",
                        "chat",
                        "@cf/deepseek-ai/deepseek-v4-pro-0813",
                        {},
                        1,
                    )
                post.assert_not_called()
            db.close()

    def test_chat_cannot_consume_production_free_allocation(self):
        from cyberquiz.cloudflare import reserve as free_reserve

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            with patch(
                "cyberquiz.cloudflare.config",
                return_value={
                    "cf_free_plan_confirmed": True,
                    "cf_daily_neuron_limit": 8000,
                },
            ):
                free_reserve(db, "a", "chat", 3000)
                with self.assertRaises(ValueError):
                    free_reserve(db, "b", "chat", 1)
                free_reserve(db, "c", "voice", 2000)
                free_reserve(db, "d", "research", 500)
            db.close()


class AutonomyTests(unittest.TestCase):
    def test_all_scenes_fit_and_wrong_lab_evidence_is_rejected(self):
        from cyberquiz.scenarios import bank, plan, validate
        from cyberquiz.quality import layout
        import copy

        for s in bank():
            layout(plan(s, {}, "test"))
        p = next(x for x in bank() if x["key"] == "acl-order")
        p = copy.deepcopy(p)
        p["model"]["rules"].reverse()
        with self.assertRaises(ValueError):
            validate(p)

    def test_only_confirmed_publication_is_cleaned(self):
        from cyberquiz.maintenance import cleanup

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "out").mkdir()
            db = connect(root / "state.db")
            jobs = []
            for status in (
                "published",
                "publish_unknown",
                "container_created",
                "rendered",
            ):
                j = new_job(db, status)
                jobs.append(j)
                (root / "out" / j).mkdir()
                (root / "out" / j / "reel.mp4").write_bytes(b"video")
                db.execute(
                    "UPDATE jobs SET status=?,media_id=?,published_at=? WHERE id=?",
                    (status, "123", "2026-01-01T00:00:00+00:00", j),
                )
            db.commit()
            with patch("cyberquiz.maintenance.ROOT", root):
                cleanup(db)
            self.assertFalse((root / "out" / jobs[0] / "reel.mp4").exists())
            for j in jobs[1:]:
                self.assertTrue((root / "out" / j / "reel.mp4").exists())
            self.assertTrue((root / "out" / jobs[0] / "receipt.json").exists())
            db.close()

    def test_conversation_remembers_both_sides_separately(self):
        from cyberquiz.chat import remember, history

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            remember(db, 1, 10, "question", "answer", "answer", 100)
            self.assertEqual(
                history(db, 10)[0], {"user": "question", "assistant": "answer"}
            )
            self.assertEqual(history(db, 11), [])
            db.close()

    def test_metrics_total_value_and_missing_follows(self):
        from cyberquiz.learning import metric, analyze

        self.assertEqual(
            metric({"reach": {"data": [{"total_value": {"value": 20}}]}}, "reach"), 20
        )
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            j = new_job(db, "quiz")
            p = {"format": "topology-pause-5", "family": "visual-vlan"}
            db.execute(
                'UPDATE jobs SET status="published",media_id="1",plan=? WHERE id=?',
                (json.dumps(p), j),
            )
            payload = {
                k: {"data": [{"total_value": {"value": v}}]}
                for k, v in [("reach", 1000), ("shares", 20)]
            }
            db.execute(
                "INSERT INTO metrics VALUES(?,?,?,?)",
                ("1", "today", 72, json.dumps(payload)),
            )
            db.commit()
            r = analyze(db)
            self.assertEqual(r["comparable_posts"], 1)
            self.assertIsNone(r["posts"][0]["follows_per_1000"])
            db.close()


class ProductionRegressionTests(unittest.TestCase):
    def test_model_linebreaks_cannot_break_hook_layout(self):
        from cyberquiz.editorial import craft
        from cyberquiz.scenarios import plan, vlan
        from cyberquiz.quality import layout

        with patch(
            "cyberquiz.editorial.cloudflare.llm",
            return_value={
                "hook_lines": ["Links\nare up.", "Why does ping fail?"],
                "caption_opening": "Link lights can mislead.",
                "discussion_prompt": "Which clue rules out the cable?",
            },
        ):
            p = craft(None, "test", plan(vlan(), {}, "test"), {"ideas": []})
        self.assertEqual(len(p["question"].split("\n")), 2)
        layout(p)

    def test_procedural_cases_still_validate_and_fit(self):
        from cyberquiz.scenarios import bank, plan, validate
        from cyberquiz.labs import variant
        from cyberquiz.quality import layout

        for scene in bank():
            for seed in (0, 1, 42, 2**32 - 1):
                s = (
                    variant(scene, seed)
                    if scene["family"].startswith("lab-")
                    else scene
                )
                validate(s)
                layout(plan(s, {}, "test"))

    def test_normal_messages_queue_and_only_budget_is_a_command(self):
        from cyberquiz.telegram import handle, tables

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            tables(db)
            with (
                patch(
                    "cyberquiz.telegram.config",
                    return_value={"telegram_allowed_user_ids": [10]},
                ),
                patch("cyberquiz.telegram.send") as send,
            ):
                handle(
                    db,
                    {
                        "update_id": 1,
                        "message": {
                            "from": {"id": 10},
                            "chat": {"id": 10, "type": "private"},
                            "text": "What should we change next?",
                        },
                    },
                )
                self.assertEqual(
                    db.execute("SELECT status FROM telegram_updates").fetchone()[0],
                    "queuedchat",
                )
                send.assert_not_called()
            db.close()


class AudioVideoSyncTests(unittest.TestCase):
    @unittest.skipUnless(__import__("shutil").which("ffmpeg"), "ffmpeg required")
    def test_audio_samples_and_scene_cues_share_one_timeline(self):
        import wave, struct
        from cyberquiz.scenarios import plan, vlan
        from cyberquiz.visual import render
        from cyberquiz.quality import artifact

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            p = plan(vlan(), {}, "test")
            p["decision_seconds"] = 4
            (root / "plan.json").write_text(json.dumps(p))
            for label, seconds, value in [
                ("intro", 1, 1000),
                ("reveal_voice", 2, 2000),
                ("fix_voice", 3, 3000),
            ]:
                with wave.open(str(root / (label + ".wav")), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(24000)
                    w.writeframes(struct.pack("<h", value) * (seconds * 24000))
            render(root)
            timing = json.loads((root / "timing.json").read_text())
            self.assertEqual(timing["reveal_at"], 5)
            self.assertEqual(timing["fix_at"], 7)
            self.assertEqual([x["start"] for x in timing["segments"]], [0, 1, 5, 7])
            with wave.open(str(root / "speech.wav")) as w:
                for seconds, value in [(0, 1000), (2, 0), (5, 2000), (7, 3000)]:
                    w.setpos(seconds * 24000)
                    self.assertEqual(struct.unpack("<h", w.readframes(1))[0], value)
            self.assertTrue(artifact(root)["decode_ok"])


class DeploymentAndQuotaTests(unittest.TestCase):
    def test_measured_success_releases_only_verified_headroom(self):
        from cyberquiz.cloudflare import reserve as free_reserve

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            with patch(
                "cyberquiz.cloudflare.config",
                return_value={
                    "cf_free_plan_confirmed": True,
                    "cf_daily_neuron_limit": 100,
                },
            ):
                free_reserve(db, "a", "chat", 90)
                db.execute(
                    'UPDATE cf_calls SET accounted_neurons=10,status="complete" WHERE operation="a"'
                )
                db.commit()
                free_reserve(db, "b", "chat", 90)
                with self.assertRaises(ValueError):
                    free_reserve(db, "c", "chat", 1)
            db.close()

    def test_deploy_preserves_pause_and_lowered_limits(self):
        import subprocess, sys

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "deploy").mkdir()
            source = Path(__file__).resolve().parents[1] / "deploy" / "merge_config.py"
            (root / "deploy" / "merge_config.py").write_text(source.read_text())
            default = {
                "emergency_pause": False,
                "generation_enabled": True,
                "publishing_enabled": False,
                "require_approval": False,
                "monthly_budget_usd": 1.8,
                "per_job_budget_usd": 0.03,
                "cf_daily_neuron_limit": 8000,
            }
            current = {
                **default,
                "emergency_pause": True,
                "generation_enabled": False,
                "monthly_budget_usd": 0.5,
            }
            (root / "config.defaults.json").write_text(json.dumps(default))
            (root / "config.json").write_text(json.dumps(current))
            subprocess.run(
                [sys.executable, str(root / "deploy" / "merge_config.py")], check=True
            )
            result = json.loads((root / "config.json").read_text())
            self.assertTrue(result["emergency_pause"])
            self.assertFalse(result["generation_enabled"])
            self.assertEqual(result["monthly_budget_usd"], 0.5)


class CopyAndRecoveryTests(unittest.TestCase):
    def test_unverified_counts_are_not_used_in_creative_copy(self):
        from cyberquiz.editorial import craft
        from cyberquiz.scenarios import plan, bank

        s = next(x for x in bank() if x["key"] == "longest-prefix")
        p = plan(s, {}, "test")
        with patch(
            "cyberquiz.editorial.cloudflare.llm",
            return_value={
                "hook_lines": ["Two routers match.", "Which wins?"],
                "caption_opening": "Two routers fight.",
                "discussion_prompt": "Which route wins?",
            },
        ):
            result = craft(None, "test", p, {"ideas": []})
        self.assertEqual(result["question"], s["question"])
        self.assertFalse(result["caption"].startswith("Two routers"))

    def test_resume_cannot_turn_published_media_into_a_new_post(self):
        from cyberquiz.production import resume

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            j = new_job(db, "test")
            db.execute(
                'UPDATE jobs SET status="published",media_id="123",plan="{}" WHERE id=?',
                (j,),
            )
            db.commit()
            with patch("cyberquiz.production.cloudflare.voice") as voice:
                with self.assertRaises(ValueError):
                    resume(db, j)
                voice.assert_not_called()
            self.assertEqual(
                db.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0],
                "published",
            )
            db.close()


class CredentialIngressTests(unittest.TestCase):
    def test_token_is_not_stored_or_sent_to_control_plane(self):
        from cyberquiz.telegram import handle, tables

        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "s.db")
            tables(db)
            with (
                patch(
                    "cyberquiz.telegram.config",
                    return_value={"telegram_allowed_user_ids": [10]},
                ),
                patch("cyberquiz.telegram.send") as send,
            ):
                handle(
                    db,
                    {
                        "update_id": 1,
                        "message": {
                            "from": {"id": 10},
                            "chat": {"id": 10, "type": "private"},
                            "text": "sk-" + "a" * 32,
                        },
                    },
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM telegram_updates").fetchone()[0], 0
                )
                self.assertNotIn("a" * 32, send.call_args[0][1])
            db.close()


class SchedulingIsolationTests(unittest.TestCase):
    def test_source_outage_does_not_block_an_eligible_queued_post(self):
        import cyberquiz.__main__ as runner

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            db = connect(root / "data" / "s.db")
            j = new_job(db, "quiz")
            db.execute('UPDATE jobs SET status="rendered",approved=1 WHERE id=?', (j,))
            db.commit()
            clock = dt.datetime.now(dt.timezone.utc).strftime("%H:%M")
            cfg = {
                "timezone": "UTC",
                "slots": [clock],
                "posts_per_day": 1,
                "generation_enabled": False,
                "publishing_enabled": True,
            }
            with (
                patch.object(runner, "ROOT", root),
                patch.object(runner, "config", return_value=cfg),
                patch("cyberquiz.maintenance.cleanup"),
                patch("cyberquiz.maintenance.backup"),
                patch(
                    "cyberquiz.content.refresh_sources",
                    side_effect=RuntimeError("Source offline"),
                ),
                patch("cyberquiz.instagram.refresh_token_if_due"),
                patch("cyberquiz.instagram.insights"),
                patch("cyberquiz.instagram.publish") as publish,
            ):
                runner.tick(db)
                publish.assert_called_once_with(db, j)
            db.close()


if __name__ == "__main__":
    unittest.main()
