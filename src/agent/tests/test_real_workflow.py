"""Real workflow semantics exercised with fake subprocesses and physical readers."""

import hashlib
import json
import re
import time
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from zhidiao_agent.agent import Agent
from zhidiao_agent.controller import ReviewedController
from zhidiao_agent.demo import ScriptedDemoClient
from zhidiao_agent.deployment import DeploymentConfig
from zhidiao_agent.editing import SourceEditor
from zhidiao_agent.models import OperationResult
from zhidiao_agent.observations import ObservationBackend
from zhidiao_agent.orchestrator import Orchestrator
from zhidiao_agent.tools.commands import CommandResult
from zhidiao_agent.tools.real_backend import RealBackend


def intel_hex(value):
    record = bytes([4, 0, 0, 0]) + value.to_bytes(4, "big")
    return ":" + record.hex().upper() + f"{(-sum(record)) & 255:02X}\n:00000001FF\n"


class ReviewedRealWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="zhidiao-reviewed-real-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.source = self.project / "main.c"
        self.source.write_text("const unsigned int gpio_period_ms = 800;\n", encoding="utf-8")
        (self.project / "GPIO.uvprojx").write_text('''<Project><Targets><Target>
<TargetName>GPIO</TargetName><TargetOption><TargetCommonOption>
<OutputDirectory>.\\output\\</OutputDirectory><OutputName>firmware</OutputName>
<CreateHexFile>1</CreateHexFile></TargetCommonOption></TargetOption></Target></Targets></Project>''')
        self.artifact = self.project / "output" / "firmware.hex"
        self.artifact.parent.mkdir()
        executable = self.root / "UV4.exe"
        executable.write_text("fake executable, never launched")
        known_hosts = self.root / "known_hosts"
        known_hosts.write_text("verified host placeholder")
        self.config = DeploymentConfig(allowed_roots=(str(self.project),),
            keil_executable=str(executable), project_file="GPIO.uvprojx", target="GPIO",
            known_hosts=str(known_hosts))
        self.compiled_period = self.deployed_period = None
        self.build_number = 0
        self.runner = Mock()
        self.runner.run.side_effect = self.fake_process
        self.uart = Mock(return_value=[])
        self.period = Mock(side_effect=lambda timeout: {"period_ms": self.deployed_period})
        self.backend = RealBackend(self.config, runner=self.runner,
            observations=ObservationBackend(uart_reader=self.uart, period_reader=self.period))
        # This stub represents a pure observation descriptor, not evidence.
        self.backend.preview_observation = Mock(return_value=OperationResult(True, None, "Configured", "real", data={
            "uart_available": True, "period_available": True, "descriptor": {"source": "injected reader"},
        }))
        self.controller = ReviewedController(self.backend, allowed_roots=(str(self.project),))
        self.params = {"expected_period_ms": 1000, "tolerance_ms": 50}
        self.client = Mock(wraps=ScriptedDemoClient())
        self.editor = SourceEditor(str(self.project), ("main.c",))
        self.loop = Orchestrator(self.controller, Agent(self.client), self.editor,
            task="Set full GPIO period to 1000 ms +/- 50 ms", project_path=str(self.project),
            params=self.params, include_uart=False)

    def fake_process(self, argv, timeout):
        self.assertGreater(timeout, 0)
        if argv[0] == self.config.keil_executable:
            self.build_number += 1
            self.compiled_period = int(re.search(r"gpio_period_ms\s*=\s*(\d+)", self.source.read_text()).group(1))
            self.artifact.write_text(intel_hex(self.compiled_period + self.build_number))
            Path(argv[argv.index("-o") + 1]).write_text('"firmware.axf" - 0 Error(s), 0 Warning(s).\n')
            return CommandResult(0, "")
        if argv[0] == "scp":
            return CommandResult(0, "")
        command = argv[-1]
        if "wc -c" in command:
            return CommandResult(0, str(self.artifact.stat().st_size) + "\n")
        if command.startswith("sha256sum < "):
            return CommandResult(0, hashlib.sha256(self.artifact.read_bytes()).hexdigest() + "  -\n")
        if "verify reset exit" in command:
            self.deployed_period = self.compiled_period
            return CommandResult(0, "Programming Finished\nVerified OK\nResetting Target\n")
        return CommandResult(0, "")

    def preview(self, **kwargs):
        result = self.controller.preview_cycle(str(self.project), params=self.params,
                                               include_uart=False, **kwargs)
        self.assertTrue(result.success, result.to_dict())
        return result.data

    def approve(self, preview, approved=True):
        return self.controller.review_cycle(preview["proposal_id"], preview["fingerprint"], approved=approved)

    def run_cycle(self):
        return self.controller.run_once(str(self.project), params=self.params, include_uart=False)

    def approve_execution(self, report):
        preview = report.data["pending_execution"]
        result = self.loop.review_execution(preview["proposal_id"], preview["fingerprint"], approved=True)
        self.assertTrue(result.success, result.to_dict())
        return result

    def test_preview_and_review_do_not_execute_hardware(self):
        preview = self.preview()
        self.assertTrue(self.approve(preview).success)
        self.runner.run.assert_not_called()
        self.period.assert_not_called()
        self.assertIn("SHA-256", preview["params"]["artifact_policy"])
        self.assertIn("source_sha256", preview["params"]["binding"])

    def test_no_real_cycle_without_review_and_no_legacy_run_bypass(self):
        self.assertEqual(self.run_cycle().error_code, "APPROVAL_REQUIRED")
        preview = self.preview()
        self.assertEqual(self.run_cycle().error_code, "APPROVAL_REQUIRED")
        self.assertTrue(self.approve(preview).success)
        self.assertEqual(self.controller.run(str(self.project)).error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_pl_only_is_explicit_and_records_skipped_uart(self):
        self.approve(self.preview())
        result = self.run_cycle()
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["decision"], "FAIL")
        self.assertEqual(result.data["verification_scope"], "gpio_period_only")
        self.assertEqual(result.data["skipped_tools"][0]["tool_name"], "read_target_log")
        self.assertEqual([row["tool_name"] for row in result.data["audit"]],
                         ["build_firmware", "flash_firmware", "run_hardware_test"])
        self.uart.assert_not_called()

    def test_successful_empty_uart_is_a_real_capture_and_can_pass_period_goal(self):
        self.source.write_text("const unsigned int gpio_period_ms = 1001;\n")
        preview = self.controller.preview_cycle(str(self.project), params=self.params)
        self.assertTrue(self.approve(preview.data).success)
        result = self.controller.run_once(str(self.project), params=self.params)
        self.assertEqual(result.data["decision"], "PASS")
        self.assertEqual(result.data["audit"][2]["result"]["logs"], [])
        self.assertTrue(result.data["uart_observed"])
        self.uart.assert_called_once()

    def test_missing_uart_does_not_silently_switch_to_pl_only(self):
        self.backend.preview_observation.return_value = OperationResult(True, None, "Configured", "real", data={
            "uart_available": False, "period_available": True,
        })
        result = self.controller.preview_cycle(str(self.project), params=self.params)
        self.assertEqual(result.error_code, "BACKEND_UNAVAILABLE")
        self.runner.run.assert_not_called()

    def test_rejected_cycle_never_authorizes_a_child_operation(self):
        preview = self.preview()
        self.assertEqual(self.approve(preview, False).error_code, "APPROVAL_REJECTED")
        self.assertEqual(self.run_cycle().error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_cycle_approval_and_children_are_single_use(self):
        preview = self.preview()
        self.approve(preview)
        self.assertTrue(self.run_cycle().success)
        calls = self.runner.run.call_count
        self.assertEqual(self.run_cycle().error_code, "APPROVAL_REQUIRED")
        self.assertEqual(self.approve(preview).error_code, "APPROVAL_REQUIRED")
        self.assertEqual(self.backend.build_firmware(str(self.project)).error_code, "APPROVAL_REQUIRED")
        self.assertEqual(self.backend.flash_firmware(str(self.artifact)).error_code, "APPROVAL_REQUIRED")
        self.assertEqual(self.runner.run.call_count, calls)

    def test_failed_rereview_revokes_previous_approval_even_if_source_is_restored(self):
        preview = self.preview()
        self.assertTrue(self.approve(preview).success)
        original = self.source.read_bytes()
        self.source.write_text("externally changed\n")
        self.assertEqual(self.approve(preview, False).error_code, "APPROVAL_REQUIRED")
        self.source.write_bytes(original)
        self.assertEqual(self.run_cycle().error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_source_change_before_review_or_execution_stops_without_commands(self):
        preview = self.preview()
        self.source.write_text("const int gpio_period_ms = 777;\n")
        self.assertEqual(self.approve(preview).error_code, "APPROVAL_REQUIRED")
        preview = self.preview()
        self.approve(preview)
        self.source.write_text("const int gpio_period_ms = 666;\n")
        self.assertEqual(self.run_cycle().error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_unlisted_source_changes_are_also_bound(self):
        other = self.project / "another.c"
        other.write_text("int x = 1;\n")
        self.approve(self.preview())
        other.write_text("int x = 2;\n")
        self.assertEqual(self.run_cycle().error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_deployment_or_goal_change_invalidates_approval(self):
        self.approve(self.preview())
        self.backend.config = replace(self.config, host="192.168.10.3")
        self.assertEqual(self.run_cycle().error_code, "APPROVAL_REQUIRED")
        self.backend.config = self.config
        self.approve(self.preview())
        self.params["expected_period_ms"] = 600
        self.assertEqual(self.run_cycle().error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_changed_observation_descriptor_invalidates_approval(self):
        self.approve(self.preview())
        self.backend.preview_observation.return_value = OperationResult(True, None, "Changed", "real", data={
            "uart_available": True, "period_available": True, "descriptor": {"source": "different reader"},
        })
        self.assertEqual(self.run_cycle().error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_same_type_callback_replacement_invalidates_approval(self):
        self.approve(self.preview())
        self.backend.observations.period_reader = Mock(return_value={"period_ms": 1000})
        self.assertEqual(self.run_cycle().error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_real_backend_observation_descriptor_integrates_without_stub(self):
        del self.backend.preview_observation
        self.approve(self.preview())
        result = self.run_cycle()
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["decision"], "FAIL")

    def test_changed_source_during_build_never_reaches_flash(self):
        self.approve(self.preview())
        def run(argv, timeout):
            result = self.fake_process(argv, timeout)
            self.source.write_text("const int gpio_period_ms = 999;\n")
            return result
        self.runner.run.side_effect = run
        result = self.run_cycle()
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_called_once()
        self.assertIsNone(self.deployed_period)

    def test_artifact_change_between_build_and_flash_preview_is_rejected(self):
        original = self.backend.preview_flash
        def preview(path):
            self.artifact.write_text(intel_hex(999))
            return original(path)
        self.backend.preview_flash = preview
        self.approve(self.preview())
        result = self.run_cycle()
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_called_once()

    def test_timeout_before_execution_or_after_build_stops_following_stages(self):
        self.approve(self.preview())
        self.controller.execution_deadline = time.monotonic() - 1
        self.assertEqual(self.run_cycle().error_code, "TIMEOUT")
        self.runner.run.assert_not_called()
        self.controller.execution_deadline = None
        self.approve(self.preview())
        def run(argv, timeout):
            result = self.fake_process(argv, timeout)
            self.controller.execution_deadline = 0
            return result
        self.runner.run.side_effect = run
        self.assertEqual(self.run_cycle().error_code, "TIMEOUT")
        self.runner.run.assert_called_once()
        self.assertIsNone(self.backend.execution_deadline)

    def test_false_physical_pass_is_rejected(self):
        self.period.return_value = {"period_ms": 800}
        self.backend.run_hardware_test = Mock(return_value=OperationResult(True, None, "Done", "real", data={
            "measurements": {"period_ms": 800}, "passed": True,
        }))
        self.approve(self.preview())
        self.assertEqual(self.run_cycle().error_code, "INVALID_RESPONSE")

    def test_human_cycle_preview_mutation_does_not_rewrite_internal_plan(self):
        preview = self.preview()
        preview["params"]["binding"]["deployment"]["host"] = "attacker.example"
        preview["params"]["build"]["commands"][0][0] = "unapproved"
        self.approve(preview)
        self.assertTrue(self.run_cycle().success)
        for call in self.runner.run.call_args_list:
            self.assertNotIn("attacker.example", " ".join(call.args[0]))
            self.assertNotEqual(call.args[0][0], "unapproved")

    def test_orchestrator_real_feedback_edit_and_reapproval_to_pass(self):
        first = self.loop.advance()
        self.assertEqual(first.data["decision"], "AWAITING_EXECUTION_APPROVAL")
        self.assertEqual(first.data["attempts"], 0)
        self.assertEqual(self.loop.advance().data["decision"], "AWAITING_EXECUTION_APPROVAL")
        self.runner.run.assert_not_called()
        self.approve_execution(first)
        self.runner.run.assert_not_called()
        edit = self.loop.advance()
        self.assertEqual(edit.data["decision"], "AWAITING_APPROVAL")
        self.assertEqual(edit.data["attempts"], 1)
        self.assertIn("800", self.source.read_text())
        pending = edit.data["pending_edit"]
        self.assertTrue(self.loop.review_edit(pending["proposal_id"], pending["fingerprint"], approved=True).success)
        self.assertIn("1001", self.source.read_text())
        calls = self.runner.run.call_count
        second = self.loop.advance()
        self.assertEqual(second.data["decision"], "AWAITING_EXECUTION_APPROVAL")
        self.assertEqual(self.runner.run.call_count, calls)
        self.approve_execution(second)
        final = self.loop.advance()
        self.assertEqual(final.data["decision"], "PASS")
        self.assertEqual(final.data["attempts"], 2)
        self.assertEqual(final.data["evidence_source"], "real")
        self.assertEqual([c["execution"]["audit"][-1]["result"]["measurements"]["period_ms"]
                          for c in final.data["cycles"]], [800, 1001])
        self.assertEqual(self.build_number, 2)
        self.loop.advance()
        self.assertEqual(self.build_number, 2)
        self.uart.assert_not_called()

    def test_orchestrator_execution_rejection_or_cancel_never_runs(self):
        first = self.loop.advance()
        preview = first.data["pending_execution"]
        result = self.loop.review_execution(preview["proposal_id"], preview["fingerprint"], approved=False)
        self.assertEqual(result.error_code, "APPROVAL_REJECTED")
        self.assertEqual(self.loop.advance().data["decision"], "STOPPED")
        self.assertEqual(self.run_cycle().error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_incomplete_uart_never_becomes_a_pass(self):
        self.backend.read_target_log = Mock(return_value=OperationResult(True, None, "Captured", "real", data={
            "duration_s": 5, "logs": [], "overflow": True,
        }))
        preview = self.controller.preview_cycle(str(self.project), params=self.params)
        self.approve(preview.data)
        result = self.controller.run_once(str(self.project), params=self.params)
        self.assertEqual(result.data["reason"], "LOG_INCOMPLETE")
        self.period.assert_not_called()

    def test_attempt_limit_stops_without_model_or_repeat_build(self):
        self.controller.max_attempts = 1
        first = self.loop.advance()
        self.approve_execution(first)
        result = self.loop.advance()
        self.assertEqual(result.data["decision"], "FAIL")
        self.assertEqual(result.data["attempts"], 1)
        self.client.generate.assert_not_called()
        self.loop.advance()
        self.assertEqual(self.build_number, 1)
