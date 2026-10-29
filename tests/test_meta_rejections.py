import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import requests
from cyberquiz.store import connect, new_job
from cyberquiz.instagram import publish, MetaAPIError


class MetaRejectionTests(unittest.TestCase):
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
