"""LED display semantics and isolation, with no hardware/network dependency."""

import json
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import test_v05_workflow as fixture
import test_audit_fixes as frontend_fixture
from zhidiao_agent.deployment import DeploymentConfig, StatusIndicatorConfig, PLObserverConfig
from zhidiao_agent.errors import AgentError, ErrorCode
from zhidiao_agent.events import WorkflowEvents
from zhidiao_agent.presentation import view_model
from zhidiao_agent.status_indicator import AXIGPIOLedWriter, LEDProgress, LEDStatusAdapter, TOOLS, STARTS
from zhidiao_agent.tools.commands import CommandResult


class RecordingWriter:
    def __init__(self):
        self.values = []
        self.cancelled = threading.Event()
        self.changed = threading.Condition()

    def __call__(self, value):
        with self.changed:
            self.values.append(value)
            self.changed.notify_all()

    def wait_value(self, value):
        with self.changed:
            return self.changed.wait_for(lambda: value in self.values, timeout=2)

    def cancel(self):
        self.cancelled.set()


class LEDProgressTests(unittest.TestCase):
    def setUp(self):
        self.progress = LEDProgress(StatusIndicatorConfig())
        self.sequence = 0

    def emit(self, kind, *, tool=None, attempt=1, now=0, **data):
        self.sequence += 1
        return self.progress.accept({"sequence": self.sequence, "attempt": attempt,
                                     "kind": kind, "tool_name": tool, **data}, now)

    def complete(self, tool, *, attempt=1):
        self.emit(STARTS[tool], tool=tool, attempt=attempt)
        self.emit("TOOL_FINISHED", tool=tool, attempt=attempt, success=True)

    def test_default_off_normal_blink_and_progressive_success(self):
        self.assertEqual(self.progress.value(0), 0xF)
        for index, tool in enumerate(TOOLS):
            self.emit(STARTS[tool], tool=tool)
            self.assertEqual(self.progress.value(.1), 0xF ^ ((1 << (index + 1)) - 1))
            self.assertEqual(self.progress.value(.6), 0xF ^ ((1 << index) - 1))
            self.emit("TOOL_FINISHED", tool=tool, success=True)
            self.assertEqual(self.progress.value(100), 0xF ^ ((1 << (index + 1)) - 1))
        self.emit("PASS")
        self.assertEqual(self.progress.value(200), 0)
        self.assertFalse(self.progress.blinking)

    def test_each_error_preserves_prior_success_and_double_blinks_only_failed_tool(self):
        for failed in range(4):
            self.setUp()
            for tool in TOOLS[:failed]:
                self.complete(tool)
            tool = TOOLS[failed]
            self.emit(STARTS[tool], tool=tool)
            self.emit("TOOL_FINISHED", tool=tool, success=False)
            base = (1 << failed) - 1
            for now in (.01, .25, 1.01, 1.25):
                self.assertEqual(self.progress.value(now), 0xF ^ (base | (1 << failed)))
            for now in (.13, .4, .9, 1.4):
                self.assertEqual(self.progress.value(now), 0xF ^ base)
            self.emit("STOPPED")
            self.assertEqual(self.progress.failed, failed)

    def test_physical_fail_analysis_waiting_and_new_attempt(self):
        for tool in TOOLS:
            self.emit(STARTS[tool], tool=tool)
            self.emit("TOOL_FINISHED", tool=tool, success=True, passed=False)
        for kind in ("ANALYZING", "ANALYSIS_FINISHED", "WAITING_APPROVAL", "APPLYING_EDIT", "EDIT_APPLIED"):
            self.emit(kind)
            self.assertEqual(self.progress.value(5), 0)
            self.assertIsNone(self.progress.failed)
        self.emit("BUILDING", tool=TOOLS[0], attempt=2, now=10)
        self.assertEqual(self.progress.completed, 0)
        self.assertEqual(self.progress.value(10.6), 0xF)
        self.assertEqual(self.progress.value(10.1), 0xE)

    def test_error_reset_and_stale_events_cannot_restore_previous_attempt(self):
        self.emit("BUILDING", tool=TOOLS[0])
        self.emit("TOOL_FINISHED", tool=TOOLS[0], success=False)
        self.emit("BUILDING", tool=TOOLS[0], attempt=2)
        self.assertIsNone(self.progress.failed)
        self.assertFalse(self.emit("TOOL_FINISHED", tool=TOOLS[0], attempt=1, success=False))
        self.assertEqual(self.progress.attempt, 2)
        old = {"sequence": 1, "kind": "BUILDING", "tool_name": TOOLS[0], "attempt": 3}
        self.assertFalse(self.progress.accept(old, 0))
        self.assertEqual(self.progress.attempt, 2)

    def test_unknown_tool_invalid_success_and_non_tool_error_do_not_fake_progress(self):
        self.assertFalse(self.emit("BUILDING", tool="devmem"))
        self.assertEqual(self.progress.value(0), 0xF)
        self.emit("BUILDING", tool=TOOLS[0])
        self.assertFalse(self.emit("TOOL_FINISHED", tool=TOOLS[0], success=1))
        self.emit("TOOL_FINISHED", tool=TOOLS[0], success=True)
        self.emit("ERROR")
        self.assertEqual(self.progress.completed, 1)
        self.assertIsNone(self.progress.failed)

    def test_stop_during_active_tool_marks_that_tool_as_error(self):
        self.emit("BUILDING", tool=TOOLS[0])
        self.emit("ERROR")
        self.assertEqual(self.progress.failed, 0)

    def test_pl_only_pass_does_not_claim_uart_was_called(self):
        for tool in (TOOLS[0], TOOLS[1], TOOLS[3]):
            self.complete(tool)
        self.emit("PASS")
        self.assertEqual(self.progress.value(100), 0x4)

    def test_active_high_configuration(self):
        self.progress = LEDProgress(StatusIndicatorConfig(active_low=False))
        self.assertEqual(self.progress.value(0), 0)
        self.complete(TOOLS[0])
        self.assertEqual(self.progress.value(0), 1)


