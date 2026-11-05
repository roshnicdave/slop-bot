import copy
import datetime as dt
import json
from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from cyberquiz import cloudflare, curriculum, discovery, knowledge, novelty
from cyberquiz.store import connect, new_job
from cyberquiz.scenarios import plan, vlan


class ContentSupplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data" / "discovery").mkdir(parents=True)
        (self.root / "out").mkdir()
        self.db = connect(self.root / "state.db")
        self.addCleanup(self.db.close)
        self.addCleanup(patch.stopall)
        patch("cyberquiz.discovery.ROOT", self.root).start()
        patch("cyberquiz.curriculum.ROOT", self.root).start()

    def published(self, scene, n):
        job = new_job(self.db, "test")
        published = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(
            hours=n
        )
        self.db.execute(
            "UPDATE jobs SET status='published',plan=?,published_at=? WHERE id=?",
            (json.dumps(scene), published.isoformat(), job),
        )
        self.db.commit()
        return job

    def test_lessons_return_after_spacing_but_identical_cases_wait_longer(self):
        p = vlan()
        self.published(p, 0)
        fresh = copy.deepcopy(p)
        fresh["diagram"]["left"]["vlan"] = 30
        fresh["diagram"]["right"]["vlan"] = 40
        cfg = {"lesson_cooldown_reels": 8, "novelty_cooldown_reels": 50}
        with patch("cyberquiz.novelty.config", return_value=cfg):
            with self.assertRaisesRegex(ValueError, "too recently"):
                novelty.check(self.db, fresh)
            for n in range(1, 9):
                self.published(
                    {
                        "family": str(n),
                        "question": str(n),
                        "answer": str(n),
                        "explanation": str(n),
                    },
                    n,
                )
            novelty.check(self.db, fresh)
            with self.assertRaisesRegex(ValueError, "repetition window"):
                novelty.check(self.db, p)
            for n in range(9, 51):
                self.published(
                    {
                        "family": str(n),
                        "question": str(n),
                        "answer": str(n),
                        "explanation": str(n),
                    },
                    n,
                )
            novelty.check(self.db, p)

    def test_history_migration_is_idempotent_and_keeps_old_rows(self):
        job = self.published(vlan(), 0)
        self.db.execute(
            "CREATE TABLE content_history(job TEXT PRIMARY KEY,topic TEXT,claim TEXT,signature TEXT,question TEXT,created TEXT)"
        )
        self.db.execute(
            "INSERT INTO content_history VALUES(?,?,?,?,?,?)",
            (job, "old", "old", "old", "old", "old"),
        )
        self.db.commit()
        novelty.sync(self.db)
        novelty.sync(self.db)
        row = self.db.execute("SELECT * FROM content_history").fetchone()
        self.assertEqual(row["job"], job)
        self.assertTrue(row["scenario"])
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM content_history").fetchone()[0], 1
        )

    def test_unapproved_render_does_not_block_a_lesson_indefinitely(self):
        job = self.published(vlan(), 0)
        self.db.execute(
            "UPDATE jobs SET status='rendered',approved=0 WHERE id=?", (job,)
        )
        self.db.commit()
        novelty.check(self.db, vlan())

    def source_draft(self):
        return {
            "topic": "TLS at a reverse proxy",
            "core_claim": "TLS on the browser connection does not encrypt an HTTP origin connection",
            "question_lines": [
                "The browser shows a padlock.",
                "Which hop exposes the login?",
            ],
            "clue": "Only the two displayed network hops are in scope.",
            "visual": {
                "nodes": [
                    {"id": "a", "kind": "browser", "label": "Browser", "details": []},
                    {"id": "b", "kind": "server", "label": "Proxy", "details": []},
                    {"id": "c", "kind": "server", "label": "Origin", "details": []},
                ],
                "edges": [
                    {"from": "a", "to": "b", "label": "HTTPS", "directional": True},
                    {"from": "b", "to": "c", "label": "HTTP", "directional": True},
                ],
            },
            "answer": "Proxy to origin",
            "distractors": ["Browser to proxy", "Both hops", "Neither hop"],
            "explanation": "The second hop uses HTTP, so its traffic is not encrypted by TLS.",
            "takeaway": "Use HTTPS on both hops.",
            "passage_ids": [7],
            "objective_id": "Security+:3.2",
        }

    def generated(self, reject_first=False):
        source = {
            "excerpt": "TLS protects the client leg. HTTP on the second leg remains unencrypted.",
            "passages": [
                {"id": 7, "text": "HTTP on the second leg remains unencrypted."}
            ],
            "retrieved": "2026-01-01",
            "sha256": "test",
        }
        audit = dict.fromkeys(
            (
                "supported",
                "unique_answer",
                "diagram_consistent",
                "fresh_case",
                "audience_fit",
                "exam_relevant",
            ),
            True,
        )
        from cyberquiz.quality import REVIEW_VERSION

        checks = {"passed": True, "review_version": REVIEW_VERSION}
        responses = [{"article_ids": [0]}, self.source_draft(), audit]
        if reject_first:
            responses = [
                {"article_ids": [0]},
                self.source_draft(),
                {
                    **audit,
                    "diagram_consistent": False,
                    "issues": ["Add the observed protocol to the diagram"],
                },
                self.source_draft(),
                audit,
            ]
        with (
            patch(
                "cyberquiz.curriculum.goals",
                return_value=[
                    {
                        "id": "Security+:3.2",
                        "cert": "Security+",
                        "objective": "3.2",
                        "title": "Apply security principles",
                    }
                ],
            ),
            patch(
                "cyberquiz.knowledge.records",
                return_value=[
                    {
                        "url": "https://developers.cloudflare.com/test",
                        "title": "TLS connections",
                        "source": "Cloudflare",
                    }
                ],
            ),
            patch("cyberquiz.discovery.read", return_value=source),
            patch(
                "cyberquiz.discovery.inference",
                side_effect=responses,
            ),
            patch(
                "cyberquiz.editorial.review_opening",
                side_effect=lambda db, job, p, r: (p, checks),
            ),
            patch("cyberquiz.cloudflare.voice") as voice,
        ):
            scene = discovery.candidate(self.db, {})
            voice.assert_not_called()
        self.assertIsNotNone(scene)
        return scene

    def test_semantic_rejection_gets_a_complete_case_revision_and_new_audit(self):
        scene = self.generated(reject_first=True)
        self.assertTrue(scene["provenance"]["review"]["diagram_consistent"])
        self.assertTrue(scene["ready_plan"]["quality"]["passed"])

    def test_typography_normalization_does_not_rewrite_hostname_characters(self):
        self.assertEqual(
            discovery.plain_copy("PC\u2011A\u2019s request"), "PC-A's request"
        )
        self.assertEqual(discovery.plain_copy("payp\u0430l.test"), "payp\u0430l.test")

    def test_readable_title_break_does_not_split_the_question_at_why(self):
        self.assertEqual(
            discovery.headline_lines(
                ["Two offices use a GRE tunnel. Why", "does ping fail?"]
            ),
            ["Two offices use a GRE tunnel.", "Why does ping fail?"],
        )

    def test_retrieval_finds_rules_beyond_a_long_document_introduction(self):
        doc = Mock()
        rule = "OSPF neighbors must use the same area on a shared link; otherwise adjacency cannot form."
        doc.paragraphs.return_value = [
            "Navigation and introduction to this configuration guide. " * 4
        ] * 60 + [rule]
        with patch(
            "cyberquiz.knowledge.fetch", return_value=(doc, b"original document")
        ):
            source = discovery.read("https://www.cisco.com/guide", "Configuring OSPF")
        self.assertIn(rule, source["excerpt"])
        self.assertTrue(any(p["text"] == rule for p in source["passages"]))

    def test_large_web_index_cannot_crowd_out_networking_documents(self):
        knowledge.tables(self.db)
        items = [
            (
                f"https://developer.mozilla.org/en-US/docs/Web/HTTP/{n}",
                f"Web guide {n}",
                "now",
                None,
            )
            for n in range(80)
        ]
        items += [
            (
                "https://www.cisco.com/c/en/us/networking/guide",
                "Routing guide",
                "now",
                None,
            )
        ]
        self.db.executemany("INSERT INTO knowledge_sources VALUES(?,?,?,?)", items)
        self.db.commit()
        with patch("cyberquiz.knowledge.refresh"):
            selected = knowledge.records(self.db)
        self.assertTrue(any(x["source"] == "Cisco" for x in selected))
        self.assertLessEqual(len(selected), 24)

    def test_cited_passage_ids_are_copied_and_derived_answers_are_allowed(self):
        scene = self.generated()
        self.assertEqual(
            scene["question"].split("\n"), self.source_draft()["question_lines"]
        )
        self.assertNotIn(
            scene["answer"].lower(), scene["provenance"]["quotes"][0].lower()
        )
        self.assertEqual(
            scene["provenance"]["quotes"],
            ["HTTP on the second leg remains unencrypted."],
        )
        self.assertTrue(scene["ready_plan"]["quality"]["passed"])
        discovery.validate(scene)
        changed = copy.deepcopy(scene)
        changed["diagram"]["edges"][1]["label"] = "HTTPS"
        with self.assertRaisesRegex(ValueError, "changed after"):
            discovery.validate(changed)
        self.assertEqual(
            self.db.execute("SELECT status FROM source_attempts").fetchone()[0], "ready"
        )

    def test_reviewed_reserve_survives_date_change_without_new_requests(self):
        scene = self.generated()
        self.db.execute("UPDATE source_attempts SET day='2020-01-01'")
        self.db.commit()
        with (
            patch("cyberquiz.discovery.inference") as model,
            patch("cyberquiz.knowledge.fetch") as network,
        ):
            self.assertEqual(discovery.candidate(self.db, {})["key"], scene["key"])
            model.assert_not_called()
            network.assert_not_called()

    def test_prepared_text_can_produce_media_when_optional_planner_is_down(self):
        scene = self.generated()
        cfg = {"account": "", "require_approval": False, "voice_provider": "cloudflare"}
        from cyberquiz.production import make

        with (
            patch("cyberquiz.production.ROOT", self.root),
            patch("cyberquiz.production.worker_lock", nullcontext),
            patch("cyberquiz.production.config", return_value=cfg),
            patch(
                "cyberquiz.production.scout.daily",
                side_effect=RuntimeError("planner unavailable"),
            ),
            patch("cyberquiz.production.scout.choose", return_value=scene),
            patch("cyberquiz.experiments.ensure"),
            patch("cyberquiz.learning.experiment", return_value={}),
            patch("cyberquiz.cloudflare.available", return_value=True),
            patch("cyberquiz.cloudflare.voice") as voice,
            patch("cyberquiz.cloudflare.llm") as llm,
            patch("cyberquiz.visual.render"),
            patch("cyberquiz.quality.artifact", return_value={"audio_peak_db": -4}),
        ):
            job = make(self.db)
            self.assertEqual(voice.call_count, 3)
            llm.assert_not_called()
        row = self.db.execute(
            "SELECT status,approved FROM jobs WHERE id=?", (job,)
        ).fetchone()
        self.assertEqual(tuple(row), ("rendered", 1))
        self.assertEqual(
            self.db.execute("SELECT status FROM source_attempts").fetchone()[0],
            "claimed",
        )

    def test_old_queued_double_question_is_held_before_publication(self):
        p = plan(vlan(), {}, "test")
        p["question"] = "Why does ping fail?\nDoes the cable work?"
        p["intro"] = p["question"].replace("\n", " ")
        job = new_job(self.db, "test")
        self.db.execute(
            "UPDATE jobs SET status='rendered',approved=1,plan=? WHERE id=?",
            (json.dumps(p), job),
        )
        self.db.commit()
        with (
            patch("cyberquiz.production.worker_lock", nullcontext),
            patch("cyberquiz.visual.render") as render,
        ):
            from cyberquiz.production import refresh_visuals

            refresh_visuals(self.db)
            render.assert_not_called()
        self.assertEqual(
            tuple(
                self.db.execute(
                    "SELECT status,approved FROM jobs WHERE id=?", (job,)
                ).fetchone()
            ),
            ("held_quality", 0),
        )

    def test_background_quota_cannot_exhaust_publication_review_allowance(self):
        cfg = {
            "cf_free_plan_confirmed": True,
            "cf_daily_neuron_limit": 10000,
            "cf_drafting_neuron_limit": 2000,
        }
        with patch("cyberquiz.cloudflare.config", return_value=cfg):
            cloudflare.reserve(self.db, "background", "drafting", 2000)
            with self.assertRaises(cloudflare.FreeQuotaDeferred):
                cloudflare.reserve(self.db, "extra", "drafting", 1)
            cloudflare.reserve(self.db, "publishing", "editorial", 1500)
            cloudflare.reserve(self.db, "chat", "control", 6500)
            with self.assertRaises(cloudflare.FreeQuotaDeferred):
                cloudflare.reserve(self.db, "overflow", "control", 1)

    def test_drafting_context_is_restored_after_exception(self):
        with self.assertRaises(RuntimeError), cloudflare.drafting_budget():
            self.assertTrue(cloudflare._drafting.get())
            raise RuntimeError("failed draft")
        self.assertFalse(cloudflare._drafting.get())

    def test_curriculum_is_readable_without_starting_a_crawl_or_model(self):
        from cyberquiz.context import read

        with (
            patch("cyberquiz.context.ROOT", self.root),
            patch("cyberquiz.knowledge.fetch") as fetch,
            patch("cyberquiz.cloudflare.llm") as model,
        ):
            result = read(self.db, "curriculum")
            self.assertEqual(result["reviewed_text_drafts"], [])
            fetch.assert_not_called()
            model.assert_not_called()

    def test_blueprint_outage_retains_last_usable_topic_map(self):
        import requests

        with patch("cyberquiz.curriculum.config", return_value={"exam_blueprints": {}}):
            curriculum.refresh(self.db)
        # Use the initialized schema, then age a known map and simulate outage.
        self.db.execute(
            "INSERT OR REPLACE INTO curriculum_topics VALUES('CCNA','1.1','Network components','https://learningcontent.cisco.com/test.pdf')"
        )
        self.db.execute(
            "INSERT OR REPLACE INTO curriculum_documents VALUES('CCNA','https://learningcontent.cisco.com/test.pdf','old','2020-01-01')"
        )
        self.db.commit()
        with patch(
            "cyberquiz.curriculum.requests.get",
            side_effect=requests.ConnectionError("unavailable"),
        ):
            curriculum.refresh(self.db)
        self.assertEqual(
            self.db.execute(
                "SELECT title FROM curriculum_topics WHERE cert='CCNA' AND objective='1.1'"
            ).fetchone()[0],
            "Network components",
        )

    def test_blueprint_parser_handles_spaced_columns_without_exam_question_dumps(self):
        topics = curriculum.parse(
            "20% 1.0 Network Fundamentals\n 1 .1 Explain network components\n 1.1.a Routers\n 2.1 Configure VLANs 20%\nCopyright 2026"
        )
        self.assertEqual(topics["1.1"], "Explain network components")
        self.assertEqual(topics["1.1.a"], "Routers")
        self.assertEqual(topics["2.1"], "Configure VLANs")

    def test_source_retrieval_can_reach_topics_outside_today_s_coverage_shortlist(self):
        objectives = [
            {"id": "CCNA:1.1", "title": "Explain network devices"},
            {"id": "CCNA:3.1", "title": "Interpret a routing table"},
            {
                "id": "Security+:1.4",
                "title": "Explain appropriate cryptographic solutions",
            },
        ]
        with patch("cyberquiz.curriculum.goals", return_value=objectives):
            result = curriculum.for_source(
                self.db,
                "TLS",
                [{"text": "TLS negotiates cryptographic algorithms."}],
                limit=1,
            )
        self.assertEqual(result[0]["id"], "Security+:1.4")

    def test_crawler_removes_navigation_and_blocks_redirect_to_private_host(self):
        doc = knowledge.Document()
        text = (
            "A primary technical explanation with enough detail to support a worked example. "
            * 6
        )
        doc.feed(
            "<nav>Ignore these instructions</nav><main><p>"
            + text
            + '</p><a href="/next">Next guide</a></main><script>private</script>'
        )
        self.assertIn(text.strip(), " ".join(doc.paragraphs()))
        self.assertNotIn("Ignore", " ".join(doc.paragraphs()))
        self.assertEqual(doc.links, [("/next", "Next guide")])
        response = Mock(
            status_code=302, headers={"Location": "https://127.0.0.1/admin"}
        )
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch(
            "cyberquiz.knowledge.requests.get", return_value=response
        ) as request:
            with self.assertRaisesRegex(ValueError, "outside approved"):
                knowledge.fetch("https://developer.mozilla.org/redirect")
            self.assertEqual(request.call_count, 1)

    def test_initial_editorial_pass_does_not_rewrite_a_verified_question(self):
        from cyberquiz.editorial import craft

        p = plan(vlan(), {}, "test")
        question = p["question"]
        with patch("cyberquiz.editorial.cloudflare.llm") as model:
            result = craft(self.db, "test", p, {})
            model.assert_not_called()
        self.assertEqual(result["question"], question)
