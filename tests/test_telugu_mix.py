import unittest
from unittest.mock import patch

from cyberquiz import translation
from cyberquiz.production import _telugu_labels


class TeluguConfigTests(unittest.TestCase):
    def test_disabled_by_default(self):
        self.assertEqual(_telugu_labels({}), [])
        self.assertEqual(_telugu_labels({"telugu_mix_enabled": False}), [])

    def test_enabled_default_labels(self):
        self.assertEqual(
            _telugu_labels({"telugu_mix_enabled": True}),
            ["intro", "fix_voice"],
        )

    def test_enabled_respects_configured_labels(self):
        self.assertEqual(
            _telugu_labels({
                "telugu_mix_enabled": True,
                "telugu_segments": ["intro"],
            }),
            ["intro"],
        )

    def test_enabled_rejects_unknown_labels(self):
        self.assertEqual(
            _telugu_labels({
                "telugu_mix_enabled": True,
                "telugu_segments": ["intro", "outro", "credits"],
            }),
            ["intro"],
        )


class TeluguTranslationTests(unittest.TestCase):
    def test_prepare_returns_none_when_translate_returns_nothing(self):
        with patch(
            "cyberquiz.translation.cloudflare.llm", return_value={"telugu": ""}
        ):
            self.assertIsNone(
                translation.prepare(None, "job1", "intro", "Check the TTL field.")
            )

    def test_prepare_requires_review_pass(self):
        responses = [
            {"telugu": "TTL field ni check cheyandi"},
            {"passed": False, "reason": "tone too literal"},
        ]
        with patch(
            "cyberquiz.translation.cloudflare.llm", side_effect=responses
        ) as llm:
            self.assertIsNone(
                translation.prepare(None, "job1", "intro", "Check the TTL field.")
            )
            self.assertEqual(llm.call_count, 2)

    def test_prepare_returns_telugu_on_pass(self):
        responses = [
            {"telugu": "TTL field ni check cheyandi"},
            {"passed": True, "reason": "ok"},
        ]
        with patch(
            "cyberquiz.translation.cloudflare.llm", side_effect=responses
        ):
            self.assertEqual(
                translation.prepare(None, "job1", "intro", "Check the TTL field."),
                "TTL field ni check cheyandi",
            )

    def test_translate_rejects_output_that_drops_protected_term(self):
        with patch(
            "cyberquiz.translation.cloudflare.llm",
            return_value={"telugu": "field ni check cheyandi"},
        ):
            self.assertIsNone(
                translation.translate(None, "job1", "intro", "Check the TTL field.")
            )

    def test_translate_returns_none_on_non_string(self):
        with patch(
            "cyberquiz.translation.cloudflare.llm", return_value={"telugu": 42}
        ):
            self.assertIsNone(
                translation.translate(None, "job1", "intro", "Short line.")
            )

    def test_prepare_swallows_provider_errors(self):
        from cyberquiz.cloudflare import CloudflareRequestError

        with patch(
            "cyberquiz.translation.cloudflare.llm",
            side_effect=CloudflareRequestError("outage"),
        ):
            self.assertIsNone(
                translation.prepare(None, "job1", "intro", "Short line.")
            )


if __name__ == "__main__":
    unittest.main()