class LEDAdapterTests(unittest.TestCase):
    def setUp(self):
        self.events = WorkflowEvents()
        self.config = DeploymentConfig(allowed_roots=(str(Path.cwd()),), status_indicator=StatusIndicatorConfig())
        self.writer = RecordingWriter()
        self.adapter = LEDStatusAdapter(self.config, self.events, writer=self.writer)
        self.addCleanup(self.adapter.close)

    def test_no_write_before_approved_tool_start_and_final_mask_is_flushed_on_close(self):
        for kind in ("TASK_ACCEPTED", "TARGET_PARSED", "WAITING_APPROVAL"):
            self.events.emit(kind, attempt=1)
        self.assertEqual(self.writer.values, [])
        for tool in TOOLS:
            self.events.emit(STARTS[tool], attempt=1, tool_name=tool)
            self.events.emit("TOOL_FINISHED", attempt=1, tool_name=tool, success=True, passed=False)
        self.events.emit("PASS", attempt=1)
        self.adapter.close()
        self.assertEqual(self.writer.values[-1], 0)
        self.assertTrue(all(type(v) is int and 0 <= v <= 15 for v in self.writer.values))
        before = list(self.writer.values)
        self.events.emit("BUILDING", attempt=2, tool_name=TOOLS[0])
        self.assertEqual(self.writer.values, before)

    def test_background_worker_really_blinks_without_blocking_event_sender(self):
        self.events.emit("BUILDING", attempt=1, tool_name=TOOLS[0])
        self.assertTrue(self.writer.wait_value(0xE))
        self.assertTrue(self.writer.wait_value(0xF))
        self.events.emit("TOOL_FINISHED", attempt=1, tool_name=TOOLS[0], success=True)
        self.adapter.close()
        self.assertEqual(self.writer.values[-1], 0xE)

    def test_write_failure_is_one_sanitized_warning_and_no_retry_storm(self):
        self.adapter.close()
        broken = Mock(side_effect=OSError("SECRET token=do-not-log"))
        self.adapter = LEDStatusAdapter(self.config, self.events, writer=broken)
        with self.assertLogs("zhidiao_agent.status_indicator", level="WARNING") as logs:
            self.events.emit("BUILDING", attempt=1, tool_name=TOOLS[0])
            thread = self.adapter._thread
            if thread is not None:
                thread.join(timeout=2)
        self.events.emit("FLASHING", attempt=1, tool_name=TOOLS[1])
        broken.assert_called_once()
        errors = [row for row in self.events.snapshot() if row["kind"] == "INDICATOR_ERROR"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["error_code"], "STATUS_INDICATOR_UNAVAILABLE")
        self.assertNotIn("SECRET", str(logs.output) + str(errors))

    def test_worker_start_failure_warns_once_and_success_can_close_without_join_error(self):
        with patch("zhidiao_agent.status_indicator.threading.Thread.start", side_effect=RuntimeError("hidden")) as start, \
                self.assertLogs("zhidiao_agent.status_indicator", level="WARNING"):
            self.events.emit("BUILDING", attempt=1, tool_name=TOOLS[0])
            self.events.emit("TOOL_FINISHED", attempt=1, tool_name=TOOLS[0], success=True)
            self.events.emit("FLASHING", attempt=1, tool_name=TOOLS[1])
            self.adapter.close()
        start.assert_called_once()
        self.assertIsNone(self.adapter._thread)
        self.assertTrue(self.adapter._disabled)
        self.assertEqual(self.writer.values, [])
        warnings = [row for row in self.events.snapshot() if row["kind"] == "INDICATOR_ERROR"]
        self.assertEqual([row["error_code"] for row in warnings], ["STATUS_INDICATOR_UNAVAILABLE"])

    def test_slow_indicator_cannot_block_tools_and_close_cancels_its_own_transport(self):
        self.adapter.close()
        entered = threading.Event()
        class SlowWriter(RecordingWriter):
            def __call__(self, value):
                entered.set()
                self.cancelled.wait(timeout=2)
        writer = SlowWriter()
        self.adapter = LEDStatusAdapter(self.config, self.events, writer=writer)
        self.events.emit("BUILDING", attempt=1, tool_name=TOOLS[0])
        self.assertTrue(entered.wait(timeout=1))
        self.events.emit("FLASHING", attempt=1, tool_name=TOOLS[1])
        self.assertFalse(writer.cancelled.is_set())
        self.adapter.close()
        self.assertTrue(writer.cancelled.is_set())
        self.assertIsNone(self.adapter._thread)

    def test_bad_event_listener_cannot_break_emission_or_other_listeners(self):
        bad = self.events.subscribe(Mock(side_effect=RuntimeError("hidden")))
        seen = []
        good = self.events.subscribe(seen.append)
        self.events.emit("BUILDING", attempt=1, tool_name=TOOLS[0])
        bad(); good()
        self.assertEqual(seen[0]["kind"], "BUILDING")
        self.assertIn("EVENT_LISTENER_FAILED", str(self.events.snapshot()))


