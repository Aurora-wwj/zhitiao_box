import contextlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from zhidiao_agent.cli import main
from zhidiao_agent.demo import ScriptedDemoClient


def parse_stream(text):
    decoder = json.JSONDecoder()
    documents = []
    while text.strip():
        document, position = decoder.raw_decode(text.lstrip())
        documents.append(document)
        text = text.lstrip()[position:]
    return documents


class DemoTests(unittest.TestCase):
    def run_cli(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            status = main(args)
        return status, parse_stream(output.getvalue())

    @staticmethod
    def confirm(prompt):
        return "  批准  "

    def test_noninteractive_demo_returns_diff_without_applying(self):
        with patch("sys.stdin.isatty", return_value=False), patch("zhidiao_agent.cli.NiceCodeClient") as client:
            status, documents = self.run_cli(["agent-demo"])
        client.assert_not_called()
        self.assertEqual(status, 1)
        self.assertEqual(documents[-1]["decision"], "AWAITING_APPROVAL")
        self.assertEqual(documents[-1]["model_mode"], "scripted_mock")
        preview = documents[-1]["pending_edit"]
        self.assertIn("+const unsigned int gpio_period_ms = 1001;", preview["params"]["diff"])
        self.assertNotIn("applied_edit", documents[-1]["cycles"][0])
        self.assertFalse(Path(preview["params"]["project"]).exists())

    def test_reviewed_demo_passes_in_two_cycles_without_network(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=self.confirm), patch("zhidiao_agent.cli.NiceCodeClient") as client:
            status, documents = self.run_cli(["agent-demo"])
        client.assert_not_called()
        result = documents[-1]
        self.assertEqual(status, 0)
        self.assertEqual(result["decision"], "PASS")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["evidence_source"], "mock")
        self.assertEqual(result["model_mode"], "scripted_mock")

    def test_demo_rejection_does_not_run_another_cycle(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="no"):
            status, documents = self.run_cli(["agent-demo"])
        result = documents[-1]
        self.assertEqual(status, 1)
        self.assertEqual(result["error_code"], "APPROVAL_REJECTED")
        self.assertEqual(result["report"]["attempts"], 1)
        self.assertEqual(result["report"]["decision"], "STOPPED")

    def test_real_model_requires_explicit_network_protocol_and_key(self):
        with patch.dict(os.environ, {}, clear=True), patch("zhidiao_agent.cli.NiceCodeClient") as client:
            for args, error in ((["agent-demo", "--protocol", "openai-responses"], "APPROVAL_REQUIRED"),
                                (["agent-demo", "--allow-network"], "CONFIGURATION_ERROR"),
                                (["agent-demo", "--allow-network", "--protocol", "openai-responses"], "CONFIGURATION_ERROR")):
                with self.subTest(args=args):
                    status, documents = self.run_cli(args)
                    self.assertEqual(status, 1)
                    self.assertEqual(documents[-1]["error_code"], error)
        client.assert_not_called()

    def test_live_model_wiring_is_tested_only_with_mock_client(self):
        client = Mock(wraps=ScriptedDemoClient())
        with patch.dict(os.environ, {"NICECODE_API_KEY": "fake-test-key"}, clear=True), patch(
            "zhidiao_agent.cli.NiceCodeClient", return_value=client,
        ), patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=self.confirm):
            status, documents = self.run_cli(["agent-demo", "--allow-network", "--protocol", "openai-responses"])
        self.assertEqual(status, 0)
        self.assertEqual(documents[-1]["model_mode"], "nicecode")
        client.generate.assert_called_once()
        self.assertNotIn("fake-test-key", json.dumps(documents))
