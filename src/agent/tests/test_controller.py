import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from zhidiao_agent.controller import Controller
from zhidiao_agent.models import OperationResult
from zhidiao_agent.tools.mock_backend import MockBackend
from zhidiao_agent.tools.real_backend import RealBackend


class ControllerTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="zhidiao-controller-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "allowed root"
        self.root.mkdir()
        self.project = str(self.root / "project")

    def controller(self, backend=None, **kwargs):
        return Controller(
            backend if backend is not None else MockBackend(),
            allowed_roots=(str(self.root),), **kwargs,
        )

    def test_success_has_ordered_audit(self):
        result = self.controller().run(self.project)
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["decision"], "PASS")
        self.assertEqual([row["tool_name"] for row in result.data["audit"]], [
            "build_firmware", "flash_firmware", "read_target_log", "run_hardware_test",
        ])

    def test_build_failure_stops_before_flash(self):
        backend = Mock(wraps=MockBackend())
        backend.requires_approval = False
        backend.name = "mock"
        backend.build_firmware.return_value = OperationResult(False, "BUILD_FAILED", "Failed", "mock")
        result = self.controller(backend).run(self.project)
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["reason"], "BUILD_FAILED")
        backend.flash_firmware.assert_not_called()

    def test_unverified_flash_stops_before_uart(self):
        backend = Mock(wraps=MockBackend())
        backend.requires_approval = False
        backend.name = "mock"
        backend.flash_firmware.return_value = OperationResult(
            True, None, "Done", "mock", data={"verified": False},
        )
        result = self.controller(backend).run(self.project)
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["reason"], "FLASH_NOT_VERIFIED")
        backend.read_target_log.assert_not_called()

    def test_measurement_mismatch_has_bounded_retries(self):
        result = self.controller().run(
            self.project, params={"expected_period_ms": 800, "tolerance_ms": 50},
        )
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["decision"], "FAIL")
        self.assertEqual(result.data["attempts"], 3)
        self.assertEqual(len(result.data["audit"]), 12)

    def test_real_backend_never_runs_automatically(self):
        backend = Mock(wraps=RealBackend())
        backend.requires_approval = True
        result = self.controller(backend).run(self.project)
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        backend.build_firmware.assert_not_called()

    def test_paths_and_attempt_limits(self):
        for path in (
            "relative",
            str(self.root.parent / "outside"),
            str(self.root / ".." / "outside"),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.controller().run(path).error_code, "INVALID_ARGUMENT")
        for attempts in (0, 4, True):
            with self.subTest(attempts=attempts):
                self.assertEqual(
                    self.controller(max_attempts=attempts).run(self.project).error_code,
                    "INVALID_ARGUMENT",
                )
                self.assertEqual(self.controller(max_attempts=attempts).run_once(self.project).error_code, "INVALID_ARGUMENT")

    def test_backend_exception_is_sanitized(self):
        backend = Mock(wraps=MockBackend())
        backend.requires_approval = False
        backend.build_firmware.side_effect = RuntimeError("private")
        result = self.controller(backend).run(self.project)
        self.assertEqual(result.error_code, "INTERNAL_ERROR")
        self.assertNotIn("private", result.message)

    def test_uart_failure_stops_measurement(self):
        backend = Mock(wraps=MockBackend())
        backend.requires_approval = False
        backend.name = "mock"
        backend.read_target_log.return_value = OperationResult(
            False, "UART_READ_FAILED", "Failed", "mock",
        )
        result = self.controller(backend).run(self.project)
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["reason"], "LOG_COLLECTION_FAILED")
        backend.run_hardware_test.assert_not_called()

    def test_measurement_tool_failure_does_not_retry(self):
        backend = Mock(wraps=MockBackend())
        backend.requires_approval = False
        backend.name = "mock"
        backend.run_hardware_test.return_value = OperationResult(
            False, "PL_TEST_UNAVAILABLE", "Failed", "mock",
        )
        result = self.controller(backend).run(self.project)
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["reason"], "MEASUREMENT_TOOL_FAILED")
        self.assertEqual(result.data["attempts"], 1)
        backend.build_firmware.assert_called_once()

    def test_artifact_outside_allowed_root_never_flashes(self):
        backend = Mock(wraps=MockBackend())
        backend.requires_approval = False
        backend.name = "mock"
        backend.build_firmware.return_value = OperationResult(
            True, None, "Done", "mock",
            data={"artifact_path": str(self.root.parent / "outside" / "firmware.hex")},
        )
        result = self.controller(backend).run(self.project)
        self.assertEqual(result.error_code, "INVALID_ARGUMENT")
        backend.flash_firmware.assert_not_called()

    def test_invalid_gpio_goal_stops_before_build(self):
        backend = Mock(wraps=MockBackend())
        backend.requires_approval = False
        result = self.controller(backend).run(self.project, params={"expected_period_ms": 1000, "tolerance_ms": -1})
        self.assertEqual(result.error_code, "INVALID_ARGUMENT")
        backend.build_firmware.assert_not_called()
