import unittest
from types import SimpleNamespace
from unittest.mock import patch
from cyberquiz import cloudflare


class AgentProtocolTests(unittest.TestCase):
    def test_unreceipted_first_turn_claim_is_rejected(self):
        response = SimpleNamespace(
            json=lambda: {
                "success": True,
                "result": {"response": "I've paused publishing."},
            }
        )
        messages = [
            {"role": "system", "content": "operator"},
            {"role": "user", "content": "wait stop"},
        ]
        with patch("cyberquiz.cloudflare.request", return_value=response) as request:
            with self.assertRaises(cloudflare.CloudflareRequestError):
                cloudflare.agent_turn(None, "test", messages, [{"name": "read_system"}])
        self.assertEqual(request.call_args.args[4]["tool_choice"], "required")

    def test_receipted_followup_can_reply_without_another_call(self):
        response = SimpleNamespace(
            json=lambda: {
                "success": True,
                "result": {"response": "Publishing is paused."},
            }
        )
        messages = [
            {"role": "system", "content": "operator"},
            {"role": "tool", "content": '{"publishing_enabled":false}'},
        ]
        with patch("cyberquiz.cloudflare.request", return_value=response) as request:
            result = cloudflare.agent_turn(
                None, "test", messages, [{"name": "read_system"}]
            )
        self.assertNotIn("tool_choice", request.call_args.args[4])
        self.assertEqual(result["content"], "Publishing is paused.")

    def test_notifications_do_not_force_state_mutation(self):
        response = SimpleNamespace(
            json=lambda: {
                "success": True,
                "result": {"response": "Your Reel is ready."},
            }
        )
        with patch("cyberquiz.cloudflare.request", return_value=response) as request:
            cloudflare.agent_turn(
                None, "event", [{"role": "system", "content": "event"}], []
            )
        self.assertNotIn("tool_choice", request.call_args.args[4])

    def test_provider_tool_followup_normalizes_null_without_mutating_transcript(self):
        response = SimpleNamespace(
            json=lambda: {"success": True, "result": {"response": "Paused."}}
        )
        messages = [
            {"role": "system", "content": "operator"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call",
                        "function": {
                            "name": "set_publishing",
                            "arguments": '{"enabled":false}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call",
                "content": '{"publishing_enabled":false}',
            },
        ]
        with patch("cyberquiz.cloudflare.request", return_value=response) as request:
            cloudflare.agent_turn(None, "test", messages, [{"name": "set_publishing"}])
        sent = request.call_args.args[4]["messages"]
        self.assertEqual(sent[1]["content"], "")
        self.assertEqual(sent[1]["tool_calls"], messages[1]["tool_calls"])
        self.assertEqual(sent[2]["tool_call_id"], "call")
        self.assertIsNone(messages[1]["content"])
