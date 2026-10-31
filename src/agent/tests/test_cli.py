import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from zhidiao_agent.cli import main
from zhidiao_agent.models import OperationResult


class CliTests(unittest.TestCase):
    def run_cli(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(args)
        return status, json.loads(output.getvalue())

    def test_offline_mock_passes(self):
        with patch("zhidiao_agent.cli.NiceCodeClient") as client:
            status, result = self.run_cli(["mock"])
        client.assert_not_called()
        self.assertEqual(status, 0)
        self.assertEqual(result["decision"], "PASS")
        self.assertEqual(len(result["audit"]), 4)

    def test_no_implicit_network_permission(self):
        with patch("zhidiao_agent.cli.NiceCodeClient") as client:
            status, result = self.run_cli(["suggest", "task", "--protocol", "openai-chat"])
        client.assert_not_called()
        self.assertEqual(status, 1)
        self.assertEqual(result["error_code"], "APPROVAL_REQUIRED")

    def test_protocol_must_be_explicit(self):
        with patch("zhidiao_agent.cli.NiceCodeClient") as client:
            status, result = self.run_cli(["suggest", "task", "--allow-network"])
        client.assert_not_called()
        self.assertEqual(status, 1)
        self.assertEqual(result["error_code"], "CONFIGURATION_ERROR")

    def test_missing_config_never_constructs_client(self):
        with patch.dict(os.environ, {}, clear=True), patch("zhidiao_agent.cli.NiceCodeClient") as client:
            status, result = self.run_cli([
                "suggest", "task", "--protocol", "openai-chat", "--allow-network",
            ])
        client.assert_not_called()
        self.assertEqual(status, 1)
        self.assertEqual(result["error_code"], "CONFIGURATION_ERROR")

    def test_explicit_request_uses_mock_client_and_hides_key(self):
        config = {
            "NICECODE_BASE_URL": "https://api.example.com/v1",
            "NICECODE_MODEL": "test-model", "NICECODE_API_KEY": "private-test-key",
        }
        with patch.dict(os.environ, config, clear=True), patch("zhidiao_agent.cli.NiceCodeClient") as client:
            client.return_value.generate.return_value = OperationResult(
                True, None, "Done", "mock", data={"content": "Review the GPIO period."},
            )
            status, result = self.run_cli([
                "suggest", "task", "--protocol", "openai-chat", "--allow-network",
            ])
        self.assertEqual(status, 0)
        self.assertTrue(result["requires_human_approval"])
        self.assertNotIn("private-test-key", json.dumps(result))
        client.return_value.generate.assert_called_once()

    def test_path_outside_root_fails(self):
        with TemporaryDirectory(prefix="zhidiao-cli-") as directory:
            root = Path(directory) / "allowed"
            root.mkdir()
            outside = str(Path(directory) / "outside" / "project")
            with patch("zhidiao_agent.cli.Path.cwd", return_value=root):
                status, result = self.run_cli(["mock", "--project", outside])
        self.assertEqual(status, 1)
        self.assertEqual(result["error_code"], "INVALID_ARGUMENT")

    def test_responses_uses_official_defaults_and_mock_transport(self):
        from zhidiao_agent.nicecode import OpenAIResponsesAdapter
        with patch.dict(os.environ, {"NICECODE_API_KEY": "mock-key"}, clear=True), patch("zhidiao_agent.cli.NiceCodeClient") as client:
            client.return_value.generate.return_value = OperationResult(
                True, None, "Done", "mock", data={"content": "A proposal"},
            )
            status, result = self.run_cli([
                "suggest", "task", "--protocol", "openai-responses", "--allow-network",
            ])
        self.assertEqual(status, 0)
        self.assertTrue(result["requires_human_approval"])
        config = client.call_args.args[0]
        self.assertEqual(config.base_url, "https://api.nicecode.ai/v1")
        self.assertEqual(config.model, "gpt-5-codex")
        self.assertIsInstance(client.call_args.kwargs["adapter"], OpenAIResponsesAdapter)
