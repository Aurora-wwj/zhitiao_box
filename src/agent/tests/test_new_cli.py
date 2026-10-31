"""Parser wiring tests never start a real server, model, SSH or setup action."""

import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

from zhidiao_agent.cli import main
from zhidiao_agent.models import OperationResult


def result(data=None, *, success=True, code=None):
    return OperationResult(success, code, "fixture", "mock", data=data or {})


class NewCliTests(unittest.TestCase):
    def run_cli(self, arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(arguments)
        return status, json.loads(output.getvalue())

    def test_setup_preview_passes_exact_configuration_to_review_wrapper(self):
        with patch("zhidiao_agent.setup_cli.run_setup", return_value=result({"state": "pending"})) as setup:
            status, data = self.run_cli([
                "deployment-setup", "--project", "project", "--keil", "UV4.exe", "--known-hosts", "hosts",
                "--identity", "identity", "--project-file", "GPIO.uvprojx", "--target", "GPIO",
                "--host", "192.168.10.3", "--port", "2222", "--user", "root", "--observed-gpio", "PA1",
                "--output", "new.json", "--check-remote", "--preview-only",
            ])
        self.assertEqual(status, 0)
        self.assertTrue(data["success"])
        setup.assert_called_once_with(
            project_path="project", keil_executable="UV4.exe", known_hosts="hosts", identity_file="identity",
            project_file="GPIO.uvprojx", target="GPIO", host="192.168.10.3", port=2222, user="root",
            observed_gpio="PA1", output_path="new.json", check_remote=True, preview_only=True,
        )

    def test_setup_defaults_and_failures_do_not_claim_ready(self):
        args = ["deployment-setup", "--project", "project", "--keil", "UV4.exe", "--known-hosts", "hosts"]
        for data, success, code in (({"decision": "NOT_READY"}, True, None),
                                    ({"decision": "INCOMPLETE"}, True, None),
                                    ({"params": {"local": {"local_ready": False}}}, True, None),
                                    ({}, False, "CONFIGURATION_ERROR")):
            with self.subTest(data=data), patch("zhidiao_agent.setup_cli.run_setup", return_value=result(
                    data, success=success, code=code)) as setup:
                status, _ = self.run_cli(args)
                self.assertEqual(status, 1)
                options = setup.call_args.kwargs
                self.assertEqual(options["host"], "192.168.10.2")
                self.assertEqual(options["observed_gpio"], "PA1")
                self.assertFalse(options["check_remote"])
                self.assertFalse(options["preview_only"])

    def test_deployment_check_only_calls_approved_diagnostic_wrapper(self):
        with patch("zhidiao_agent.setup_cli.run_diagnostics", return_value=result({"state": "pending"})) as diagnostics:
            status, _ = self.run_cli(["deployment-check", "--config", "local.json", "--preview-only"])
        self.assertEqual(status, 0)
        diagnostics.assert_called_once_with("local.json", preview_only=True)
        with patch("zhidiao_agent.setup_cli.run_diagnostics", return_value=result({"decision": "NOT_READY"})):
            self.assertEqual(self.run_cli(["deployment-check", "--config", "local.json"])[0], 1)

    def test_report_is_read_only_and_preserves_snapshot_envelope(self):
        with patch("zhidiao_agent.reports.read_report", return_value=result({
            "report": {"decision": "FAIL"}, "restores_approvals": False,
        })) as reader, patch("zhidiao_agent.cli._model_client") as client:
            status, data = self.run_cli(["report", "prior.json"])
        self.assertEqual(status, 0)
        reader.assert_called_once_with("prior.json")
        client.assert_not_called()
        self.assertFalse(data["restores_approvals"])
        self.assertEqual(data["report"]["decision"], "FAIL")

    def test_agent_run_passes_report_and_safe_resume_options(self):
        with patch("zhidiao_agent.workflow_cli.run_agent_workflow", return_value=result({"decision": "PASS"})) as workflow:
            status, _ = self.run_cli([
                "agent-run", "PA1 period1000 tolerance50", "--config", "local.json", "--project", "project",
                "--source", "Core/Src/main.c", "--source", "Core/Inc/main.h", "--protocol", "openai-responses",
                "--allow-network", "--pl-only", "--report-dir", "reports", "--resume-report", "prior.json",
            ])
        self.assertEqual(status, 0)
        options = workflow.call_args.kwargs
        self.assertEqual(options["source_files"], ("Core/Src/main.c", "Core/Inc/main.h"))
        self.assertEqual(options["report_dir"], "reports")
        self.assertEqual(options["resume_report_path"], "prior.json")
        self.assertFalse(options["include_uart"])

    def serve_arguments(self):
        return ["serve", "--config", "local.json", "--project", "project", "--source", "Core/Src/main.c"]

    def test_serve_requires_network_and_protocol_before_service_construction(self):
        with patch("zhidiao_agent.web_ui.WebUIService") as service, patch("zhidiao_agent.web_ui.run_server") as server:
            status, data = self.run_cli(self.serve_arguments())
            self.assertEqual(status, 1)
            self.assertEqual(data["error_code"], "APPROVAL_REQUIRED")
            status, data = self.run_cli(self.serve_arguments() + ["--allow-network"])
            self.assertEqual(status, 1)
            self.assertEqual(data["error_code"], "CONFIGURATION_ERROR")
        service.assert_not_called()
        server.assert_not_called()

    def test_serve_passes_only_selected_scope_and_defers_model_client(self):
        with patch("zhidiao_agent.web_ui.WebUIService") as service, patch(
            "zhidiao_agent.web_ui.run_server", return_value=result({"decision": "STOPPED"}),
        ) as server, patch("zhidiao_agent.cli._model_client") as client:
            status, _ = self.run_cli(self.serve_arguments() + [
                "--allow-network", "--protocol", "openai-responses", "--pl-only", "--max-attempts", "2",
                "--timeout-s", "120", "--port", "9876", "--report-dir", "reports",
            ])
        self.assertEqual(status, 0)
        client.assert_not_called()
        options = service.call_args.kwargs
        self.assertEqual(options["source_files"], ("Core/Src/main.c",))
        self.assertFalse(options["include_uart"])
        self.assertEqual(options["max_attempts"], 2)
        self.assertEqual(options["report_dir"], "reports")
        self.assertNotIn("host", options)
        server.assert_called_once_with(service.return_value, port=9876, open_browser=False)

    def test_wrapper_exceptions_return_structured_errors(self):
        with patch("zhidiao_agent.reports.read_report", side_effect=OSError("private")):
            status, data = self.run_cli(["report", "file.json"])
        self.assertEqual(status, 1)
        self.assertEqual(data["error_code"], "NETWORK_UNREACHABLE")
        self.assertNotIn("private", json.dumps(data))
