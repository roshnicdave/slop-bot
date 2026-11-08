import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import requests
from cyberquiz.store import connect, new_job
from cyberquiz.instagram import publish, MetaAPIError


class MetaRejectionTests(unittest.TestCase):
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
