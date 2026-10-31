import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

from zhidiao_agent.cli import main
from zhidiao_agent.approval import ApprovalGate
from zhidiao_agent.models import OperationResult
from zhidiao_agent.real_cli import real_operation


class RealCliTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.fingerprint = "a" * 64
        self.preview = OperationResult(True, None, "Prepared", "real", data={
            "proposal_id": "proposal", "fingerprint": self.fingerprint,
            "state": "pending", "params": {"commands": [["reviewed", "command"]]},
        })
        self.backend.preview_build.return_value = self.preview
        self.backend.preview_flash.return_value = self.preview
        self.backend.approvals.decide.return_value = OperationResult(True, None, "Approved", "approval")
        self.backend.build_firmware.return_value = OperationResult(
            True, None, "Done", "real", data={"artifact_path": "local.hex"},
        )
        self.backend.flash_firmware.return_value = OperationResult(
            True, None, "Done", "real", data={"verified": True},
        )
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        self.enterContext(patch("zhidiao_agent.real_cli.DeploymentConfig.load", return_value=Mock()))
        self.enterContext(patch("zhidiao_agent.real_cli.RealBackend", return_value=self.backend))

    def test_preview_only_never_requests_approval_or_executes(self):
        with patch("builtins.input") as prompt:
            status = main(["real-build", "project", "--config", "local.json", "--preview-only"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(self.output.getvalue())["state"], "pending")
        prompt.assert_not_called()
        self.backend.approvals.decide.assert_not_called()
        self.backend.build_firmware.assert_not_called()

    def test_noninteractive_input_cannot_auto_approve(self):
        with patch("sys.stdin.isatty", return_value=False):
            result = real_operation("real-flash", "local.json", "local.hex", preview_only=False)
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.backend.flash_firmware.assert_not_called()
        self.backend.approvals.decide.assert_not_called()

    def test_exact_human_confirmation_executes_only_selected_operation(self):
        for command in ("real-build", "real-flash"):
            with self.subTest(command=command), patch("sys.stdin.isatty", return_value=True), patch(
                "builtins.input", return_value="APPROVE " + self.fingerprint,
            ):
                result = real_operation(command, "local.json", "path", preview_only=False)
                self.assertTrue(result.success)
                self.backend.approvals.decide.assert_called_with("proposal", self.fingerprint, approved=True)
        self.backend.build_firmware.assert_called_once_with("path")
        self.backend.flash_firmware.assert_called_once_with("path")

    def test_rejection_or_eof_does_not_execute(self):
        self.backend.approvals.decide.return_value = OperationResult(False, "APPROVAL_REJECTED", "Rejected", "approval")
        for answer in ("maybe", "APPROVE wrong", ""):
            with self.subTest(answer=answer), patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=answer):
                result = real_operation("real-build", "local.json", "project", preview_only=False)
                self.assertEqual(result.error_code, "APPROVAL_REJECTED")
                self.backend.approvals.decide.assert_called_with("proposal", self.fingerprint, approved=False)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=EOFError):
            self.assertEqual(real_operation("real-build", "local.json", "project", preview_only=False).error_code, "APPROVAL_REJECTED")
        self.backend.build_firmware.assert_not_called()

    def test_failed_preflight_and_unexpected_ui_error_are_captured(self):
        self.backend.preview_build.return_value = OperationResult(False, "CONFIGURATION_ERROR", "Missing Keil", "real")
        result = real_operation("real-build", "local.json", "project", preview_only=False)
        self.assertEqual(result.error_code, "CONFIGURATION_ERROR")
        self.backend.preview_build.side_effect = RuntimeError("private details")
        result = real_operation("real-build", "local.json", "project", preview_only=False)
        self.assertEqual(result.error_code, "INTERNAL_ERROR")
        self.assertNotIn("private details", result.message)
        self.backend.build_firmware.assert_not_called()


class ObservationCliTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.backend.approvals = ApprovalGate()
        self.plan = {"period_available": True, "uart_available": True,
                     "effects": "One approved SSH observation; no flash or source edits."}
        self.backend.preview_observation.return_value = OperationResult(True, None, "Preview", "real", data=self.plan)
        self.backend.run_hardware_test.return_value = OperationResult(True, None, "Measurement complete", "real", data={
            "passed": False, "measurements": {"period_ms": 601},
        })
        self.backend.read_target_log.return_value = OperationResult(True, None, "Captured", "real", data={"logs": []})
        self.backend._preview_uart_capture.return_value = OperationResult(True, None, "Injected provider", "real", data={"required": False})
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        self.enterContext(patch("zhidiao_agent.real_cli.DeploymentConfig.load", return_value=Mock()))
        self.enterContext(patch("zhidiao_agent.real_cli.RealBackend", return_value=self.backend))

    def test_independent_pl_preview_never_reads_hardware(self):
        status = main(["real-test", "--config", "local.json", "--expected-period-ms", "1000",
                       "--tolerance-ms", "50", "--preview-only"])
        self.assertEqual(status, 0)
        preview = json.loads(self.output.getvalue())
        self.assertEqual(preview["action"], "run_hardware_test")
        self.assertEqual(preview["params"]["arguments"], ["gpio_period", {"expected_period_ms": 1000, "tolerance_ms": 50}])
        self.backend.run_hardware_test.assert_not_called()
    def test_independent_pl_uses_human_approval_and_preserves_tool_vs_dut_status(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="  批准  "):
            actual = real_operation("real-test", "local.json", preview_only=False,
                                    params={"expected_period_ms": 1000, "tolerance_ms": 50})
        self.assertTrue(actual.success)
        self.assertFalse(actual.data["passed"])
        self.backend.run_hardware_test.assert_called_once_with("gpio_period", {"expected_period_ms": 1000, "tolerance_ms": 50})
        self.backend.flash_firmware.assert_not_called()

    def test_changed_observation_plan_invalidates_approval(self):
        self.backend.preview_observation.side_effect = [
            OperationResult(True, None, "Preview", "real", data={"register": "old"}),
            OperationResult(True, None, "Preview", "real", data={"register": "changed"}),
        ]
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="y"):
            actual = real_operation("real-test", "local.json", preview_only=False,
                                    params={"expected_period_ms": 1000, "tolerance_ms": 50})
        self.assertEqual(actual.error_code, "APPROVAL_REQUIRED")
        self.backend.run_hardware_test.assert_not_called()

    def test_empty_uart_capture_success_does_not_claim_firmware_pass(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="approve"):
            actual = real_operation("real-log", "local.json", preview_only=False, duration_s=3)
        self.assertTrue(actual.success)
        self.assertEqual(actual.data["logs"], [])
        self.assertNotIn("passed", actual.data)
        self.backend.read_target_log.assert_called_once_with(3)

    def test_unavailable_uart_is_reported_without_approval_or_capture(self):
        self.backend.preview_observation.return_value = OperationResult(False, "BACKEND_UNAVAILABLE", "UART reader is not connected.", "real")
        with patch("builtins.input") as prompt:
            actual = real_operation("real-log", "local.json", preview_only=False)
        self.assertEqual(actual.error_code, "BACKEND_UNAVAILABLE")
        prompt.assert_not_called()
        self.backend.read_target_log.assert_not_called()

    def test_rejection_never_runs_observation(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="取消"):
            actual = real_operation("real-test", "local.json", preview_only=False,
                                    params={"expected_period_ms": 1000, "tolerance_ms": 50})
        self.assertEqual(actual.error_code, "APPROVAL_REJECTED")
        self.backend.run_hardware_test.assert_not_called()