class LEDConfigTransportTests(unittest.TestCase):
    def test_optional_json_roundtrip_and_strict_fixed_address_validation(self):
        with TemporaryDirectory() as root:
            profile = Path(root) / "deployment.json"
            document = {"allowed_roots": [root]}
            profile.write_text(json.dumps(document))
            self.assertIsNone(DeploymentConfig.load(str(profile)).status_indicator)
            for indicator in (None, {"type": "axi_gpio_led_bar", "data_addr": "0x43C60000", "active_low": True}):
                document["status_indicator"] = indicator
                profile.write_text(json.dumps(document))
                self.assertEqual(DeploymentConfig.load(str(profile)).status_indicator,
                                 StatusIndicatorConfig() if indicator else None)
            for indicator in ([], "on", {"data_addr": "0x43C60004"}, {"data_addr": "0x43C60000; id"},
                              {"type": "shell"}, {"active_low": 1}, {"command": "anything"}):
                document["status_indicator"] = indicator
                profile.write_text(json.dumps(document))
                with self.assertRaises(AgentError):
                    DeploymentConfig.load(str(profile))

    def test_led_cannot_alias_a_period_register(self):
        with self.assertRaises(AgentError):
            DeploymentConfig(allowed_roots=(str(Path.cwd()),), status_indicator=StatusIndicatorConfig(),
                             observer=PLObserverConfig(period_addr="0x43C60000"))

    def test_writer_has_one_fixed_address_four_bit_values_strict_ssh_and_timeout(self):
        with TemporaryDirectory() as root:
            hosts = Path(root) / "known_hosts"
            hosts.write_text("trusted host fixture")
            config = DeploymentConfig(allowed_roots=(root,), known_hosts=str(hosts),
                                      status_indicator=StatusIndicatorConfig())
            runner = Mock(run=Mock(return_value=CommandResult(0, "")))
            writer = AXIGPIOLedWriter(config, runner=runner)
            for value in range(16):
                writer(value)
                argv, timeout = runner.run.call_args.args
                self.assertEqual(argv[-1], f"/bin/busybox devmem 0x43C60000 32 0x{value:X}")
                self.assertIn("BatchMode=yes", argv)
                self.assertIn("StrictHostKeyChecking=yes", argv)
                self.assertEqual(timeout, 2)
            self.assertEqual(runner.run.call_count, 16)
            for value in (-1, 16, True, "0x0", "0; reboot", None):
                with self.assertRaises(AgentError):
                    writer(value)
            self.assertEqual(runner.run.call_count, 16)
            runner.run.return_value = CommandResult(255, "sensitive output")
            with self.assertRaises(AgentError):
                writer(0)


class LEDWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.FourToolSessionTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        config = replace(self.case.config, status_indicator=StatusIndicatorConfig())
        self.case.config = config
        self.case.backend.config = self.case.backend._initial_config = config
        self.case.backend.observations.uart_reader.config = config
        self.case.backend.observations.period_reader.config = config
        self.writer = RecordingWriter()
        self.writer_class = self.enterContext(patch("zhidiao_agent.status_indicator.AXIGPIOLedWriter", return_value=self.writer))
        self.addCleanup(self.case.controller.close_status_indicator)

    def test_full_native_fake_fail_edit_pass_preserves_verdict_and_resets_attempt(self):
        pending = self.case.first_failure()
        self.assertTrue(self.writer.wait_value(0))
        indicator = self.case.controller._status_indicator
        self.assertEqual(indicator._progress.completed, 15)
        self.assertIsNone(indicator._progress.failed)
        self.assertTrue(self.case.scope.review_edit(pending["proposal_id"], pending["fingerprint"], approved=True).success)
        self.case.loop.advance()
        self.case.scope.approve_cycle()
        final = self.case.loop.advance()
        self.case.controller.close_status_indicator()
        self.assertEqual(final.data["decision"], "PASS")
        self.assertEqual(indicator._progress.attempt, 2)
        self.assertEqual(self.writer.values[-1], 0)
        self.assertEqual([len(c["execution"]["audit"]) for c in final.data["cycles"]], [4, 4])

    def test_led_failure_does_not_change_tool_success_or_prevent_pass(self):
        class BrokenWriter(RecordingWriter):
            def __call__(self, value):
                raise OSError("indicator only")
        self.writer_class.return_value = BrokenWriter()
        pending = self.case.first_failure()
        indicator = self.case.controller._status_indicator
        thread = indicator._thread
        if thread is not None:
            thread.join(timeout=2)
        self.assertTrue(any(e["kind"] == "INDICATOR_ERROR" for e in self.case.loop.report()["events"]))
        self.case.scope.review_edit(pending["proposal_id"], pending["fingerprint"], approved=True)
        self.case.loop.advance(); self.case.scope.approve_cycle()
        final = self.case.loop.advance()
        self.assertEqual(final.data["decision"], "PASS")
        self.assertTrue(all(row["result"]["success"] for cycle in final.data["cycles"] for row in cycle["execution"]["audit"]))

    def test_unapproved_rejected_or_changed_scope_never_starts_indicator(self):
        preview = self.case.scope.preview().data
        self.writer_class.assert_not_called()
        changed = replace(self.case.config, status_indicator=StatusIndicatorConfig(active_low=False))
        self.case.backend.config = changed
        result = self.case.scope.review_scope(preview["proposal_id"], preview["fingerprint"], approved=True)
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.writer_class.assert_not_called()
        self.assertEqual(self.writer.values, [])

    def test_tool_exception_emits_failed_finish_and_double_blink(self):
        self.case.accept_scope()
        self.case.loop.advance()
        self.case.scope.approve_cycle()
        self.case.backend.build_firmware = Mock(side_effect=TimeoutError("build timeout"))
        result = self.case.loop.advance()
        self.assertFalse(result.success)
        rows = [r for r in self.case.loop.report()["events"] if r["kind"] == "TOOL_FINISHED"]
        self.assertEqual(rows[-1]["tool_name"], "build_firmware")
        self.assertFalse(rows[-1]["success"])
        self.assertEqual(rows[-1]["error_code"], result.error_code)
        self.assertEqual(result.error_code, "TIMEOUT")
        self.assertEqual(self.case.controller._status_indicator._progress.failed, 0)

    def test_missing_config_creates_no_indicator(self):
        self.case.config = replace(self.case.config, status_indicator=None)
        self.case.backend.config = self.case.backend._initial_config = self.case.config
        self.case.backend.observations.uart_reader.config = self.case.config
        self.case.backend.observations.period_reader.config = self.case.config
        self.case.first_failure()
        self.writer_class.assert_not_called()
        self.assertIsNone(self.case.controller._status_indicator)


