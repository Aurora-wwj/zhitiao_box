"""FPGA loading remains a child of an explicitly approved observation cycle."""

import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import test_real_workflow
from zhidiao_agent.controller import ReviewedController
from zhidiao_agent.deployment import PLObserverConfig
from zhidiao_agent.real_cli import real_operation
from zhidiao_agent.tools.commands import CommandResult
from zhidiao_agent.tools.real_backend import RealBackend


class PreparationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_real_workflow.ReviewedRealWorkflowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.sha = "a" * 64
        self.config = replace(self.fixture.config, observer=PLObserverConfig(
            prepare_policy="load_verified", bitstream="/sd/pl/measurement.bit", bitstream_sha256=self.sha))
        self.runner = Mock()
        self.runner.run.side_effect = self.command
        self.backend = RealBackend(self.config, runner=self.runner)
        self.uart = Mock(return_value=[])
        self.backend.observations.uart_reader = self.uart
        self.controller = ReviewedController(self.backend, allowed_roots=self.config.allowed_roots)
        self.params = self.fixture.params
        self.loads = self.measures = 0

    def command(self, argv, timeout):
        if argv[0] == "ssh" and "ZHIDIAO_PREP_V1" in argv[-1]:
            self.loads += 1
            return CommandResult(0, f"ZHIDIAO_PREP_V1 LOADED {self.sha} 1")
        if argv[0] == "ssh" and "ZHIDIAO_PL_V1" in argv[-1]:
            self.measures += 1
            return CommandResult(0, "ZHIDIAO_PL_V1 0 2 2 1 100100000 50050000")
        return self.fixture.fake_process(argv, timeout)

    def preview(self):
        result = self.controller.preview_cycle(str(self.fixture.project), params=self.params)
        self.assertTrue(result.success, result.to_dict())
        return result.data

    def approve(self, preview):
        result = self.controller.review_cycle(preview["proposal_id"], preview["fingerprint"], approved=True)
        self.assertTrue(result.success, result.to_dict())

    def test_no_fpga_loading_without_approval_or_available_provider(self):
        result = self.backend.run_hardware_test("gpio_period", self.params)
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.backend.observations.uart_reader = None
        self.assertEqual(self.backend.read_target_log(1).error_code, "BACKEND_UNAVAILABLE")
        self.assertEqual(self.backend.run_hardware_test("gpio_period", {}).error_code, "INVALID_ARGUMENT")
        self.runner.run.assert_not_called()

    def test_cycle_preview_discloses_exact_image_and_loading_effect(self):
        preview = self.preview()
        internal = preview["params"]["internal_preparation"]
        self.assertTrue(internal["requires_loading"])
        self.assertEqual(internal["observer"]["bitstream_sha256"], self.sha)
        self.assertIn("/dev/xdevcfg", internal["effects"])
        self.assertEqual(preview["params"]["observed_gpio"], "PA1")
        self.runner.run.assert_not_called()

    def test_load_once_before_uart_and_pl_then_reload_only_for_next_approved_cycle(self):
        self.approve(self.preview())
        result = self.controller.run_once(str(self.fixture.project), params=self.params)
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["decision"], "PASS")
        self.assertEqual((self.loads, self.measures), (1, 1))
        self.assertTrue(result.data["audit"][2]["result"]["preparation"]["loaded"])
        self.assertEqual(result.data["audit"][3]["result"]["observed_gpio"], "PA1")
        self.assertEqual(self.controller.run_once(str(self.fixture.project), params=self.params).error_code,
                         "APPROVAL_REQUIRED")
        self.assertEqual(self.loads, 1)
        self.approve(self.preview())
        result = self.controller.run_once(str(self.fixture.project), params=self.params)
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual((self.loads, self.measures), (2, 2))

    def test_image_check_failure_stops_before_any_uart_or_measurement(self):
        original = self.command
        def command(argv, timeout):
            if argv[0] == "ssh" and "ZHIDIAO_PREP_V1" in argv[-1]:
                return CommandResult(76, "private details")
            return original(argv, timeout)
        self.runner.run.side_effect = command
        self.approve(self.preview())
        result = self.controller.run_once(str(self.fixture.project), params=self.params)
        self.assertEqual(result.data["decision"], "FAIL")
        self.assertEqual(result.data["reason"], "LOG_COLLECTION_FAILED")
        self.uart.assert_not_called()
        self.assertEqual(self.measures, 0)

    def test_standalone_observation_derives_loading_only_after_human_review(self):
        with patch("zhidiao_agent.real_cli.DeploymentConfig.load", return_value=self.config), \
             patch("zhidiao_agent.real_cli.RealBackend", return_value=self.backend), \
             patch("zhidiao_agent.real_cli.human_review") as ui:
            from zhidiao_agent.models import OperationResult
            ui.return_value = OperationResult(True, None, "Approved", "mock", data={"approved": True})
            result = real_operation("real-test", "fixture.json", preview_only=True, params=self.params)
            self.assertTrue(result.success)
            ui.assert_not_called()
            self.runner.run.assert_not_called()
            result = real_operation("real-test", "fixture.json", preview_only=False, params=self.params)
        self.assertTrue(result.success, result.to_dict())
        self.assertTrue(result.data["passed"])
        self.assertEqual((self.loads, self.measures), (1, 1))

    def test_flash_transport_timeout_keeps_uncertain_hardware_state_in_report(self):
        fixture = self.fixture
        original = fixture.fake_process
        def interrupted(argv, timeout):
            if "verify reset exit" in argv[-1]:
                raise TimeoutError()
            return original(argv, timeout)
        fixture.runner.run.side_effect = interrupted
        preview = fixture.loop.advance()
        fixture.approve_execution(preview)
        result = fixture.loop.advance()
        self.assertEqual(result.data["decision"], "FAIL")
        self.assertTrue(result.data["hardware_state_uncertain"])
        fixture.client.generate.assert_not_called()
