import unittest
from unittest.mock import Mock

from zhidiao_agent.errors import AgentError, ErrorCode
from zhidiao_agent.models import OperationResult, invoke


class ResultTests(unittest.TestCase):
    def test_human_interrupt_is_structured_cancellation(self):
        def interrupted():
            raise KeyboardInterrupt()
        result = invoke(interrupted, backend="mock_model")
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "CANCELLED")

    def test_result_preserves_hardware_failure_distinction(self):
        result = invoke(
            lambda: {"passed": False, "measurements": {"period_ms": 800}},
            backend="mock",
        )
        payload = result.to_dict()
        self.assertTrue(payload["success"])
        self.assertFalse(payload["passed"])
        self.assertIsNone(payload["error_code"])
        self.assertEqual(payload["contract_version"], "0.2")
        self.assertGreaterEqual(payload["duration_ms"], 0)

    def test_exceptions_are_mapped_and_sanitized(self):
        cases = [
            (TimeoutError("private-details"), ErrorCode.TIMEOUT),
            (ConnectionError("private-details"), ErrorCode.NETWORK_UNREACHABLE),
            (OSError("private-details"), ErrorCode.NETWORK_UNREACHABLE),
            (RuntimeError("private-details"), ErrorCode.INTERNAL_ERROR),
        ]
        for exception, expected in cases:
            with self.subTest(exception=type(exception).__name__):
                operation = Mock(side_effect=exception)
                result = invoke(operation, backend="mock")
                operation.assert_called_once_with()
                self.assertFalse(result.success)
                self.assertEqual(result.error_code, expected.value)
                self.assertNotIn("private-details", result.message)
                self.assertEqual(result.data, {})

    def test_known_service_error_is_preserved(self):
        operation = Mock(
            side_effect=AgentError(
                ErrorCode.SERVICE_ERROR,
                "Service rejected the request.",
                status_code=429,
            )
        )
        result = invoke(operation, backend="nicecode")
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "SERVICE_ERROR")
        self.assertEqual(result.data["status_code"], 429)

    def test_invalid_return_type_is_rejected(self):
        result = invoke(lambda: None, backend="mock")
        self.assertEqual(result.error_code, "INVALID_RESPONSE")

    def test_common_fields_cannot_be_overwritten(self):
        result = invoke(lambda: {"success": False}, backend="mock")
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "INVALID_ARGUMENT")

    def test_inconsistent_success_and_error_are_rejected(self):
        for success, code in ((True, "TIMEOUT"), (False, None)):
            with self.subTest(success=success, code=code):
                with self.assertRaises(AgentError):
                    OperationResult(success, code, "Test", "mock")
