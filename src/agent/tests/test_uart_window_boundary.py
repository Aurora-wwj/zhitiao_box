"""A capture deadline can split an asynchronous line without losing evidence."""

import json
import unittest
from dataclasses import replace
from unittest.mock import Mock

import test_pl_uart as reader_fixture
import test_v05_workflow as workflow_fixture
from zhidiao_agent.agent import Agent
from zhidiao_agent.controller import ReviewedController
from zhidiao_agent.observations import ObservationBackend
from zhidiao_agent.orchestrator import Orchestrator
from zhidiao_agent.presentation import view_model
from zhidiao_agent.session import SessionScope


class WindowBoundaryReaderTests(unittest.TestCase):
    def setUp(self):
        self.case = reader_fixture.UARTReaderTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_recorded_z_and_zh_tails_preserve_all_bytes_without_fatal_truncation(self):
        for tail in (b"Z", b"ZH"):
            with self.subTest(tail=tail):
                raw = b"ZHIDIAO_OK\r\n" * 4 + tail
                capture = self.case.capture(raw, elapsed=5000 if tail == b"Z" else 5010)
                self.assertEqual([row["text"] for row in capture["logs"]], ["ZHIDIAO_OK"] * 4 + [tail.decode()])
                self.assertEqual(capture["bytes_captured"], len(raw))
                self.assertEqual(capture["capture_end_reason"], "deadline")
                self.assertTrue(capture["partial_tail"])
                self.assertFalse(capture["truncated"])
                outcome = ObservationBackend(uart_reader=Mock(return_value=capture)).read_target_log(5)
                self.assertTrue(outcome.success, outcome.to_dict())
                self.assertTrue(outcome.data["partial_tail"])
                self.assertNotIn("passed", outcome.data)

    def test_only_tail_and_split_crlf_are_partial_observations(self):
        for raw in (b"Z", b"ZHIDIAO_OK\r"):
            with self.subTest(raw=raw):
                capture = self.case.capture(raw)
                self.assertTrue(capture["partial_tail"])
                self.assertFalse(capture["truncated"])
                self.assertEqual(capture["logs"][-1]["text"], raw.decode())

    def test_clean_multiline_and_empty_capture_have_no_partial_tail(self):
        for raw in (b"", b"ok\r\n", b"one\ntwo\n"):
            with self.subTest(raw=raw):
                capture = self.case.capture(raw)
                self.assertFalse(capture["partial_tail"])
                self.assertFalse(capture["truncated"])
                self.assertEqual(capture["capture_end_reason"], "deadline")

    def test_capacity_limit_is_fatal_even_if_last_line_is_complete_or_limit_bit_is_missing(self):
        raw = b"ok\n"
        self.case.reader.config = replace(self.case.config,
            uart_observer=replace(self.case.config.uart_observer, max_bytes=len(raw)))
        for limited in (0, 1):
            with self.subTest(limited=limited):
                capture = self.case.capture(raw, limited=limited)
                self.assertFalse(capture["partial_tail"])
                self.assertTrue(capture["truncated"])
                self.assertEqual(capture["capture_end_reason"], "capture_limit")

    def test_partial_tail_never_clears_capacity_or_hardware_or_decode_flags(self):
        for fields in ({"limited": 1}, {"overflow": 1}, {"frame": 1}, {"parity": 1}):
            with self.subTest(fields=fields):
                capture = self.case.capture(b"ok\nZ", **fields)
                self.assertTrue(capture["partial_tail"])
                if "limited" in fields:
                    self.assertTrue(capture["truncated"])
                else:
                    key = {"overflow": "overflow", "frame": "frame_errors", "parity": "parity_errors"}[next(iter(fields))]
                    self.assertTrue(capture[key])
        self.assertEqual(self.case.capture(b"ok\n\xff")["decoding_errors"], 1)
        # A split UTF-8 code point still obeys the strict decoding-error policy.
        self.assertEqual(self.case.capture(b"ok\n\xe6")["decoding_errors"], 1)


class WindowBoundaryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.case = workflow_fixture.FourToolSessionTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def run_cycle(self, output, *, already_pass=False):
        if already_pass:
            self.case.case.source.write_text("const unsigned int gpio_period_ms = 1000;\n", encoding="utf-8")
        self.case.uart_output = output
        controller = ReviewedController(self.case.backend, allowed_roots=self.case.config.allowed_roots)
        loop = Orchestrator(controller, Agent(self.case.case.client), self.case.case.editor,
            task="PA1 full period 1000 ms tolerance 50 ms", project_path=str(self.case.case.project),
            params=self.case.case.params, include_uart=True)
        self.addCleanup(controller.close_status_indicator)
        scope = SessionScope(loop)
        preview = scope.preview()
        self.assertTrue(preview.success, preview.to_dict())
        p = preview.data
        self.assertTrue(scope.review_scope(p["proposal_id"], p["fingerprint"], approved=True).success)
        self.assertEqual(loop.advance().data["decision"], "AWAITING_EXECUTION_APPROVAL")
        self.assertTrue(scope.approve_cycle().success)
        return loop, scope, loop.advance()

    def assert_no_pl(self, result):
        audit = result.data["cycles"][0]["execution"]["audit"]
        self.assertEqual([row["tool_name"] for row in audit],
                         ["build_firmware", "flash_firmware", "read_target_log"])
        self.assertFalse(any("ZHIDIAO_PL_V1" in call.args[0][-1] for call in self.case.runner.run.call_args_list))
        self.case.case.client.generate.assert_not_called()

    def test_four_complete_lines_and_z_tail_continue_to_pl_pass(self):
        _, _, result = self.run_cycle(reader_fixture.envelope(b"ZHIDIAO_OK\r\n" * 4 + b"Z"), already_pass=True)
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["decision"], "PASS")
        audit = result.data["cycles"][0]["execution"]["audit"]
        self.assertEqual([row["tool_name"] for row in audit],
                         ["build_firmware", "flash_firmware", "read_target_log", "run_hardware_test"])
        self.assertTrue(audit[2]["result"]["partial_tail"])
        self.assertTrue(audit[3]["result"]["passed"])

    def test_zh_tail_supports_complete_two_round_fail_edit_rebuild_pass(self):
        loop, scope, first = self.run_cycle(reader_fixture.envelope(b"ZHIDIAO_OK\r\n" * 4 + b"ZH"))
        self.assertEqual(first.data["decision"], "AWAITING_APPROVAL", first.to_dict())
        request = json.loads(self.case.case.client.generate.call_args.args[0][-1]["content"])
        uart = request["context"]["execution"]["audit"][2]["result"]
        self.assertTrue(uart["partial_tail"])
        self.assertFalse(uart["truncated"])
        pending = first.data["pending_edit"]
        self.assertTrue(scope.review_edit(pending["proposal_id"], pending["fingerprint"], approved=True).success)
        self.assertEqual(loop.advance().data["decision"], "AWAITING_EXECUTION_APPROVAL")
        self.assertTrue(scope.approve_cycle().success)
        final = loop.advance()
        self.assertEqual(final.data["decision"], "PASS", final.to_dict())
        self.assertEqual(self.case.uart_calls, 2)
        self.assertTrue(all(len(c["execution"]["audit"]) == 4 for c in final.data["cycles"]))

    def test_capacity_truncation_still_stops_before_pl(self):
        _, _, result = self.run_cycle(reader_fixture.envelope(b"ok\nZ", limited=1))
        self.assertEqual(result.data["reason"], "LOG_INCOMPLETE")
        self.assert_no_pl(result)

    def test_full_line_at_actual_byte_cap_still_stops_without_limit_bit(self):
        raw = b"ok\n"
        config = replace(self.case.config, uart_observer=replace(self.case.config.uart_observer, max_bytes=len(raw)))
        self.case.config = config
        self.case.backend.config = self.case.backend._initial_config = config
        self.case.backend.observations.uart_reader.config = config
        self.case.backend.observations.period_reader.config = config
        _, _, result = self.run_cycle(reader_fixture.envelope(raw))
        self.assertEqual(result.data["reason"], "LOG_INCOMPLETE")
        self.assert_no_pl(result)

    def test_partial_tail_with_any_health_error_still_stops_before_pl(self):
        for fields in ({"overflow": 1}, {"frame": 1}, {"parity": 1}, {"raw": b"ok\n\xff"}):
            with self.subTest(fields=fields):
                self.case.runner.run.reset_mock()
                actual = dict(fields)
                raw = actual.pop("raw", b"ok\nZ")
                _, _, result = self.run_cycle(reader_fixture.envelope(raw, **actual))
                self.assertEqual(result.data["reason"], "LOG_INCOMPLETE")
                self.assert_no_pl(result)

    def test_real_transport_completion_loss_still_stops_before_pl(self):
        for output in (reader_fixture.envelope(b"ok\nZ").rsplit("\n", 1)[0],
                       reader_fixture.envelope(b"ok\nZ")[:-1]):
            with self.subTest(output=output[-20:]):
                self.case.runner.run.reset_mock()
                _, _, result = self.run_cycle(output)
                self.assertEqual(result.data["reason"], "LOG_COLLECTION_FAILED")
                self.assertEqual(result.data["cycles"][0]["execution"]["audit"][-1]["result"]["error_code"], "INVALID_RESPONSE")
                self.assert_no_pl(result)

    def test_legacy_truncated_true_cannot_be_waived_by_a_partial_tail_hint(self):
        for hint in ({}, {"partial_tail": True, "capture_end_reason": "deadline"}):
            with self.subTest(hint=hint):
                self.case.runner.run.reset_mock()
                self.case.backend.observations.uart_reader = Mock(return_value={
                    "logs": [{"timestamp_ms": 1, "text": "ok"}, {"timestamp_ms": 2, "text": "Z"}],
                    "truncated": True, "overflow": False, **hint})
                _, _, result = self.run_cycle("")
                self.assertEqual(result.data["reason"], "LOG_INCOMPLETE")
                self.assert_no_pl(result)


