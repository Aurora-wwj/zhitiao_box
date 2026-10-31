import json
import hashlib
import os
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from zhidiao_agent.deployment import DeploymentConfig
from zhidiao_agent.errors import AgentError, ErrorCode
from zhidiao_agent.tools.artifacts import keil_target, validate_hex
from zhidiao_agent.tools.commands import CommandResult
from zhidiao_agent.tools.real_backend import RealBackend


def hex_text(data=b"\x01\x02\x03\x04"):
    record = bytes([len(data), 0, 0, 0]) + data
    return ":020000040800F2\n:" + record.hex().upper() + f"{(-sum(record)) & 255:02X}" + "\n:00000001FF\n"


class RealBackendTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="zhidiao-real-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project with spaces"
        self.project.mkdir()
        self.mdk = self.project / "MDK-ARM"
        self.mdk.mkdir()
        self.project_file = self.mdk / "GPIO1.uvprojx"
        self.project_file.write_text('''<Project><Targets><Target><TargetName>GPIO1</TargetName>
<TargetOption><TargetCommonOption><OutputDirectory>.\\GPIO1\\</OutputDirectory>
<OutputName>GPIO1</OutputName><CreateHexFile>1</CreateHexFile>
</TargetCommonOption></TargetOption></Target></Targets></Project>''')
        self.source = self.project / "main.c"
        self.source.write_text("int main(void) { return 0; }")
        self.hex = self.mdk / "GPIO1" / "GPIO1.hex"
        self.hex.parent.mkdir()
        self.executable = self.root / "UV4.exe"
        self.executable.write_text("mock executable, never launched")
        self.hosts = self.root / "known hosts"
        self.hosts.write_text("verified deployment host placeholder for offline tests")
        self.config = DeploymentConfig(
            allowed_roots=(str(self.project),), keil_executable=str(self.executable),
            project_file="MDK-ARM/GPIO1.uvprojx", target="GPIO1", known_hosts=str(self.hosts),
        )
        self.runner = Mock()
        self.backend = RealBackend(self.config, runner=self.runner)

    def approve(self, preview):
        self.assertTrue(preview.success, preview.to_dict())
        result = self.backend.approvals.decide(
            preview.data["proposal_id"], preview.data["fingerprint"], approved=True,
        )
        self.assertTrue(result.success)

    def build_side_effect(self, *, errors=0, exitcode=0, create=True):
        def run(argv, timeout):
            self.assertEqual(argv[0], str(self.executable))
            self.assertIn("-r", argv)
            self.assertIn("-t", argv)
            log = Path(argv[argv.index("-o") + 1])
            log.write_text(f'"GPIO1.axf" - {errors} Error(s), 18 Warning(s).\n')
            if create:
                self.hex.write_text(hex_text())
            return CommandResult(exitcode, "")
        return run

    def build(self):
        self.approve(self.backend.preview_build(str(self.project)))
        return self.backend.build_firmware(str(self.project))

    def flash(self):
        self.hex.write_text(hex_text())
        self.approve(self.backend.preview_flash(str(self.hex)))
        return self.backend.flash_firmware(str(self.hex))

    def successful_flash_commands(self, last_log=None, last_code=0):
        # Path.write_text uses native newlines; upload checks compare raw bytes.
        data = hex_text().replace("\n", os.linesep).encode("ascii")
        size = len(data)
        return [CommandResult(0, ""), CommandResult(0, ""), CommandResult(0, str(size) + "\n"),
                CommandResult(0, hashlib.sha256(data).hexdigest() + "  -\n"),
                CommandResult(last_code, last_log if last_log is not None else
                    "Unable to match requested speed 2000 kHz, using 1800 kHz\n"
                    "** Programming Finished **\n** Verified OK **\n** Resetting Target **")]

    def test_preview_does_not_execute_and_reflects_actual_keil_output(self):
        result = self.backend.preview_build(str(self.project))
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["params"]["artifact_path"], str(self.hex))
        self.runner.run.assert_not_called()
        self.assertEqual(list(self.project.glob("keil_build_*.log")), [])

    def test_build_without_preview_or_approval_never_runs(self):
        self.assertEqual(self.backend.build_firmware(str(self.project)).error_code, "APPROVAL_REQUIRED")
        self.backend.preview_build(str(self.project))
        self.assertEqual(self.backend.build_firmware(str(self.project)).error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_warnings_and_fresh_hex_are_successful_for_exit_zero_or_one(self):
        for code in (0, 1):
            with self.subTest(code=code):
                self.hex.unlink(missing_ok=True)
                self.runner.run.side_effect = self.build_side_effect(exitcode=code)
                result = self.build()
                self.assertTrue(result.success, result.to_dict())
                self.assertEqual(result.data["artifact_path"], str(self.hex))
                self.assertIn("18 Warning(s)", result.data["compiler_log"])

    def test_build_errors_and_fatal_exit_are_not_success(self):
        for errors, code in ((1, 0), (0, 2)):
            with self.subTest(errors=errors, code=code):
                self.runner.run.side_effect = self.build_side_effect(errors=errors, exitcode=code)
                result = self.build()
                self.assertEqual(result.error_code, "BUILD_FAILED")
                self.assertIn("compiler_log", result.data)

    def test_build_rejects_missing_and_stale_hex(self):
        self.runner.run.side_effect = self.build_side_effect(create=False)
        self.assertEqual(self.build().error_code, "ARTIFACT_NOT_FOUND")
        self.hex.write_text(hex_text())
        self.assertEqual(self.build().error_code, "ARTIFACT_NOT_FOUND")

    def test_build_missing_log_and_timeout(self):
        self.runner.run.return_value = CommandResult(0, "0 Error(s)")
        self.assertEqual(self.build().error_code, "BUILD_FAILED")
        self.runner.run.side_effect = AgentError(ErrorCode.TIMEOUT, "Timed out.")
        self.assertEqual(self.build().error_code, "TIMEOUT")

    def test_source_change_requires_new_approval(self):
        self.approve(self.backend.preview_build(str(self.project)))
        self.source.write_text("int main(void) { return 1; }")
        self.assertEqual(self.backend.build_firmware(str(self.project)).error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_approval_cannot_be_replayed(self):
        self.runner.run.side_effect = self.build_side_effect()
        self.assertTrue(self.build().success)
        self.assertEqual(self.backend.build_firmware(str(self.project)).error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_called_once()

    def test_flash_preview_has_strict_host_check_and_legacy_compatibility(self):
        self.hex.write_text(hex_text())
        result = self.backend.preview_flash(str(self.hex))
        self.assertTrue(result.success, result.to_dict())
        params = result.data["params"]
        self.assertRegex(params["remote_path"], r"^/sd/firmware/run_[0-9a-f]{32}/firmware.hex$")
        self.assertEqual(len(params["commands"]), 5)
        for command in params["commands"]:
            self.assertIn("BatchMode=yes", command)
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertIn("HostKeyAlgorithms=+ssh-rsa", command)
        self.assertIn("-O", params["commands"][1])
        self.assertIn("command -v sha256sum", params["commands"][0][-1])
        self.assertEqual(params["commands"][3][-1], "sha256sum < " + params["remote_path"])
        self.assertIn("verify reset exit", params["commands"][-1][-1])
        self.runner.run.assert_not_called()

    def test_flash_success_requires_program_verify_reset_and_exit(self):
        self.runner.run.side_effect = self.successful_flash_commands()
        result = self.flash()
        self.assertTrue(result.success, result.to_dict())
        self.assertTrue(result.data["verified"])
        self.assertTrue(result.data["upload_verified"])
        self.assertEqual(result.data["artifact_sha256"], result.data["remote_sha256"])
        self.assertEqual(self.runner.run.call_count, 5)
        budgets = [call.args[1] for call in self.runner.run.call_args_list]
        self.assertEqual(budgets, sorted(budgets, reverse=True))

    def test_each_upload_failure_stops_before_openocd(self):
        for index in (0, 1, 2, 3):
            with self.subTest(index=index):
                self.runner.reset_mock()
                results = self.successful_flash_commands()
                results[index] = CommandResult(1, "failed")
                self.runner.run.side_effect = results
                result = self.flash()
                self.assertEqual(result.error_code, "UPLOAD_FAILED")
                self.assertFalse(result.data["verified"])
                self.assertFalse(result.data["upload_verified"])
                self.assertEqual(self.runner.run.call_count, index + 1)

    def test_remote_size_mismatch_stops_before_programming(self):
        results = self.successful_flash_commands()
        results[2] = CommandResult(0, "1\n")
        self.runner.run.side_effect = results
        self.assertEqual(self.flash().error_code, "UPLOAD_FAILED")
        self.assertEqual(self.runner.run.call_count, 3)

    def test_same_size_wrong_sha256_stops_before_openocd(self):
        results = self.successful_flash_commands()
        expected = results[3].output.split()[0]
        different = ("0" if expected[0] != "0" else "1") + expected[1:]
        results[3] = CommandResult(0, different + "  -\n")
        self.runner.run.side_effect = results
        result = self.flash()
        self.assertEqual(result.error_code, "UPLOAD_FAILED")
        self.assertFalse(result.data["verified"])
        self.assertFalse(result.data["upload_verified"])
        self.assertEqual(result.data["remote_sha256"], different)
        self.assertEqual(result.data["artifact_sha256"], expected)
        self.assertEqual(self.runner.run.call_count, 4)
        self.assertIn("sha256sum < ", self.runner.run.call_args.args[0][-1])

    def test_malformed_or_ambiguous_remote_sha256_stops_before_openocd(self):
        digest = self.successful_flash_commands()[3].output.split()[0]
        for output in ("", digest, "a" * 32 + "  -\n", "g" * 64 + "  -\n",
                       digest + "  /wrong/file.hex\n", digest + "  -\nextra output",
                       digest + "  -\n" + digest + "  -\n"):
            with self.subTest(output=output):
                self.runner.reset_mock()
                results = self.successful_flash_commands()
                results[3] = CommandResult(0, output)
                self.runner.run.side_effect = results
                result = self.flash()
                self.assertEqual(result.error_code, "UPLOAD_FAILED")
                self.assertFalse(result.data["verified"])
                self.assertFalse(result.data["upload_verified"])
                self.assertNotIn("remote_sha256", result.data)
                self.assertEqual(self.runner.run.call_count, 4)

    def test_remote_sha256_accepts_text_binary_and_uppercase_output(self):
        digest = self.successful_flash_commands()[3].output.split()[0]
        for output in (digest + "  -\n", digest + " *-\n", digest.upper() + "\t-\r\n"):
            with self.subTest(output=output):
                self.runner.reset_mock()
                results = self.successful_flash_commands()
                results[3] = CommandResult(0, output)
                self.runner.run.side_effect = results
                result = self.flash()
                self.assertTrue(result.success, result.to_dict())
                self.assertTrue(result.data["verified"])
                self.assertTrue(result.data["upload_verified"])
                self.assertEqual(result.data["remote_sha256"], hashlib.sha256(self.hex.read_bytes()).hexdigest())
                self.assertEqual(self.runner.run.call_count, 5)

    def test_hash_command_failure_is_not_overridden_by_valid_output(self):
        for code, expected in ((1, "UPLOAD_FAILED"), (127, "UPLOAD_FAILED"), (255, "SSH_CONNECT_FAILED")):
            with self.subTest(code=code):
                self.runner.reset_mock()
                results = self.successful_flash_commands()
                results[3] = CommandResult(code, results[3].output)
                self.runner.run.side_effect = results
                result = self.flash()
                self.assertEqual(result.error_code, expected)
                self.assertFalse(result.data["verified"])
                self.assertFalse(result.data["upload_verified"])
                self.assertEqual(self.runner.run.call_count, 4)

    def test_hash_command_timeout_prevents_openocd(self):
        self.runner.run.side_effect = self.successful_flash_commands()[:3] + [TimeoutError()]
        result = self.flash()
        self.assertEqual(result.error_code, "TIMEOUT")
        self.assertFalse(result.data["verified"])
        self.assertFalse(result.data["upload_verified"])
        self.assertEqual(self.runner.run.call_count, 4)

    def test_total_flash_budget_also_bounds_remote_hash_step(self):
        elapsed = [0]
        responses = iter(self.successful_flash_commands())
        def command(argv, timeout):
            elapsed[0] += 41
            return next(responses)
        self.runner.run.side_effect = command
        with patch("zhidiao_agent.tools.real_backend.time.monotonic", side_effect=lambda: elapsed[0]):
            result = self.flash()
        self.assertEqual(result.error_code, "TIMEOUT")
        self.assertFalse(result.data["upload_verified"])
        self.assertEqual(self.runner.run.call_count, 3)

    def test_changed_deployment_or_build_script_invalidates_approval(self):
        self.approve(self.backend.preview_build(str(self.project)))
        self.backend.config = replace(self.config, target="different")
        self.assertEqual(self.backend.build_firmware(str(self.project)).error_code, "APPROVAL_REQUIRED")
        self.backend.config = self.config
        script = self.project / "prepare.cmd"
        script.write_text("echo original")
        self.approve(self.backend.preview_build(str(self.project)))
        script.write_text("echo changed")
        self.assertEqual(self.backend.build_firmware(str(self.project)).error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_real_observer_auto_wiring_is_preview_only_until_requested(self):
        from zhidiao_agent.deployment import PLObserverConfig
        backend = RealBackend(replace(self.config, observer=PLObserverConfig()), runner=self.runner)
        preview = backend.preview_observation()
        self.assertTrue(preview.success, preview.to_dict())
        self.assertFalse(preview.data["uart_available"])
        self.assertTrue(preview.data["period_available"])
        self.runner.run.assert_not_called()
        self.assertEqual(backend.preview_observation("read_target_log", 1).error_code, "BACKEND_UNAVAILABLE")
        self.runner.run.return_value = CommandResult(0, "ZHIDIAO_PL_V1 1 3 3 1 60096000 30048000")
        result = backend.run_hardware_test("gpio_period", {"expected_period_ms": 1000, "tolerance_ms": 50})
        self.assertTrue(result.success, result.to_dict())
        self.assertFalse(result.data["passed"])
        self.assertTrue(result.data["observation"]["freshness_verified"])
        self.runner.run.assert_called_once()

    def test_reviewed_deadline_caps_build_and_observation(self):
        from zhidiao_agent.observations import ObservationBackend
        reader = Mock(return_value={"period_ms": 1001})
        observations = ObservationBackend(period_reader=reader)
        backend = RealBackend(self.config, runner=self.runner, observations=observations)
        backend.execution_deadline = 5
        with patch("zhidiao_agent.tools.real_backend.time.monotonic", return_value=0):
            result = backend.run_hardware_test("gpio_period", {"expected_period_ms": 1000, "tolerance_ms": 50})
        self.assertTrue(result.success)
        reader.assert_called_once_with(5)
        self.assertEqual(observations.timeout_s, 15)
        backend.execution_deadline = 0
        with patch("zhidiao_agent.tools.real_backend.time.monotonic", return_value=1):
            result = backend.run_hardware_test("gpio_period", {"expected_period_ms": 1000, "tolerance_ms": 50})
        self.assertEqual(result.error_code, "TIMEOUT")
        self.assertEqual(reader.call_count, 1)
        backend.execution_deadline = 5
        self.runner.run.side_effect = self.build_side_effect()
        preview = backend.preview_build(str(self.project))
        backend.approvals.decide(preview.data["proposal_id"], preview.data["fingerprint"], approved=True)
        with patch("zhidiao_agent.tools.real_backend.time.monotonic", return_value=0):
            result = backend.build_firmware(str(self.project))
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(self.runner.run.call_args.args[1], 5)

    def test_ssh_failure_and_timeout(self):
        self.runner.run.return_value = CommandResult(255, "authentication failed")
        self.assertEqual(self.flash().error_code, "SSH_CONNECT_FAILED")
        self.runner.run.side_effect = TimeoutError()
        self.assertEqual(self.flash().error_code, "TIMEOUT")

    def test_openocd_failure_categories(self):
        for text, code, expected in [
            ("Programming Finished\nVerified OK\nResetting Target", 1, "FLASH_PROGRAM_FAILED"),
            ("Programming Finished", 0, "FLASH_VERIFY_FAILED"),
            ("Programming Finished\nVerified OK", 0, "TARGET_RESET_FAILED"),
        ]:
            with self.subTest(expected=expected):
                self.runner.run.side_effect = self.successful_flash_commands(text, code)
                result = self.flash()
                self.assertEqual(result.error_code, expected)
                self.assertFalse(result.data["verified"])
                self.assertTrue(result.data["upload_verified"])

    def test_firmware_change_after_approval_stops_all_commands(self):
        self.hex.write_text(hex_text())
        self.approve(self.backend.preview_flash(str(self.hex)))
        self.hex.write_text(hex_text(b"\x02\x03\x04\x05"))
        self.assertEqual(self.backend.flash_firmware(str(self.hex)).error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_bad_hex_or_missing_host_trust_is_rejected_before_execution(self):
        self.hex.write_text(":00000001FF\n")
        self.assertEqual(self.backend.preview_flash(str(self.hex)).error_code, "INVALID_ARGUMENT")
        self.hex.write_text(hex_text())
        self.hosts.unlink()
        self.assertEqual(self.backend.preview_flash(str(self.hex)).error_code, "CONFIGURATION_ERROR")
        self.runner.run.assert_not_called()

    def test_configured_pl_interfaces_remain_unavailable(self):
        self.assertEqual(self.backend.read_target_log(5).error_code, "BACKEND_UNAVAILABLE")
        self.assertEqual(self.backend.run_hardware_test("gpio_period", {}).error_code, "BACKEND_UNAVAILABLE")

    def test_project_discovery_and_ambiguous_or_outside_artifacts(self):
        config = replace(self.config, project_file=None, target=None)
        self.assertEqual(keil_target(self.project, config)[2], self.hex)
        (self.project / "another.uvprojx").write_text(self.project_file.read_text())
        with self.assertRaises(AgentError):
            keil_target(self.project, config)
        self.project_file.write_text(self.project_file.read_text().replace(".\\GPIO1\\", "../../outside"))
        with self.assertRaises(AgentError):
            keil_target(self.project, self.config)

    def test_disabled_hex_generation_and_invalid_xml(self):
        self.project_file.write_text(self.project_file.read_text().replace("<CreateHexFile>1", "<CreateHexFile>0"))
        self.assertEqual(self.backend.preview_build(str(self.project)).error_code, "CONFIGURATION_ERROR")
        self.project_file.write_text("not xml")
        self.assertEqual(self.backend.preview_build(str(self.project)).error_code, "CONFIGURATION_ERROR")

    def test_deployment_loader_and_invalid_settings(self):
        filename = self.root / "deployment.json"
        filename.write_text(json.dumps({"allowed_roots": [str(self.project)]}))
        self.assertEqual(DeploymentConfig.load(str(filename)).allowed_roots, (str(self.project),))
        for changes in ({"host": "host;touch bad"}, {"port": True}, {"mount_root": "/sd;bad"},
                        {"build_timeout_s": float("nan")}, {"flash_timeout_s": 0}):
            with self.subTest(changes=changes), self.assertRaises(AgentError):
                replace(self.config, **changes)

    def test_hex_checksums_eof_and_trailing_data_are_enforced(self):
        for content in (hex_text().replace("0304F2", "0304F1"), hex_text().replace(":00000001FF", ""),
                        hex_text() + ":00000001FF\n", "not hex"):
            with self.subTest(content=content):
                self.hex.write_text(content)
                with self.assertRaises(AgentError):
                    validate_hex(self.hex)

    def test_preview_payload_mutation_cannot_change_executable_plan(self):
        preview = self.backend.preview_build(str(self.project))
        preview.data["params"]["commands"][0][0] = "unapproved executable"
        self.approve(preview)
        self.runner.run.side_effect = self.build_side_effect()
        self.assertTrue(self.backend.build_firmware(str(self.project)).success)
        self.assertEqual(self.runner.run.call_args.args[0][0], str(self.executable))

    def test_firmware_mutation_during_upload_prevents_openocd(self):
        self.hex.write_text(hex_text())
        self.approve(self.backend.preview_flash(str(self.hex)))
        def run(argv, timeout):
            self.hex.write_text(hex_text(b"\x02\x03\x04\x05"))
            return CommandResult(0, "")
        self.runner.run.side_effect = run
        result = self.backend.flash_firmware(str(self.hex))
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.assertFalse(result.data["verified"])
        self.runner.run.assert_called_once()

    def test_flash_total_budget_stops_before_first_command(self):
        self.hex.write_text(hex_text())
        self.approve(self.backend.preview_flash(str(self.hex)))
        with patch("zhidiao_agent.tools.real_backend.time.monotonic", side_effect=[0, 121]):
            result = self.backend.flash_firmware(str(self.hex))
        self.assertEqual(result.error_code, "TIMEOUT")
        self.runner.run.assert_not_called()

    def test_occupied_log_path_is_not_used_as_fresh_build_output(self):
        preview = self.backend.preview_build(str(self.project))
        self.approve(preview)
        Path(preview.data["params"]["log_path"]).write_text("stale")
        self.assertEqual(self.backend.build_firmware(str(self.project)).error_code, "CONFIGURATION_ERROR")
        self.runner.run.assert_not_called()

    def test_controller_keeps_configured_real_backend_blocked(self):
        from zhidiao_agent.controller import Controller
        result = Controller(self.backend, allowed_roots=(str(self.project),)).run(str(self.project))
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_observation_provider_can_be_injected_without_command_execution(self):
        from zhidiao_agent.observations import ObservationBackend
        observations = ObservationBackend(
            uart_reader=Mock(return_value=[{"timestamp_ms": 0, "text": "FW_BOOT_OK"}]),
            period_reader=Mock(return_value={"period_ms": 1001}),
        )
        backend = RealBackend(self.config, runner=self.runner, observations=observations)
        self.assertTrue(backend.read_target_log(5).success)
        result = backend.run_hardware_test("gpio_period", {"expected_period_ms": 1000, "tolerance_ms": 50})
        self.assertTrue(result.success)
        self.assertTrue(result.data["passed"])
        self.runner.run.assert_not_called()
