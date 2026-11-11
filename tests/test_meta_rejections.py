import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import requests
from cyberquiz.store import connect, new_job
from cyberquiz.instagram import publish, MetaAPIError


class MetaRejectionTests(unittest.TestCase):
    def test_scheduler_recovers_a_failed_upload_once_and_keeps_uncertain_publications(
        self,
    ):
        from cyberquiz.__main__ import publish_due

        cfg = {
            "publishing_enabled": True,
            "public_media_base_url": "https://example.com/media",
            "timezone": "UTC",
            "slots": ["00:00"],
            "posts_per_day": 1,
        }
        failure = {
            "status_code": "ERROR",
            "status": "Error: Media upload has failed with error code 2207085",
        }
        clock = dt.datetime(2026, 11, 10, 20, tzinfo=dt.timezone.utc)
        for outcome in ("published", "failed", "publish_unknown"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                b = connect(root / "state.sqlite")
                self.addCleanup(b.close)
                job = new_job(b, "test")
                (root / "out" / job).mkdir(parents=True)
                plan = {"family": "test", "caption": "test", "question": "test"}
                b.execute(
                    "UPDATE jobs SET status='container_created',approved=1,container_id='old',plan=? WHERE id=?",
                    (json.dumps(plan), job),
                )
                b.commit()
                if outcome == "publish_unknown":
                    responses = [{"status_code": "PUBLISHED"}]
                else:
                    responses = [failure, {"id": "replacement"}]
                    if outcome == "failed":
                        responses.append(failure)
                    else:
                        responses.extend(
                            [{"status_code": "FINISHED"}, {"id": "media"}, {}]
                        )
                with (
                    patch("cyberquiz.instagram.config", return_value=cfg),
                    patch(
                        "cyberquiz.instagram.secrets",
                        return_value={
                            "IG_ACCESS_TOKEN": "test",
                            "IG_USER_ID": "account",
                        },
                    ),
                    patch("cyberquiz.instagram.ROOT", root),
                    patch("cyberquiz.instagram.graph", side_effect=responses) as graph,
                    patch("cyberquiz.telegram.notify"),
                    patch("cyberquiz.wakeup.signal"),
                ):
                    if outcome == "publish_unknown":
                        with self.assertRaisesRegex(ValueError, "reconciliation"):
                            publish_due(b, cfg, clock)
                    else:
                        self.assertEqual(
                            publish_due(b, cfg, clock), outcome == "published"
                        )
                    row = b.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
                    self.assertEqual(row["status"], outcome)
                    rejected = b.execute(
                        "SELECT container_id,code FROM rejected_instagram_uploads ORDER BY observed"
                    ).fetchall()
                    if outcome == "published":
                        self.assertEqual(row["media_id"], "media")
                        self.assertEqual(
                            [tuple(r) for r in rejected], [("old", 2207085)]
                        )
                    elif outcome == "failed":
                        self.assertFalse(row["approved"])
                        self.assertIn("replacement upload also failed", row["error"])
                        self.assertEqual(len(rejected), 2)
                    else:
                        self.assertEqual(row["container_id"], "old")
                        self.assertEqual(rejected, [])
                    submitted = [
                        call.args[1]
                        for call in graph.call_args_list
                        if call.args[0] == "POST"
                    ]
                    expected = {
                        "published": ["account/media", "account/media_publish"],
                        "failed": ["account/media"],
                        "publish_unknown": [],
                    }
                    self.assertEqual(submitted, expected[outcome])
                    if outcome != "published":
                        self.assertFalse(publish_due(b, cfg, clock))
                        self.assertEqual(graph.call_count, len(responses))

    def test_a_historical_quality_pass_cannot_submit_a_new_reel(self):
        from cyberquiz.scenarios import plan, vlan
        from cyberquiz.quality import REVIEW_VERSION

        with tempfile.TemporaryDirectory() as folder:
            b = connect(Path(folder) / "state.sqlite")
            job = new_job(b, "test")
            p = plan(vlan(), {}, job)
            p["quality"] = {
                "passed": True,
                "review_version": REVIEW_VERSION - 1,
                "artifact": {"decode_ok": True},
            }
            b.execute(
                "UPDATE jobs SET status='rendered',approved=1,plan=? WHERE id=?",
                (json.dumps(p), job),
            )
            b.commit()
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
                    return_value={"IG_ACCESS_TOKEN": "test", "IG_USER_ID": "test"},
                ),
                patch("cyberquiz.instagram.graph") as graph,
            ):
                with self.assertRaisesRegex(ValueError, "current editorial review"):
                    publish(b, job, immediate=True)
                graph.assert_not_called()
            b.close()

    def test_creation_rejection_returns_job_to_ready_but_transport_failure_remains_uncertain(
        self,
    ):
        for error, expected in [
            (MetaAPIError(400, 200), "rendered"),
            (requests.Timeout(), "container_submitting"),
        ]:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                b = connect(root / "state.sqlite")
                job = new_job(b, "test")
                plan = {"visual": False, "family": "test", "caption": "test"}
                b.execute(
                    "UPDATE jobs SET status='rendered',approved=1,plan=? WHERE id=?",
                    (json.dumps(plan), job),
                )
                b.commit()
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
                    patch("cyberquiz.instagram.graph", side_effect=error) as graph,
                    patch("cyberquiz.telegram.update_config") as update,
                ):
                    with self.assertRaises(Exception):
                        publish(b, job, immediate=True)
                    self.assertEqual(
                        b.execute(
                            "SELECT status FROM jobs WHERE id=?", (job,)
                        ).fetchone()[0],
                        expected,
                    )
                    graph.assert_called_once()
                    if isinstance(error, MetaAPIError):
                        update.assert_called_once_with({"publishing_enabled": False})
                    else:
                        update.assert_not_called()
                b.close()

    def test_pause_during_meta_processing_prevents_final_publication(self):
        for changed in ({"publishing_enabled": False}, {"emergency_pause": True}):
            with tempfile.TemporaryDirectory() as folder:
                b = connect(Path(folder) / "state.sqlite")
                job = new_job(b, "test")
                p = {
                    "visual": False,
                    "family": "test",
                    "caption": "test",
                    "question": "test",
                }
                b.execute(
                    "UPDATE jobs SET status='container_created',approved=1,container_id='known',plan=? WHERE id=?",
                    (json.dumps(p), job),
                )
                b.commit()
                cfg = {
                    "publishing_enabled": True,
                    "public_media_base_url": "https://example.com/media",
                }
                with (
                    patch(
                        "cyberquiz.instagram.config",
                        side_effect=[cfg, {**cfg, **changed}],
                    ),
                    patch(
                        "cyberquiz.instagram.secrets",
                        return_value={
                            "IG_ACCESS_TOKEN": "hidden",
                            "IG_USER_ID": "test",
                        },
                    ),
                    patch(
                        "cyberquiz.instagram.graph",
                        return_value={"status_code": "FINISHED"},
                    ) as graph,
                ):
                    with self.assertRaisesRegex(
                        ValueError, "paused before final submission"
                    ):
                        publish(b, job, immediate=True)
                self.assertEqual(
                    [call.args[0] for call in graph.call_args_list], ["GET"]
                )
                self.assertEqual(
                    b.execute("SELECT status FROM jobs WHERE id=?", (job,)).fetchone()[
                        0
                    ],
                    "container_created",
                )
                b.close()