class LEDFrontendTests(unittest.TestCase):
    def setUp(self):
        self.case = frontend_fixture.RealFrontendAuditTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        base = self.case.case
        base.config = replace(base.config, status_indicator=StatusIndicatorConfig())
        base.backend.config = base.backend._initial_config = base.config
        base.backend.observations.uart_reader.config = base.config
        base.backend.observations.period_reader.config = base.config
        self.writer = RecordingWriter()
        self.enterContext(patch("zhidiao_agent.status_indicator.AXIGPIOLedWriter", return_value=self.writer))

    def test_real_ui_full_cycle_flushes_pass_state_and_closes_consumer(self):
        service = self.case.service()
        state = self.case.review(service, self.case.start(service))
        state = self.case.review(service, state)
        self.assertEqual(state["phase"], "PASS")
        indicator = service._loop.controller._status_indicator
        self.assertTrue(service.close().success)
        self.assertTrue(indicator._closed)
        self.assertEqual(self.writer.values[-1], 0)

    def test_new_ui_task_stops_previous_error_blink_worker(self):
        service = self.case.service()
        start = self.case.start(service)
        self.case.case.backend.build_firmware = Mock(side_effect=AgentError(ErrorCode.TIMEOUT, "test error"))
        state = self.case.review(service, start)
        self.assertEqual(state["phase"], "STOPPED")
        indicator = service._loop.controller._status_indicator
        self.assertTrue(indicator._progress.blinking)
        state = self.case.start(service)
        self.assertEqual(state["phase"], "AWAITING_GOAL_APPROVAL")
        self.assertTrue(indicator._closed)
        self.assertIsNone(indicator._thread)

    def test_cli_closes_consumer_and_keeps_final_success_mask(self):
        with patch.object(LEDStatusAdapter, "close", autospec=True, side_effect=LEDStatusAdapter.close) as closed:
            result = self.case.cli()
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["decision"], "PASS")
        self.assertEqual(self.writer.values[-1], 0)
        closed.assert_called_once()
        self.assertTrue(closed.call_args.args[0]._closed)

    def test_worker_start_failure_does_not_change_cli_pass_or_its_cleanup(self):
        with patch("zhidiao_agent.status_indicator.threading.Thread.start", side_effect=RuntimeError("hidden")), \
                self.assertLogs("zhidiao_agent.status_indicator", level="WARNING"):
            result = self.case.cli()
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["decision"], "PASS")
        self.assertEqual(self.writer.values, [])
        warnings = [row for row in result.data["events"] if row["kind"] == "INDICATOR_ERROR"]
        self.assertEqual(len(warnings), 1)
        self.assertTrue(all(row["result"]["success"] for cycle in result.data["cycles"]
                            for row in cycle["execution"]["audit"]))

    def test_indicator_warning_cannot_replace_ui_tool_stage_or_verdict(self):
        events = [{"kind": "BUILDING", "attempt": 1, "tool_name": TOOLS[0]},
                  {"kind": "INDICATOR_ERROR", "attempt": 1, "error_code": "STATUS_INDICATOR_UNAVAILABLE"}]
        view = view_model(phase="RUNNING", scope={}, report={}, pending=None,
                          events=events, goal=None, last_result=None, busy=True)
        self.assertEqual(view["stage_label"], "编译固件")
        self.assertEqual(view["steps"][1]["state"], "active")
        view = view_model(phase="PASS", scope={}, report={"decision": "PASS"}, pending=None,
                          events=events, goal=None, last_result=None, busy=False)
        self.assertEqual(view["status"], "PASS")

    def test_changed_indicator_after_scope_approval_blocks_build_without_led_write(self):
        base = self.case.case
        preview = base.accept_scope()
        self.assertEqual(preview["params"]["scope"]["deployment"]["status_indicator"]["data_addr"], "0x43C60000")
        base.backend.config = replace(base.config, status_indicator=None)
        self.assertFalse(base.scope.approve_cycle().success)
        self.assertEqual(self.writer.values, [])
