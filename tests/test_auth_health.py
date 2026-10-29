import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from cyberquiz.store import now
from cyberquiz.auth_health import check


class MetaHealthTests(unittest.TestCase):
    def test_revoked_token_pauses_only_publication_and_alerts_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            db = Mock()
            with (
                patch("cyberquiz.auth_health.ROOT", root),
                patch(
                    "cyberquiz.auth_health.config",
                    return_value={"graph_version": "v26.0"},
                ),
                patch(
                    "cyberquiz.auth_health.secrets",
                    return_value={
                        "IG_ACCESS_TOKEN": "private",
                        "IG_TOKEN_REFRESHED_AT": "revision",
                    },
                ),
                patch(
                    "cyberquiz.auth_health.requests.get",
                    return_value=Mock(json=lambda: {"data": {"is_valid": False}}),
                ) as request,
                patch("cyberquiz.auth_health.connect", return_value=db),
                patch("cyberquiz.telegram.update_config") as update,
                patch("cyberquiz.telegram.notify") as notify,
            ):
                self.assertFalse(check())
                self.assertFalse(check())
                self.assertEqual(request.call_count, 1)
                self.assertEqual(notify.call_count, 1)
                update.assert_called_with({"publishing_enabled": False})
                self.assertNotIn(
                    "private", (root / "data" / "meta-auth-health.json").read_text()
                )

    def test_replaced_credential_invalidates_cached_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            (root / "data" / "meta-auth-health.json").write_text(
                json.dumps(
                    {"checked_at": now(), "credential_revision": "old", "valid": False}
                )
            )
            with (
                patch("cyberquiz.auth_health.ROOT", root),
                patch(
                    "cyberquiz.auth_health.config",
                    return_value={"graph_version": "v26.0"},
                ),
                patch(
                    "cyberquiz.auth_health.secrets",
                    return_value={
                        "IG_ACCESS_TOKEN": "private",
                        "IG_TOKEN_REFRESHED_AT": "new",
                    },
                ),
                patch(
                    "cyberquiz.auth_health.requests.get",
                    return_value=Mock(
                        json=lambda: {
                            "data": {
                                "is_valid": True,
                                "expires_at": 0,
                                "data_access_expires_at": 0,
                            }
                        }
                    ),
                ),
                patch("cyberquiz.auth_health.connect", return_value=Mock()),
                patch("cyberquiz.telegram.notify") as notify,
            ):
                self.assertTrue(check())
                notify.assert_not_called()
