import json
import unittest
from unittest.mock import Mock

from zhidiao_agent.agent import Agent
from zhidiao_agent.models import OperationResult
from zhidiao_agent.config import NiceCodeConfig
from zhidiao_agent.nicecode import NiceCodeClient, OpenAIChatAdapter, HttpResponse


class AgentTests(unittest.TestCase):
    def test_decision_caps_native_client_to_remaining_orchestrator_budget(self):
        transport = Mock()
        stop = json.dumps({"action": "stop", "reason": "Need hardware inspection"})
        transport.send.return_value = HttpResponse(200, json.dumps({
            "choices": [{"message": {"content": stop}}],
        }).encode())
        client = NiceCodeClient(NiceCodeConfig("https://api.example.com/v1", "mock", "fake-key"),
                                adapter=OpenAIChatAdapter(), transport=transport)
        actual = Agent(client).decide("task", {"period_ms": 800}, {}, timeout_s=2)
        self.assertTrue(actual.success, actual.to_dict())
        self.assertEqual(transport.send.call_args.args[3], 2)

    def test_model_text_is_only_a_suggestion(self):
        client = Mock()
        client.generate.return_value = OperationResult(
            True, None, "Done", "mock", data={"content": "git push; delete files"},
        )
        result = Agent(client).suggest("Review GPIO timing", {"period_ms": 800})
        self.assertTrue(result.success)
        self.assertTrue(result.data["requires_human_approval"])
        self.assertEqual(result.data["suggestion"], "git push; delete files")
        client.generate.assert_called_once()
        self.assertEqual(client.generate.call_args.args[0][0]["role"], "system")

    def test_invalid_input_never_calls_model(self):
        client = Mock()
        for task, context in [("", {}), ("task", []), ("task", {"bad": object()})]:
            with self.subTest(task=task):
                self.assertEqual(Agent(client).suggest(task, context).error_code, "INVALID_ARGUMENT")
        client.generate.assert_not_called()

    def test_client_failures_are_unified(self):
        client = Mock()
        client.generate.return_value = OperationResult(False, "TIMEOUT", "Timeout", "mock")
        self.assertEqual(Agent(client).suggest("task").error_code, "TIMEOUT")
        client.generate.side_effect = RuntimeError("private")
        result = Agent(client).suggest("task")
        self.assertEqual(result.error_code, "INTERNAL_ERROR")
        self.assertNotIn("private", result.message)

    def test_malformed_model_result(self):
        client = Mock()
        for response in (None, OperationResult(True, None, "Done", "mock")):
            with self.subTest(response=response):
                client.generate.return_value = response
                self.assertEqual(Agent(client).suggest("task").error_code, "INVALID_RESPONSE")