class WindowBoundaryMetadataAndUITests(unittest.TestCase):
    def test_invalid_new_metadata_cannot_enter_evidence(self):
        for fields in ({"partial_tail": 1}, {"capture_end_reason": "unknown"},
                       {"capture_end_reason": []}, {"partial_tail": True},
                       {"capture_end_reason": "capture_limit", "truncated": False}):
            with self.subTest(fields=fields):
                result = ObservationBackend(uart_reader=Mock(return_value={"logs": [], **fields})).read_target_log(5)
                self.assertEqual(result.error_code, "INVALID_RESPONSE")

    def test_ui_marks_tail_without_changing_raw_logs_or_measurement_verdict(self):
        result = {"success": True, "logs": [{"text": "ZHIDIAO_OK"}, {"text": "ZH"}],
                  "partial_tail": True, "truncated": False, "overflow": False, "capture_end_reason": "deadline"}
        report = {"cycles": [{"attempt": 1, "execution": {"audit": [
            {"tool_name": "read_target_log", "result": result}]}}]}
        view = view_model(phase="PASS", scope={}, report=report, pending=None, events=[])
        self.assertEqual(view["status"], "PASS")
        self.assertTrue(view["uart_partial_tail"])
        self.assertIn("末行未闭合", view["uart_text"])
        self.assertEqual(view["uart_logs"], ["ZHIDIAO_OK", "ZH"])
        self.assertEqual(result["logs"][-1]["text"], "ZH")
        result["truncated"] = True
        view = view_model(phase="FAIL", scope={}, report={**report, "reason": "LOG_INCOMPLETE"}, pending=None, events=[])
        self.assertEqual(view["status"], "ERROR")
        self.assertFalse(view["uart_partial_tail"])
        self.assertNotIn("正常结束", view["uart_text"])
        self.assertIn("证据不完整", view["uart_text"])
        self.assertIn("已停止后续 PL", view["reason"])
        self.assertEqual(view["uart_logs"], ["ZHIDIAO_OK", "ZH"])

    def test_next_capture_does_not_inherit_previous_partial_tail_notice(self):
        def cycle(attempt, partial):
            return {"attempt": attempt, "execution": {"audit": [{"tool_name": "read_target_log", "result": {
                "success": True, "logs": [{"text": "new"}], "partial_tail": partial,
                "truncated": False, "overflow": False, "capture_end_reason": "deadline"}}]}}
        view = view_model(phase="PASS", scope={}, report={"cycles": [cycle(1, True), cycle(2, False)]}, pending=None, events=[])
        self.assertEqual(view["uart_attempt"], 2)
        self.assertFalse(view["uart_partial_tail"])
        self.assertNotIn("末行未闭合", view["uart_text"])
