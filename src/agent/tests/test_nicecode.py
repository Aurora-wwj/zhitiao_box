import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError, HTTPError

from zhidiao_agent.config import NiceCodeConfig
from zhidiao_agent.nicecode import (
    HttpResponse, NiceCodeClient, OpenAIChatAdapter, UrllibTransport, MAX_RESPONSE_BYTES,
)


class NiceCodeTests(unittest.TestCase):
    def setUp(self):
        self.transport = Mock()
        self.config = NiceCodeConfig("https://api.example.com/v1", "test", "fake-key")
        self.client = NiceCodeClient(
            self.config, adapter=OpenAIChatAdapter(), transport=self.transport,
        )
        self.messages = [{"role": "user", "content": "Plan a GPIO test"}]

    def test_success_and_request_contract(self):
        self.transport.send.return_value = HttpResponse(
            200, b'{"choices":[{"message":{"content":"A test plan"}}]}',
        )
        result = self.client.generate(self.messages)
        self.assertTrue(result.success)
        self.assertEqual(result.data["content"], "A test plan")
        args = self.transport.send.call_args.args
        self.assertEqual(args[0], "https://api.example.com/v1/chat/completions")
        self.assertEqual(json.loads(args[2]), {
            "model": "test", "messages": self.messages, "stream": False,
        })
        self.assertEqual(args[3], 30.0)

    def test_no_adapter_means_no_network(self):
        result = NiceCodeClient(self.config, transport=self.transport).generate(self.messages)
        self.assertEqual(result.error_code, "CONFIGURATION_ERROR")
        self.transport.send.assert_not_called()

    def test_request_budget_can_only_shorten_timeout(self):
        self.transport.send.return_value = HttpResponse(200, b'{"choices":[{"message":{"content":"ok"}}]}')
        for budget, expected in ((5, 5), (60, 30)):
            self.assertTrue(self.client.generate(self.messages, timeout_s=budget).success)
            self.assertEqual(self.transport.send.call_args.args[3], expected)
        self.transport.reset_mock()
        for budget in (True, 0, -1, float("nan"), float("inf")):
            self.assertEqual(self.client.generate(self.messages, timeout_s=budget).error_code, "INVALID_ARGUMENT")
        self.transport.send.assert_not_called()

    def test_invalid_unicode_in_api_text_is_a_response_error(self):
        self.transport.send.return_value = HttpResponse(200, b'{"choices":[{"message":{"content":"\\ud800"}}]}')
        self.assertEqual(self.client.generate(self.messages).error_code, "INVALID_RESPONSE")

    def test_failures_are_sanitized_and_never_retried(self):
        for exc, code in [
            (TimeoutError("fake-key"), "TIMEOUT"),
            (ConnectionError("fake-key"), "NETWORK_UNREACHABLE"),
            (RuntimeError("fake-key"), "INTERNAL_ERROR"),
        ]:
            with self.subTest(code=code):
                self.transport.reset_mock()
                self.transport.send.side_effect = exc
                result = self.client.generate(self.messages)
                self.assertEqual(result.error_code, code)
                self.assertNotIn("fake-key", result.message)
                self.transport.send.assert_called_once()

    def test_http_failures(self):
        for status in (301, 401, 403, 429, 500, 503):
            with self.subTest(status=status):
                self.transport.send.return_value = HttpResponse(status, b"private response")
                result = self.client.generate(self.messages)
                self.assertEqual(result.error_code, "SERVICE_ERROR")
                self.assertIn(str(status), result.message)
                self.assertEqual(result.data["status_code"], status)
                self.assertNotIn("private response", result.message)

    def test_invalid_responses(self):
        for body, code in [
            (b"not JSON", "INVALID_RESPONSE"),
            (b"{}", "INVALID_RESPONSE"),
            (b'{"choices":[]}', "INVALID_RESPONSE"),
            (b'{"error":{"message":"private"}}', "SERVICE_ERROR"),
            (b"x" * (MAX_RESPONSE_BYTES + 1), "INVALID_RESPONSE"),
        ]:
            with self.subTest(code=code, length=len(body)):
                self.transport.send.return_value = HttpResponse(200, body)
                self.assertEqual(self.client.generate(self.messages).error_code, code)

    def test_invalid_messages_do_not_call_transport(self):
        for messages in ([], None, [{}], [{"role": "tool", "content": "run"}]):
            with self.subTest(messages=messages):
                self.assertEqual(self.client.generate(messages).error_code, "INVALID_ARGUMENT")
        self.transport.send.assert_not_called()

    def test_transport_handles_wrapped_network_and_timeout(self):
        for reason, code in [(TimeoutError(), "TIMEOUT"), (OSError(), "NETWORK_UNREACHABLE")]:
            with self.subTest(code=code), patch("zhidiao_agent.nicecode.build_opener") as factory:
                factory.return_value.open.side_effect = URLError(reason)
                client = NiceCodeClient(self.config, adapter=OpenAIChatAdapter())
                self.assertEqual(client.generate(self.messages).error_code, code)

    def test_transport_preserves_http_status(self):
        with patch("zhidiao_agent.nicecode.build_opener") as factory:
            factory.return_value.open.side_effect = HTTPError(
                "https://api.example.com", 429, "private", {}, None,
            )
            response = UrllibTransport().send("https://api.example.com", {}, b"{}", 1)
            self.assertEqual(response.status, 429)
            self.assertEqual(response.body, b"")

    def test_transport_rejects_oversized_body(self):
        with patch("zhidiao_agent.nicecode.build_opener") as factory:
            response = factory.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b"x" * (MAX_RESPONSE_BYTES + 1)
            client = NiceCodeClient(self.config, adapter=OpenAIChatAdapter())
            self.assertEqual(client.generate(self.messages).error_code, "INVALID_RESPONSE")
            response.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)

    def test_redirect_handler_refuses_redirect(self):
        from zhidiao_agent.nicecode import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(
            None, None, 302, "Redirect", {}, "https://other.example.com",
        ))
