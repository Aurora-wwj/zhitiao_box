import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from zhidiao_agent.agent import Agent
from zhidiao_agent.controller import Controller
from zhidiao_agent.demo import ScriptedDemoClient
from zhidiao_agent.editing import SourceEditor
from zhidiao_agent.orchestrator import Orchestrator
from zhidiao_agent.reports import MAX_REPORT_BYTES, RunStore, read_report
from zhidiao_agent.tools.feedback_mock import FeedbackMockBackend


class RunStoreTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="zhidiao-reports-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.store = RunStore(self.root / "reports")
        self.report = {"report_schema": "1.0", "run_id": "run_" + "a" * 32,
                       "decision": "AWAITING_APPROVAL", "attempts": 1,
                       "pending_edit": {"proposal_id": "old-proposal", "fingerprint": "b" * 64}}

    def test_atomic_report_can_be_reopened_without_restoring_approvals(self):
        saved = self.store.save(self.report)
        self.assertTrue(saved.success, saved.to_dict())
        self.assertEqual(self.store.load(self.report["run_id"]).data["report"], self.report)
        self.assertFalse(self.store.load(self.report["run_id"]).data["restores_approvals"])
        self.assertEqual(self.store.list_runs().data["runs"], [self.report["run_id"]])
        if os.name == "posix":
            self.assertEqual(Path(saved.data["path"]).stat().st_mode & 0o777, 0o600)

    def test_secrets_are_removed_from_persistent_evidence(self):
        self.report["context"] = {"api_key": "secret-value", "Authorization": "Bearer credential",
                                  "log": "Bearer secret-token sk-abcdefghijklmnop"}
        saved = self.store.save(self.report)
        text = Path(saved.data["path"]).read_text()
        self.assertNotIn("secret-value", text)
        self.assertNotIn("secret-token", text)
        self.assertNotIn("sk-abcdefghijklmnop", text)
        self.assertIn("[REDACTED]", text)

    def test_failed_replace_preserves_previous_report_and_removes_temporary(self):
        self.assertTrue(self.store.save(self.report).success)
        path = self.store.root / (self.report["run_id"] + ".json")
        before = path.read_bytes()
        with patch("zhidiao_agent.reports.os.replace", side_effect=OSError("private details")):
            result = self.store.save({**self.report, "decision": "STOPPED"})
        self.assertFalse(result.success)
        self.assertNotIn("private details", result.message)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.store.root.glob(".run-*")), [])

    def test_malformed_oversized_and_nonfinite_reports_are_rejected(self):
        path = self.root / "bad.json"
        for raw in (b'[]', b'{"run_id":"run_0","attempts":0}',
                    b'{"attempts":0,"attempts":1}', b'x' * (MAX_REPORT_BYTES + 1)):
            path.write_bytes(raw)
            self.assertFalse(read_report(str(path)).success)
        for report in ({**self.report, "attempts": True}, {**self.report, "value": float("nan")},
                       {**self.report, "value": "x" * MAX_REPORT_BYTES}):
            self.assertFalse(self.store.save(report).success)
        self.assertFalse(self.store.load("../escape").success)

    def test_symlink_report_destinations_are_rejected_before_write(self):
        with patch.object(Path, "is_symlink", return_value=True):
            self.assertFalse(self.store.save(self.report).success)
            self.assertFalse(self.store.load(self.report["run_id"]).success)
            self.assertFalse(self.store.list_runs().success)
        self.assertFalse(self.store.root.exists())


class PersistedOrchestratorTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="zhidiao-report-loop-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.source = self.project / "main.c"
        self.source.write_text("const unsigned int gpio_period_ms = 800;\n", encoding="utf-8")
        self.store = RunStore(self.root / "reports")
        self.task = "PA1 complete period 1000 ms +/-50 ms"
        self.params = {"expected_period_ms": 1000, "tolerance_ms": 50}

    def loop(self, **extra):
        editor = SourceEditor(str(self.project), ("main.c",))
        controller = Controller(FeedbackMockBackend(str(self.project)), allowed_roots=(str(self.project),), max_attempts=3)
        return Orchestrator(controller, Agent(ScriptedDemoClient()), editor,
                            task=self.task, project_path=str(self.project), params=self.params,
                            report_store=self.store, **extra)

    def test_states_edit_and_terminal_evidence_are_durable(self):
        loop = self.loop()
        preview = loop.advance()
        loaded = self.store.load(loop.run_id).data["report"]
        self.assertEqual(loaded["decision"], "AWAITING_APPROVAL")
        self.assertEqual(loaded["observed_gpio"], "PA1")
        self.assertIn("source_sha256", loaded["checkpoint"])
        self.assertTrue(Path(preview.data["report_path"]).is_file())
        edit = preview.data["pending_edit"]
        self.assertTrue(loop.review_edit(edit["proposal_id"], edit["fingerprint"], approved=True).success)
        self.assertEqual(self.store.load(loop.run_id).data["report"]["decision"], "READY")
        self.assertEqual(loop.advance().data["decision"], "PASS")
        loaded = self.store.load(loop.run_id).data["report"]
        self.assertEqual(loaded["decision"], "PASS")
        self.assertEqual(loaded["attempts"], 2)

    def test_recovery_keeps_attempts_and_demands_fresh_source_approval(self):
        original = self.loop()
        first = original.advance()
        report = self.store.load(original.run_id).data["report"]
        restored = self.loop(recovery_report=report)
        preview = restored.advance()
        self.assertEqual(preview.data["decision"], "AWAITING_APPROVAL")
        self.assertEqual(preview.data["attempts"], 1)
        self.assertEqual(preview.data["parent_run_id"], original.run_id)
        self.assertNotEqual(preview.data["run_id"], original.run_id)
        self.assertNotEqual(preview.data["pending_edit"]["proposal_id"], first.data["pending_edit"]["proposal_id"])
        self.assertIn("800", self.source.read_text())
        pending = preview.data["pending_edit"]
        self.assertTrue(restored.review_edit(pending["proposal_id"], pending["fingerprint"], approved=True).success)
        self.assertEqual(restored.advance().data["decision"], "PASS")
        self.assertEqual(restored.attempts, 2)

    def test_recovery_rejects_changed_sources_or_inflight_checkpoint(self):
        original = self.loop()
        original.advance()
        saved = self.store.load(original.run_id).data["report"]
        for changes in ({"in_flight": "tool_cycle"}, {"observed_gpio": "PB3"},
                        {"max_attempts": 99}, {"checkpoint": {}}):
            result = self.loop(recovery_report={**saved, **changes}).advance()
            self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.source.write_text("externally changed\n")
        self.assertEqual(self.loop(recovery_report=saved).advance().error_code, "APPROVAL_REQUIRED")

    def test_recovery_caps_budget_without_comparing_float_remainders(self):
        original = self.loop(timeout_s=296.125)
        original.advance()
        report = self.store.load(original.run_id).data["report"]
        restored = self.loop(timeout_s=299.875, recovery_report=report)
        self.assertTrue(restored.advance().success)
        self.assertEqual(restored.timeout_s, 296.125)

    def test_cancel_is_persisted_and_terminal_recovery_never_runs_tools(self):
        loop = self.loop()
        loop.advance()
        self.assertEqual(loop.cancel().data["decision"], "STOPPED")
        saved = self.store.load(loop.run_id).data["report"]
        restored = self.loop(recovery_report=saved)
        backend = Mock(wraps=restored.controller.backend)
        backend.requires_approval = False
        restored.controller.backend = backend
        self.assertEqual(restored.advance().error_code, "APPROVAL_REQUIRED")
        backend.build_firmware.assert_not_called()

    def test_report_io_failure_stops_before_any_tool_cycle(self):
        loop = self.loop()
        backend = Mock(wraps=loop.controller.backend)
        backend.requires_approval = False
        loop.controller.backend = backend
        with patch("zhidiao_agent.reports.os.replace", side_effect=OSError("private report path")):
            result = loop.advance()
        self.assertFalse(result.success)
        self.assertEqual(result.data["report"]["decision"], "STOPPED")
        backend.build_firmware.assert_not_called()

    def test_custom_report_root_cannot_mutate_tracked_project_inputs(self):
        loop = self.loop()
        loop.report_store = RunStore(self.project / "reports")
        self.assertEqual(loop.advance().error_code, "INVALID_ARGUMENT")
        self.assertFalse((self.project / "reports").exists())
