import contextlib
import io
import unittest
from unittest.mock import Mock, patch

from zhidiao_agent.approval import ApprovalGate
from zhidiao_agent.models import OperationResult
from zhidiao_agent.setup_cli import run_diagnostics, run_setup


def ok(data=None):
    return OperationResult(True, None, "mock", "mock", data=data or {})


class SetupCliTests(unittest.TestCase):
    def setUp(self):
        self.instance = Mock()
        self.instance.approvals = ApprovalGate()
        self.instance.preview.side_effect = lambda *a, **kw: self.instance.approvals.propose("test_setup", {"file": "local.json"})
        self.instance.apply.return_value = ok({"profile_path": "local.json"})
        self.instance.run.return_value = ok({"decision": "READY"})
        self.enterContext(patch("zhidiao_agent.setup_cli.DeploymentConfig"))
        self.enterContext(patch("zhidiao_agent.setup_cli.DeploymentSetup", return_value=self.instance))
        self.enterContext(patch("zhidiao_agent.setup_cli.DeploymentDiagnostics", return_value=self.instance))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def setup(self, **options):
        return run_setup(project_path="project", keil_executable="UV4", known_hosts="hosts", **options)

    def test_preview_only_does_not_ask_or_execute(self):
        with patch("builtins.input") as prompt:
            result = self.setup(preview_only=True)
            checked = run_diagnostics("local.json", preview_only=True)
        self.assertTrue(result.success)
        self.assertTrue(checked.success)
        self.instance.apply.assert_not_called()
        self.instance.run.assert_not_called()
        prompt.assert_not_called()

    def test_rejected_and_noninteractive_setup_never_write(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="取消"):
            self.assertEqual(self.setup().error_code, "APPROVAL_REJECTED")
        with patch("sys.stdin.isatty", return_value=False):
            self.assertEqual(self.setup().error_code, "APPROVAL_REQUIRED")
        self.instance.apply.assert_not_called()

    def test_trusted_human_may_approve_setup_and_checks(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="批准"):
            self.assertTrue(self.setup().success)
            self.assertTrue(run_diagnostics("local.json").success)
        self.instance.apply.assert_called_once()
        self.instance.run.assert_called_once()

    def test_diagnostics_cancel_and_factory_errors_are_captured(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=EOFError()):
            self.assertEqual(run_diagnostics("local.json").error_code, "APPROVAL_REJECTED")
        with patch("zhidiao_agent.setup_cli.DeploymentSetup", side_effect=RuntimeError("private")):
            actual = self.setup()
        self.assertEqual(actual.error_code, "INTERNAL_ERROR")
        self.assertNotIn("private", actual.message)
