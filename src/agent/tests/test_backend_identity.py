"""A deployment must not flash one Zynq and accept another board's evidence."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from zhidiao_agent.controller import ReviewedController
from zhidiao_agent.deployment import DeploymentConfig, PLObserverConfig
from zhidiao_agent.observations import ObservationBackend
from zhidiao_agent.tools.commands import CommandResult
from zhidiao_agent.tools.pl_observer import PLPeriodReader
from zhidiao_agent.tools.real_backend import RealBackend


class BackendIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="zhidiao-deployment-identity-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "main.c").write_text("int main(void) { return 0; }\n")
        (self.project / "GPIO.uvprojx").write_text('''<Project><Targets><Target>
<TargetName>GPIO</TargetName><TargetOption><TargetCommonOption>
<OutputDirectory>.\\output\\</OutputDirectory><OutputName>firmware</OutputName>
<CreateHexFile>1</CreateHexFile></TargetCommonOption></TargetOption></Target></Targets></Project>''')
        self.executable = self.root / "UV4.exe"
        self.executable.write_text("mock executable, never launched")
        self.hosts = self.root / "known_hosts"
        self.hosts.write_text("trusted host fixture")
        self.identity = self.root / "identity"
        self.identity.write_text("test placeholder, not a key")
        self.config = DeploymentConfig(
            allowed_roots=(str(self.project),), keil_executable=str(self.executable),
            project_file="GPIO.uvprojx", target="GPIO", known_hosts=str(self.hosts),
            identity_file=str(self.identity), observer=PLObserverConfig(),
        )
        self.runner = Mock()
        self.runner.run.return_value = CommandResult(0, "ZHIDIAO_PL_V1 0 2 2 1 100100000 50050000")
        self.backend = RealBackend(self.config, runner=self.runner)
        self.params = {"expected_period_ms": 1000, "tolerance_ms": 50}

    def test_changed_deployment_cannot_create_a_mixed_board_preview(self):
        alternate = self.root / "alternate_identity"
        alternate.write_text("other fixture")
        for change in (
            {"host": "192.168.10.3"}, {"port": 2222}, {"user": "other"},
            {"identity_file": str(alternate)}, {"known_hosts": str(alternate)},
            {"observer": replace(self.config.observer, pl_clock_hz=50_000_000)},
            {"allow_legacy_rsa": False},
        ):
            with self.subTest(change=change):
                self.backend.config = replace(self.config, **change)
                result = self.backend.preview_observation()
                self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
                self.assertEqual(self.backend.run_hardware_test("gpio_period", self.params).error_code,
                                 "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_changed_backend_blocks_real_cycle_before_build_or_measurement(self):
        self.backend.config = replace(self.config, host="192.168.10.3")
        controller = ReviewedController(self.backend, allowed_roots=self.config.allowed_roots)
        preview = controller.preview_cycle(str(self.project), params=self.params, include_uart=False)
        self.assertEqual(preview.error_code, "APPROVAL_REQUIRED")
        self.assertEqual(controller.run_once(str(self.project), params=self.params,
                                             include_uart=False).error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_native_reader_config_mutation_is_rejected_before_io(self):
        reader = self.backend.observations.period_reader
        reader.config = replace(self.config, host="192.168.10.3")
        self.assertEqual(self.backend.preview_observation().error_code, "APPROVAL_REQUIRED")
        self.assertEqual(self.backend.read_target_log(1).error_code, "APPROVAL_REQUIRED")
        self.assertEqual(self.backend.run_hardware_test("gpio_period", self.params).error_code,
                         "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_native_reader_transport_mutation_is_rejected_before_io(self):
        replacement = Mock()
        self.backend.observations.period_reader.runner = replacement
        self.assertEqual(self.backend.run_hardware_test("gpio_period", self.params).error_code,
                         "APPROVAL_REQUIRED")
        replacement.run.assert_not_called()
        self.runner.run.assert_not_called()

    def test_mismatched_injected_native_reader_is_rejected(self):
        observations = ObservationBackend(period_reader=PLPeriodReader(
            replace(self.config, host="192.168.10.3"), runner=self.runner))
        backend = RealBackend(self.config, runner=self.runner, observations=observations)
        self.assertEqual(backend.preview_observation().error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_new_instance_can_select_new_board_and_measure_it(self):
        new_config = replace(self.config, host="192.168.10.3")
        backend = RealBackend(new_config, runner=self.runner)
        preview = backend.preview_observation()
        self.assertTrue(preview.success, preview.to_dict())
        self.assertEqual(preview.data["descriptor"]["deployment"]["host"], "192.168.10.3")
        self.assertEqual(preview.data["descriptor"]["period"]["commands"][0][-2], "root@192.168.10.3")
        measurement = backend.run_hardware_test("gpio_period", self.params)
        self.assertTrue(measurement.success, measurement.to_dict())
        self.assertTrue(measurement.data["passed"])
        self.assertEqual(self.runner.run.call_args.args[0][-2], "root@192.168.10.3")

    def test_equal_config_copy_and_trusted_callbacks_stay_supported(self):
        self.backend.config = replace(self.config)
        self.assertTrue(self.backend.preview_observation().success)
        callback = Mock(return_value={"period_ms": 1001})
        backend = RealBackend(self.config, runner=self.runner,
                              observations=ObservationBackend(period_reader=callback))
        result = backend.run_hardware_test("gpio_period", self.params)
        self.assertTrue(result.success)
        callback.assert_called_once()
        self.runner.run.assert_not_called()
