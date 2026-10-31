import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from zhidiao_agent.agent import Agent
from zhidiao_agent.controller import Controller
from zhidiao_agent.demo import ScriptedDemoClient
from zhidiao_agent.editing import SourceEditor
from zhidiao_agent.models import OperationResult
from zhidiao_agent.orchestrator import Orchestrator
from zhidiao_agent.tools.feedback_mock import FeedbackMockBackend


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="zhidiao-loop-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.file = self.root / "main.c"
        self.file.write_text("const unsigned int gpio_period_ms = 800;\n", encoding="utf-8")
        self.editor = SourceEditor(str(self.root), ("main.c",))
        self.backend = Mock(wraps=FeedbackMockBackend(str(self.root)))
        self.backend.requires_approval = False
        self.backend.name = "mock_feedback"
        self.controller = Controller(self.backend, allowed_roots=(str(self.root),), max_attempts=3)
        self.client = Mock(wraps=ScriptedDemoClient())
        self.clock = Mock(return_value=0)
        self.loop = Orchestrator(self.controller, Agent(self.client), self.editor,
            task="1000 ms +/- 50 ms", project_path=str(self.root),
            params={"expected_period_ms": 1000, "tolerance_ms": 50}, clock=self.clock)

    def approve(self, result):
        self.assertTrue(result.success, result.to_dict())
        preview = result.data["pending_edit"]
        return self.loop.review_edit(preview["proposal_id"], preview["fingerprint"], approved=True)

    def test_full_feedback_edit_loop_800_to_1001_only_after_human_review(self):
        first = self.loop.advance()
        self.assertEqual(first.data["decision"], "AWAITING_APPROVAL")
        self.assertEqual(first.data["attempts"], 1)
        self.assertIn("= 800;", self.file.read_text())
        repeated = self.loop.advance()
        self.assertEqual(repeated.data["decision"], "AWAITING_APPROVAL")
        self.backend.build_firmware.assert_called_once()
        self.client.generate.assert_called_once()
        self.assertTrue(self.approve(first).success)
        self.assertIn("= 1001;", self.file.read_text())
        final = self.loop.advance()
        self.assertEqual(final.data["decision"], "PASS")
        self.assertEqual(final.data["attempts"], 2)
        periods = [cycle["execution"]["audit"][-1]["result"]["measurements"]["period_ms"] for cycle in final.data["cycles"]]
        self.assertEqual(periods, [800, 1001])
        self.assertEqual(final.data["evidence_source"], "mock")
        self.assertIn("applied_edit", final.data["cycles"][0])
        self.loop.advance()
        self.assertEqual(self.backend.build_firmware.call_count, 2)
        self.client.generate.assert_called_once()

    def test_rejection_stops_without_edit_or_extra_cycle(self):
        preview = self.loop.advance().data["pending_edit"]
        result = self.loop.review_edit(preview["proposal_id"], preview["fingerprint"], approved=False)
        self.assertEqual(result.error_code, "APPROVAL_REJECTED")
        self.assertEqual(self.loop.advance().data["decision"], "STOPPED")
        self.assertIn("= 800;", self.file.read_text())
        self.backend.build_firmware.assert_called_once()

    def test_source_change_after_preview_does_not_get_overwritten(self):
        first = self.loop.advance()
        self.file.write_text("const int gpio_period_ms = 777;\n", encoding="utf-8")
        result = self.approve(first)
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.assertIn("777", self.file.read_text())
        self.backend.build_firmware.assert_called_once()

    def test_attempt_limit_stops_before_requesting_another_edit(self):
        self.controller.max_attempts = 1
        result = self.loop.advance()
        self.assertEqual(result.data["decision"], "FAIL")
        self.assertEqual(result.data["reason"], "ATTEMPTS_EXHAUSTED")
        self.client.generate.assert_not_called()
        self.assertIn("800", self.file.read_text())

    def test_model_stop_is_honored(self):
        self.client.generate.return_value = OperationResult(True, None, "Done", "mock", data={
            "content": json.dumps({"action": "stop", "reason": "Need human investigation"}),
        })
        self.assertEqual(self.loop.advance().data["decision"], "STOPPED")
        self.assertIn("800", self.file.read_text())

    def test_model_cannot_declare_pass_or_execute_commands(self):
        for decision in ({"action": "pass", "reason": "I approve"},
                         {"action": "stop", "reason": "stop", "command": "shell"}):
            with self.subTest(decision=decision):
                response = OperationResult(True, None, "Done", "mock", data={"content": json.dumps(decision)})
                client = Mock()
                client.generate.return_value = response
                result = Agent(client).decide("task", {}, {})
                self.assertEqual(result.error_code, "INVALID_RESPONSE")

    def test_false_backend_pass_cannot_override_measurements(self):
        self.backend.run_hardware_test.return_value = OperationResult(True, None, "Done", "mock", data={
            "passed": True, "measurements": {"period_ms": 800},
        })
        result = self.loop.advance()
        self.assertEqual(result.error_code, "INVALID_RESPONSE")
        self.client.generate.assert_not_called()

    def test_observation_tool_failure_stops_without_source_edit(self):
        self.backend.run_hardware_test.return_value = OperationResult(False, "PL_TEST_UNAVAILABLE", "Unavailable", "mock")
        result = self.loop.advance()
        self.assertEqual(result.data["decision"], "FAIL")
        self.assertEqual(result.data["reason"], "MEASUREMENT_TOOL_FAILED")
        self.client.generate.assert_not_called()

    def test_model_timeout_stops_and_sanitizes_error(self):
        self.client.generate.side_effect = TimeoutError("private details")
        result = self.loop.advance()
        self.assertEqual(result.error_code, "TIMEOUT")
        self.assertNotIn("private details", result.message)
        self.assertIn("800", self.file.read_text())

    def test_time_budget_includes_waiting_for_human(self):
        first = self.loop.advance()
        self.clock.return_value = 301
        result = self.approve(first)
        self.assertEqual(result.error_code, "TIMEOUT")
        self.assertIn("800", self.file.read_text())
        self.backend.build_firmware.assert_called_once()

    def test_real_automatic_backend_is_still_blocked(self):
        self.backend.requires_approval = True
        result = self.loop.advance()
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.backend.build_firmware.assert_not_called()
        self.client.generate.assert_not_called()

    def test_cancel_invalidates_pending_review(self):
        first = self.loop.advance()
        self.assertEqual(self.loop.cancel().data["decision"], "STOPPED")
        self.assertFalse(self.approve(first).success)
        self.assertIn("800", self.file.read_text())

    def test_feedback_uses_deployed_build_not_latest_source(self):
        backend = FeedbackMockBackend(str(self.root))
        build = backend.build_firmware(str(self.root))
        self.assertTrue(backend.flash_firmware(build.data["artifact_path"]).success)
        self.file.write_text("const int gpio_period_ms = 1001;\n", encoding="utf-8")
        result = backend.run_hardware_test("gpio_period", {"expected_period_ms": 1000, "tolerance_ms": 50})
        self.assertEqual(result.data["measurements"]["period_ms"], 800)
        self.assertFalse(result.data["passed"])
        self.assertEqual(backend.flash_firmware(build.data["artifact_path"]).error_code, "FLASH_PROGRAM_FAILED")

    def test_invalid_model_json_and_unlisted_path_do_not_create_edit(self):
        sources = self.editor.snapshot().data["sources"]
        for text in ("not JSON", json.dumps({"action": "edit", "reason": "bad", "edit": {
            "path": "../main.c", "before_sha256": sources["main.c"]["sha256"], "content": "bad",
        }})):
            client = Mock()
            client.generate.return_value = OperationResult(True, None, "Done", "mock", data={"content": text})
            self.assertEqual(Agent(client).decide("task", {}, sources).error_code, "INVALID_RESPONSE")

    def test_stale_hash_from_model_stops_before_approval(self):
        self.client.generate.return_value = OperationResult(True, None, "Done", "mock", data={
            "content": json.dumps({"action": "edit", "reason": "change period", "edit": {
                "path": "main.c", "before_sha256": "0" * 64, "content": "const int gpio_period_ms = 1001;\n",
            }}),
        })
        result = self.loop.advance()
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.assertIsNone(result.data["report"]["pending_edit"])
        self.assertIn("800", self.file.read_text())

    def test_non_json_tool_metadata_cannot_break_error_report(self):
        self.backend.build_firmware.return_value = OperationResult(
            True, None, "Done", "mock", data={"artifact_path": str(self.root / "firmware.hex"), "invalid": object()},
        )
        result = self.loop.advance()
        self.assertEqual(result.error_code, "INVALID_RESPONSE")
        self.assertEqual(result.data["report"]["decision"], "STOPPED")
        self.client.generate.assert_not_called()
