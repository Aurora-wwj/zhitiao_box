import unittest
from unittest.mock import Mock

from zhidiao_agent.observations import ObservationBackend


class ObservationTests(unittest.TestCase):
    def test_empty_uart_capture_success_and_completeness_metadata(self):
        for data in ([], {"logs": [], "overflow": False, "truncated": False}):
            result = ObservationBackend(uart_reader=Mock(return_value=data)).read_target_log(1)
            self.assertTrue(result.success)
            self.assertEqual(result.data["logs"], [])
            self.assertNotIn("passed", result.data)
        result = ObservationBackend(uart_reader=Mock(return_value={
            "logs": [{"timestamp_ms": 0, "text": "partial"}], "overflow": True,
            "truncated": True, "decoding_errors": 1,
        })).read_target_log(1)
        self.assertTrue(result.success)
        self.assertTrue(result.data["overflow"])
        self.assertTrue(result.data["truncated"])
        self.assertEqual(result.data["decoding_errors"], 1)

    def test_invalid_uart_metadata_or_non_unicode_text(self):
        for data in ({"logs": [], "overflow": 1}, {"logs": [], "passed": True},
                     {"logs": [], "decoding_errors": True},
                     [{"timestamp_ms": 0, "text": b"\xff"}],
                     [{"timestamp_ms": 0, "text": "\ud800"}]):
            result = ObservationBackend(uart_reader=Mock(return_value=data)).read_target_log(1)
            self.assertEqual(result.error_code, "INVALID_RESPONSE")

    def test_acquisition_metadata_retained_without_overriding_verdict(self):
        data = {"period_ms": 600.96, "high_ms": 300.48, "duty_cycle": 0.5,
                "period_ticks": 60096000, "edge_start": 0xffffffff, "edge_end": 1,
                "fresh_edges": 2, "valid": 1, "pl_clock_hz": 100000000,
                "freshness_verified": True, "evidence_source": "real_pl", "passed": True}
        result = ObservationBackend(period_reader=Mock(return_value=data)).run_hardware_test(
            "gpio_period", {"expected_period_ms": 1000, "tolerance_ms": 50})
        self.assertTrue(result.success, result.to_dict())
        self.assertFalse(result.data["passed"])
        self.assertEqual(result.data["observation"]["fresh_edges"], 2)
        self.assertEqual(result.data["measurements"]["high_ms"], 300.48)

    def test_uart_collection_success_does_not_claim_firmware_pass(self):
        reader = Mock(return_value=[{"timestamp_ms": 0, "text": "FW_ERROR"}])
        result = ObservationBackend(uart_reader=reader).read_target_log(5)
        self.assertTrue(result.success)
        self.assertNotIn("passed", result.data)
        self.assertEqual(result.data["logs"][0]["text"], "FW_ERROR")
        reader.assert_called_once_with(5, 20)

    def test_physical_verdict_is_computed_from_period(self):
        reader = Mock(return_value={"period_ms": 800, "passed": True})
        result = ObservationBackend(period_reader=reader).run_hardware_test(
            "gpio_period", {"expected_period_ms": 1000, "tolerance_ms": 50},
        )
        self.assertTrue(result.success)
        self.assertFalse(result.data["passed"])
        self.assertEqual(result.data["measurements"]["period_ms"], 800)
        reader.return_value = {"period_ms": 1001}
        self.assertTrue(ObservationBackend(period_reader=reader).run_hardware_test(
            "gpio_period", {"expected_period_ms": 1000, "tolerance_ms": 50},
        ).data["passed"])

    def test_bad_parameters_never_call_hardware_provider(self):
        reader = Mock()
        backend = ObservationBackend(uart_reader=reader, period_reader=reader)
        for duration in (True, 0, -1, 61, float("nan")):
            self.assertEqual(backend.read_target_log(duration).error_code, "INVALID_ARGUMENT")
        for params in ({}, {"expected_period_ms": 1000, "tolerance_ms": -1},
                       {"expected_period_ms": True, "tolerance_ms": 50}):
            self.assertEqual(backend.run_hardware_test("gpio_period", params).error_code, "INVALID_ARGUMENT")
        reader.assert_not_called()

    def test_no_hardware_binding_is_explicitly_unavailable(self):
        backend = ObservationBackend()
        self.assertEqual(backend.read_target_log(1).error_code, "BACKEND_UNAVAILABLE")
        self.assertEqual(backend.run_hardware_test("gpio_period", {
            "expected_period_ms": 1000, "tolerance_ms": 50,
        }).error_code, "BACKEND_UNAVAILABLE")

    def test_invalid_uart_response_is_rejected(self):
        responses = [None, ["bad"], [{"timestamp_ms": -1, "text": "bad"}],
                     [{"timestamp_ms": 1, "text": "a"}, {"timestamp_ms": 0, "text": "b"}],
                     [{"timestamp_ms": 0, "text": "x" * 16385}]]
        for response in responses:
            with self.subTest(response_type=type(response)):
                reader = Mock(return_value=response)
                self.assertEqual(ObservationBackend(uart_reader=reader).read_target_log(1).error_code, "INVALID_RESPONSE")

    def test_invalid_measurements_and_provider_timeouts(self):
        params = {"expected_period_ms": 1000, "tolerance_ms": 50}
        for response in (None, {}, {"period_ms": float("inf")}, {"period_ms": True}, {"period_ms": 1e-320}):
            result = ObservationBackend(period_reader=Mock(return_value=response)).run_hardware_test("gpio_period", params)
            self.assertEqual(result.error_code, "INVALID_RESPONSE")
        reader = Mock(side_effect=TimeoutError("private details"))
        self.assertEqual(ObservationBackend(uart_reader=reader).read_target_log(1).error_code, "TIMEOUT")
        self.assertEqual(ObservationBackend(period_reader=reader).run_hardware_test("gpio_period", params).error_code, "TIMEOUT")
