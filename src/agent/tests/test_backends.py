import unittest

from zhidiao_agent.tools.mock_backend import MockBackend
from zhidiao_agent.tools.real_backend import RealBackend


class BackendTests(unittest.TestCase):
    def test_mock_workflow(self):
        backend = MockBackend()
        build = backend.build_firmware("/project")
        self.assertTrue(build.success)
        flash = backend.flash_firmware(build.data["artifact_path"])
        self.assertTrue(flash.success)
        self.assertTrue(flash.data["verified"])
        self.assertEqual(flash.data["remote_path"], "/sd/firmware/mock_run/firmware.hex")
        self.assertTrue(backend.read_target_log(5).success)
        result = backend.run_hardware_test(
            "gpio_period", {"expected_period_ms": 1000, "tolerance_ms": 50}
        )
        self.assertTrue(result.success)
        self.assertTrue(result.data["passed"])

    def test_measurement_failure_is_not_tool_failure(self):
        result = MockBackend().run_hardware_test(
            "gpio_period", {"expected_period_ms": 800, "tolerance_ms": 50}
        )
        self.assertTrue(result.success)
        self.assertFalse(result.data["passed"])

    def test_invalid_inputs(self):
        backend = MockBackend()
        calls = [
            lambda: backend.build_firmware(""),
            lambda: backend.flash_firmware("firmware.bin"),
            lambda: backend.read_target_log(True),
            lambda: backend.read_target_log(61),
            lambda: backend.run_hardware_test("gpio_period", {}),
            lambda: backend.run_hardware_test("gpio_period", None),
        ]
        for call in calls:
            with self.subTest(call=call):
                self.assertEqual(call().error_code, "INVALID_ARGUMENT")

    def test_real_backend_is_explicitly_unavailable(self):
        backend = RealBackend()
        self.assertTrue(backend.requires_approval)
        results = [
            backend.build_firmware("/project"),
            backend.flash_firmware("firmware.hex"),
            backend.read_target_log(5),
            backend.run_hardware_test("gpio_period", {}),
        ]
        for result in results:
            self.assertFalse(result.success)
            self.assertEqual(result.error_code, "BACKEND_UNAVAILABLE")
