import contextlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from zhidiao_agent.cli import main
from zhidiao_agent.models import OperationResult
from zhidiao_agent.workflow_cli import run_agent_workflow


def result(data=None):
    return OperationResult(True, None, "Test fixture", "mock", data=data or {})


class WorkflowCliTests(unittest.TestCase):
    def test_resume_without_task_reuses_saved_task_without_new_text_prompt(self):
        saved_task = "PA1完整周期1000 ms，误差不超过50 ms"
        with patch("zhidiao_agent.workflow_cli.read_report", return_value=result({
                "report": {"metadata": {"task": saved_task}},
        })), patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="批准") as prompt:
            actual = run_agent_workflow(None, config_path="local.json", project_path=str(self.project),
                source_files=("main.c",), client_factory=self.client_factory, resume_report_path="old.json",
                report_dir=str(self.project / ".zhidiao" / "runs"))
        self.assertTrue(actual.success, actual.to_dict())
        self.assertEqual(self.goal.interpret.call_args.args[0], saved_task)
        self.assertEqual(prompt.call_count, 2)

    def setUp(self):
        self.directory = TemporaryDirectory(prefix="zhidiao-workflow-ui-")
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name).resolve()
        (self.project / "main.c").write_text("int period = 600;\n", encoding="utf-8")
        self.config = Mock(host="192.168.10.2", user="root", allowed_roots=(str(self.project),))
        self.config.observer = SimpleNamespace(observed_gpio="PA1")
        self.config.local_path.side_effect = lambda value: Path(value)
        self.backend = Mock()
        self.backend.preview_build.return_value = result({"params": {"source_sha256": "a" * 64}})
        self.backend.preview_observation.return_value = result({"period_available": True, "uart_available": True})
        self.client_factory = Mock(return_value=Mock())
        self.goal = self.enterContext(patch("zhidiao_agent.workflow_cli.GoalInterpreter")).return_value
        self.ready_goal = {"status": "ready", "test_id": "gpio_period", "observed_gpio": "PA1",
            "params": {"expected_period_ms": 1000, "tolerance_ms": 50}, "summary": "PA1 完整周期 1000 ±50 ms"}
        self.goal.interpret.return_value = result(self.ready_goal)
        self.enterContext(patch("zhidiao_agent.workflow_cli.DeploymentConfig.load", return_value=self.config))
        self.enterContext(patch("zhidiao_agent.workflow_cli.RealBackend", return_value=self.backend))
        self.controller_class = self.enterContext(patch("zhidiao_agent.workflow_cli.ReviewedController"))
        self.loop_class = self.enterContext(patch("zhidiao_agent.workflow_cli.Orchestrator"))
        self.loop = self.loop_class.return_value
        self.loop.advance.return_value = result({"decision": "PASS", "evidence_source": "real", "attempts": 1})
        self.loop.report.return_value = {"decision": "AWAITING_EXECUTION_APPROVAL", "attempts": 0}
        self.loop.cancel.return_value = result({"decision": "STOPPED", "attempts": 0})
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def run_workflow(self, **options):
        options.setdefault("report_dir", str(self.project / ".zhidiao" / "runs"))
        return run_agent_workflow("把 GPIO 完整周期设为 1000 ms，误差不超过 50 ms", config_path="local.json",
            project_path=str(self.project), source_files=("main.c",), client_factory=self.client_factory, **options)

    def test_rejected_context_sharing_never_constructs_client_or_loop(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="取消"):
            actual = self.run_workflow()
        self.assertEqual(actual.error_code, "APPROVAL_REJECTED")
        self.client_factory.assert_not_called()
        self.goal.interpret.assert_not_called()
        self.loop_class.assert_not_called()
        self.backend.build_firmware.assert_not_called()

    def test_noninteractive_never_uploads_selected_sources(self):
        with patch("sys.stdin.isatty", return_value=False), patch("builtins.input") as prompt:
            actual = self.run_workflow()
        self.assertEqual(actual.error_code, "APPROVAL_REQUIRED")
        prompt.assert_not_called()
        self.client_factory.assert_not_called()

    def test_rejecting_parsed_goal_never_executes(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["批准", "取消"]):
            actual = self.run_workflow()
        self.assertEqual(actual.error_code, "APPROVAL_REJECTED")
        self.goal.interpret.assert_called_once()
        self.loop_class.assert_not_called()

    def test_ambiguous_goal_returns_question_without_real_loop(self):
        self.goal.interpret.return_value = result({"status": "clarification", "question": "允许误差是多少？"})
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="批准"):
            actual = self.run_workflow()
        self.assertTrue(actual.success)
        self.assertEqual(actual.data["decision"], "NEEDS_CLARIFICATION")
        self.assertEqual(self.goal.interpret.call_count, 4)
        self.loop_class.assert_not_called()

    def test_clarification_can_continue_to_goal_confirmation_in_same_session(self):
        self.goal.interpret.side_effect = [result({"status": "clarification", "question": "允许误差是多少？"}),
                                           result(self.ready_goal)]
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["批准", "误差50ms", "批准"]):
            actual = self.run_workflow()
        self.assertTrue(actual.success, actual.to_dict())
        second = self.goal.interpret.call_args_list[1]
        self.assertEqual(second.kwargs["clarifications"], ({"question": "允许误差是多少？", "answer": "误差50ms"},))
        self.assertIn("误差50ms", self.loop_class.call_args.kwargs["task"])

    def test_clarification_cancel_or_unsupported_pin_never_starts_loop(self):
        self.goal.interpret.return_value = result({"status": "clarification", "question": "允许误差是多少？"})
        for answer, code in (("取消", "CANCELLED"), ("PB3误差50ms", "INVALID_ARGUMENT")):
            with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["批准", answer]):
                actual = self.run_workflow()
            self.assertEqual(actual.error_code, code)
        self.loop_class.assert_not_called()

    def test_explicit_other_pin_rejected_before_context_upload(self):
        with patch("builtins.input") as prompt:
            actual = run_agent_workflow("把PB3完整周期调到1000ms，误差50ms", config_path="local.json",
                project_path=str(self.project), source_files=("main.c",), client_factory=self.client_factory)
        self.assertEqual(actual.error_code, "INVALID_ARGUMENT")
        self.client_factory.assert_not_called()
        prompt.assert_not_called()

    def test_budget_includes_initial_human_review_and_goal_request(self):
        clock = [0]
        def slow_review(prompt):
            clock[0] = 301
            return "批准"
        with patch("zhidiao_agent.workflow_cli.time.monotonic", side_effect=lambda: clock[0]), \
                patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=slow_review):
            actual = self.run_workflow()
        self.assertEqual(actual.error_code, "TIMEOUT")
        self.client_factory.assert_not_called()
        self.loop_class.assert_not_called()

    def test_model_cannot_report_ready_for_other_observed_pin(self):
        self.goal.interpret.return_value = result({**self.ready_goal, "observed_gpio": "PB3"})
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="批准"):
            actual = self.run_workflow()
        self.assertEqual(actual.error_code, "INVALID_RESPONSE")
        self.loop_class.assert_not_called()

    def test_report_directory_cannot_change_project_source_or_git_metadata(self):
        for root in (self.project / "reports", self.project / ".git" / "runs"):
            actual = self.run_workflow(report_dir=str(root))
            self.assertEqual(actual.error_code, "INVALID_ARGUMENT")
        self.client_factory.assert_not_called()
        self.assertFalse((self.project / "reports").exists())

    def test_resume_report_is_loaded_before_model_and_passed_without_authorization(self):
        snapshot = {"run_id": "run_" + "a" * 32, "attempts": 1, "decision": "STOPPED"}
        with patch("zhidiao_agent.workflow_cli.read_report", return_value=result({"report": snapshot})) as load, \
                patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="批准"):
            actual = self.run_workflow(resume_report_path="saved-run.json", report_dir=str(self.project / ".zhidiao" / "runs"))
        self.assertTrue(actual.success, actual.to_dict())
        load.assert_called_once_with("saved-run.json")
        self.assertEqual(self.loop_class.call_args.kwargs["recovery_report"], snapshot)
        self.assertEqual(self.loop_class.call_args.kwargs["report_store"].root, self.project / ".zhidiao" / "runs")
        self.assertNotIn("approved", self.loop_class.call_args.kwargs)

    def test_invalid_resume_report_stops_before_model_request(self):
        with patch("zhidiao_agent.workflow_cli.read_report", return_value=OperationResult(
                False, "INVALID_RESPONSE", "Invalid report", "run_report")):
            actual = self.run_workflow(resume_report_path="invalid.json")
        self.assertEqual(actual.error_code, "INVALID_RESPONSE")
        self.client_factory.assert_not_called()

    def test_missing_uart_cannot_silently_turn_into_pl_only(self):
        def observation(method=None, *args):
            return OperationResult(False, "BACKEND_UNAVAILABLE", "UART is not connected.", "real") if method == "read_target_log" else result()
        self.backend.preview_observation.side_effect = observation
        with patch("builtins.input") as prompt:
            actual = self.run_workflow()
        self.assertEqual(actual.error_code, "BACKEND_UNAVAILABLE")
        self.client_factory.assert_not_called()
        prompt.assert_not_called()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="批准"):
            actual = self.run_workflow(include_uart=False)
        self.assertTrue(actual.success)
        self.assertFalse(self.loop_class.call_args.kwargs["include_uart"])

    def test_each_execution_and_edit_uses_exact_pending_identity(self):
        edit = {"proposal_id": "edit-1", "fingerprint": "e" * 64, "params": {"diff": "-600\n+1000\n"}}
        execution = {"proposal_id": "cycle-1", "fingerprint": "c" * 64, "params": {"steps": ["build", "flash", "measure"]}}
        self.loop.advance.side_effect = [
            result({"decision": "AWAITING_EXECUTION_APPROVAL", "pending_execution": execution}),
            result({"decision": "AWAITING_APPROVAL", "pending_edit": edit}),
            result({"decision": "PASS", "evidence_source": "real", "attempts": 2}),
        ]
        self.loop.review_execution.return_value = result({"decision": "READY"})
        self.loop.review_edit.return_value = result({"decision": "READY"})
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="  Y  "):
            actual = self.run_workflow(include_uart=False)
        self.assertTrue(actual.success)
        self.assertEqual(actual.data["decision"], "PASS")
        self.loop.review_execution.assert_called_once_with("cycle-1", "c" * 64, approved=True)
        self.loop.review_edit.assert_called_once_with("edit-1", "e" * 64, approved=True)

    def test_local_source_failure_precedes_model_request(self):
        (self.project / "main.c").unlink()
        with patch("builtins.input") as prompt:
            actual = self.run_workflow()
        self.assertEqual(actual.error_code, "INVALID_ARGUMENT")
        self.client_factory.assert_not_called()
        prompt.assert_not_called()

    def test_source_change_after_consent_requires_fresh_review_before_model(self):
        def mutate_during_review(prompt):
            (self.project / "main.c").write_text("changed externally\n", encoding="utf-8")
            return "批准"
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=mutate_during_review):
            actual = self.run_workflow()
        self.assertEqual(actual.error_code, "APPROVAL_REQUIRED")
        self.client_factory.assert_not_called()
        self.loop_class.assert_not_called()

    def test_source_change_during_goal_review_does_not_start_loop(self):
        count = 0
        def mutate_on_second_review(prompt):
            nonlocal count
            count += 1
            if count == 2:
                (self.project / "main.c").write_text("changed externally\n", encoding="utf-8")
            return "批准"
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=mutate_on_second_review):
            actual = self.run_workflow()
        self.assertEqual(actual.error_code, "APPROVAL_REQUIRED")
        self.goal.interpret.assert_called_once()
        self.loop_class.assert_not_called()

    def test_cli_requires_explicit_network_and_protocol_before_workflow(self):
        args = ["agent-run", "task", "--config", "local.json", "--project", str(self.project), "--source", "main.c"]
        with patch("zhidiao_agent.workflow_cli.run_agent_workflow") as workflow:
            self.assertEqual(main(args), 1)
            self.assertEqual(main(args + ["--allow-network"]), 1)
        workflow.assert_not_called()
