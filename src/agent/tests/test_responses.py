import json
import unittest
from unittest.mock import Mock

from zhidiao_agent.config import NICECODE_BASE_URL, NICECODE_MODEL, NiceCodeConfig
from zhidiao_agent.nicecode import HttpResponse, NiceCodeClient, OpenAIResponsesAdapter


def message(text="GPIO plan", **overrides):
    return {
        "type": "message", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    } | overrides


class ResponsesTests(unittest.TestCase):
    def setUp(self):
        self.transport = Mock()
        self.client = NiceCodeClient(
            NiceCodeConfig(NICECODE_BASE_URL, NICECODE_MODEL, "mock-only-key"),
            adapter=OpenAIResponsesAdapter(), transport=self.transport,
        )
        self.messages = [{"role": "system", "content": "Only propose."},
                         {"role": "user", "content": "Plan GPIO test"}]

    def generate(self, document, status=200):
        self.transport.send.return_value = HttpResponse(status, json.dumps(document).encode())
        return self.client.generate(self.messages)

    def test_nicecode_request_contract(self):
        result = self.generate({"status": "completed", "output": [message()]})
        self.assertTrue(result.success)
        self.assertEqual(result.data["content"], "GPIO plan")
        self.transport.send.assert_called_once()
        url, headers, body, timeout = self.transport.send.call_args.args
        self.assertEqual(url, "https://api.nicecode.ai/v1/responses")
        self.assertEqual(headers["Authorization"], "Bearer mock-only-key")
        self.assertEqual(json.loads(body), {
            "model": "gpt-5-codex", "input": self.messages,
            "stream": False, "store": False,
        })
        self.assertEqual(timeout, 30.0)

    def test_reasoning_is_not_returned_as_final_answer(self):
        result = self.generate({"status": "completed", "output": [
            {"type": "reasoning", "summary": []}, message("First"), message("Second"),
        ]})
        self.assertEqual(result.data["content"], "First\nSecond")

    def test_failed_or_error_responses(self):
        for doc in ({"status": "failed"}, {"error": {"message": "private-key"}}):
            with self.subTest(doc=doc):
                result = self.generate(doc)
                self.assertEqual(result.error_code, "SERVICE_ERROR")
                self.assertNotIn("private-key", result.message)

    def test_incomplete_or_malformed_outputs(self):
        documents = [
            [], {}, {"status": "incomplete", "output": [message()]},
            {"status": "in_progress", "output": [message()]},
            {"status": "completed", "output": None},
            {"status": "completed", "output": []},
            {"status": "completed", "output": [None]},
            {"status": "completed", "output": [message(status="in_progress")]},
            {"status": "completed", "output": [message(content=None)]},
            {"status": "completed", "output": [message(content=[None])]},
            {"status": "completed", "output": [message("")]},
            {"status": "completed", "output": [message(role="user")]},
        ]
        for doc in documents:
            with self.subTest(doc=doc):
                self.assertEqual(self.generate(doc).error_code, "INVALID_RESPONSE")

    def test_tool_call_is_never_executed_or_treated_as_text(self):
        result = self.generate({"status": "completed", "output": [
            {"type": "function_call", "name": "shell", "arguments": "{}"},
        ]})
        self.assertEqual(result.error_code, "INVALID_RESPONSE")

    def test_refusal_is_not_a_successful_suggestion(self):
        result = self.generate({"status": "completed", "output": [message(content=[
            {"type": "refusal", "refusal": "private refusal text"},
        ])]})
        self.assertEqual(result.error_code, "SERVICE_ERROR")
        self.assertNotIn("private refusal text", result.message)

    def test_http_error_preserves_status(self):
        result = self.generate({}, status=429)
        self.assertEqual(result.error_code, "SERVICE_ERROR")
        self.assertEqual(result.data["status_code"], 429)

    def test_timeout_remains_structured(self):
        self.transport.send.side_effect = TimeoutError("private")
        result = self.client.generate(self.messages)
        self.assertEqual(result.error_code, "TIMEOUT")
        self.transport.send.assert_called_once()
