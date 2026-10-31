import json
import os
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from zhidiao_agent.deployment import DeploymentConfig, PLObserverConfig, UARTObserverConfig
from zhidiao_agent.pairing import DeploymentDiagnostics, DeploymentSetup, diagnostic_plan
from zhidiao_agent.tools.commands import CommandResult


def diagnostic_output(**statuses):
    names = ("ssh_connection", "remote_home", "authorized_keys", "openocd", "openocd_scripts",
             "stlink_usb", "busybox", "prog_done", "observer_registers", "busybox_usleep", "monotonic_clock")
    return "ZHIDIAO_DEPLOY_V1\n" + "\n".join(
        name + "\t" + statuses.get(name, "PASS") + ("\t/home/root" if name == "remote_home" else "")
        for name in names
    ) + "\n"


class PairingTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="zhidiao-pairing-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.project = self.root / "GPIO_PL_Test"
        self.project.mkdir()
        (self.project / "project.uvprojx").write_text('''<Project><Targets><Target>
<TargetName>GPIO</TargetName><TargetOption><TargetCommonOption>
<OutputDirectory>.\\Objects\\</OutputDirectory><OutputName>GPIO</OutputName>
<CreateHexFile>1</CreateHexFile></TargetCommonOption></TargetOption></Target></Targets></Project>''')
        self.exe = self.root / "UV4.exe"
        self.exe.write_text("fake executable never launched")
        self.hosts = self.root / "known_hosts"
        self.hosts.write_text("mock public host fixture")
        self.identity = self.root / "id_project"
        self.identity.write_text("PRIVATE FIXTURE MUST NOT BE READ")
        self.config = DeploymentConfig(allowed_roots=(str(self.project),), keil_executable=str(self.exe),
            project_file="project.uvprojx", target="GPIO", known_hosts=str(self.hosts),
            identity_file=str(self.identity), observer=PLObserverConfig())
        self.runner = Mock()
        self.runner.run.return_value = CommandResult(0, diagnostic_output())
        self.setup = DeploymentSetup(self.config, runner=self.runner)
        self.output = self.root / "deployment.local.json"
        self.enterContext(patch("zhidiao_agent.pairing.shutil.which", side_effect=lambda name: "/mock/" + name))

    def approve(self, instance, result, approved=True):
        self.assertTrue(result.success, result.to_dict())
        review = instance.approvals.decide(result.data["proposal_id"], result.data["fingerprint"], approved=approved)
        return result.data["proposal_id"], review

    def test_preview_has_complete_profile_and_checks_but_no_effect(self):
        preview = self.setup.preview(str(self.output), check_remote=True)
        self.assertTrue(preview.success, preview.to_dict())
        params = preview.data["params"]
        self.assertEqual(params["profile"]["observer"]["observed_gpio"], "PA1")
        self.assertIn("sha256", params["local"]["input_metadata"]["project_file"])
        self.assertTrue(params["local"]["local_ready"])
        self.assertFalse(self.output.exists())
        self.runner.run.assert_not_called()
        serialized = json.dumps(preview.to_dict())
        self.assertNotIn("PRIVATE FIXTURE", serialized)
        self.assertIn("StrictHostKeyChecking=yes", serialized)
        self.assertIn("BatchMode=yes", serialized)

    def test_v4_diagnostics_check_uart_status_and_timing_without_fifo_writes(self):
        config = replace(self.config, uart_observer=UARTObserverConfig())
        plan = diagnostic_plan(config)
        script = plan['commands'][0][-1]
        self.assertIn('uart_registers', plan['check_names'])
        self.assertIn('busybox_usleep', plan['check_names'])
        self.assertIn('usleep 0', script)
        self.assertIn('/proc/uptime', script)
        self.assertIn('devmem 0x43C50008 32', script)
        self.assertNotIn('devmem 0x43C50000', script)
        self.assertNotIn('devmem 0x43C5000C', script)
        self.runner.run.return_value = CommandResult(0, diagnostic_output()+'uart_registers\tPASS\n')
        diagnostics = DeploymentDiagnostics(config, runner=self.runner)
        preview = diagnostics.preview()
        proposal, _ = self.approve(diagnostics, preview)
        result = diagnostics.run(proposal)
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data['decision'], 'READY')

    def test_without_approval_and_rejection_never_write_or_connect(self):
        preview = self.setup.preview(str(self.output), check_remote=True)
        self.assertEqual(self.setup.apply(preview.data["proposal_id"]).error_code, "APPROVAL_REQUIRED")
        preview = self.setup.preview(str(self.output), check_remote=True)
        proposal, rejected = self.approve(self.setup, preview, False)
        self.assertEqual(rejected.error_code, "APPROVAL_REJECTED")
        self.assertEqual(self.setup.apply(proposal).error_code, "APPROVAL_REQUIRED")
        self.assertFalse(self.output.exists())
        self.runner.run.assert_not_called()

    def test_approved_profile_roundtrips_and_is_single_use(self):
        preview = self.setup.preview(str(self.output))
        proposal, accepted = self.approve(self.setup, preview)
        self.assertTrue(accepted.success)
        result = self.setup.apply(proposal)
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(DeploymentConfig.load(str(self.output)), self.config)
        self.assertEqual(result.data["decision"], "CONFIGURED_NOT_VERIFIED")
        self.assertEqual(self.setup.apply(proposal).error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()
        if os.name == "posix":
            self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.root.glob(".zhidiao-setup-*")), [])

    def test_existing_profile_is_never_overwritten_even_after_preview(self):
        proposal, _ = self.approve(self.setup, self.setup.preview(str(self.output)))
        self.output.write_text("user existing configuration")
        self.assertEqual(self.setup.apply(proposal).error_code, "APPROVAL_REQUIRED")
        self.assertEqual(self.output.read_text(), "user existing configuration")
        self.assertEqual(self.setup.preview(str(self.output)).error_code, "APPROVAL_REQUIRED")

    def test_changed_inputs_or_config_invalidate_preview(self):
        proposal, _ = self.approve(self.setup, self.setup.preview(str(self.output)))
        self.identity.write_text("changed private fixture")
        self.assertEqual(self.setup.apply(proposal).error_code, "APPROVAL_REQUIRED")
        proposal, _ = self.approve(self.setup, self.setup.preview(str(self.output)))
        self.setup.config = replace(self.config, host="192.168.10.3")
        self.assertEqual(self.setup.apply(proposal).error_code, "APPROVAL_REQUIRED")
        self.assertFalse(self.output.exists())

    def test_missing_local_tool_is_reported_and_cannot_create_profile(self):
        self.exe.unlink()
        preview = self.setup.preview(str(self.output))
        self.assertTrue(preview.success)
        self.assertFalse(preview.data["params"]["local"]["local_ready"])
        proposal, _ = self.approve(self.setup, preview)
        self.assertEqual(self.setup.apply(proposal).error_code, "CONFIGURATION_ERROR")
        self.assertFalse(self.output.exists())

    def test_remote_checks_keep_tool_success_and_readiness_separate(self):
        self.runner.run.return_value = CommandResult(0, diagnostic_output(stlink_usb="UNKNOWN", observer_registers="UNKNOWN"))
        proposal, _ = self.approve(self.setup, self.setup.preview(str(self.output), check_remote=True))
        result = self.setup.apply(proposal)
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["decision"], "INCOMPLETE")
        self.assertEqual(len(result.data["remote"]["checks"]), 11)
        self.runner.run.assert_called_once()
        self.assertTrue(self.output.exists())

    def test_diagnostics_require_exact_single_use_approval(self):
        checks = DeploymentDiagnostics(self.config, runner=self.runner)
        self.assertEqual(checks.run("missing").error_code, "APPROVAL_REQUIRED")
        preview = checks.preview()
        proposal, _ = self.approve(checks, preview)
        result = checks.run(proposal)
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["decision"], "READY")
        self.assertEqual(checks.run(proposal).error_code, "APPROVAL_REQUIRED")
        script = self.runner.run.call_args.args[0][-1]
        self.assertIn('DHOME="${HOME:-}"', script)
        self.assertNotIn("/root", script)
        self.assertNotIn("program ", script)
        self.assertNotIn("/dev/xdevcfg", script)
        self.assertIn("ready", script)

    def test_diagnostic_transport_and_bad_output_are_structured(self):
        checks = DeploymentDiagnostics(self.config, runner=self.runner)
        for outcome, expected in ((CommandResult(255, "private stderr"), "SSH_CONNECT_FAILED"),
                                  (CommandResult(1, "private stderr"), "BACKEND_UNAVAILABLE"),
                                  (CommandResult(0, "banner\n"), "INVALID_RESPONSE"),
                                  (CommandResult(0, diagnostic_output() + "openocd\tPASS\n"), "INVALID_RESPONSE")):
            self.runner.run.return_value = outcome
            proposal, _ = self.approve(checks, checks.preview())
            actual = checks.run(proposal)
            self.assertEqual(actual.error_code, expected)
            self.assertNotIn("private stderr", actual.message)
        self.runner.run.side_effect = TimeoutError()
        proposal, _ = self.approve(checks, checks.preview())
        self.assertEqual(checks.run(proposal).error_code, "TIMEOUT")

    def test_diagnostic_configuration_change_requires_review(self):
        checks = DeploymentDiagnostics(self.config, runner=self.runner)
        proposal, _ = self.approve(checks, checks.preview())
        checks.config = replace(self.config, host="192.168.10.3")
        self.assertEqual(checks.run(proposal).error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_failed_atomic_publication_leaves_no_temporary_or_profile(self):
        proposal, _ = self.approve(self.setup, self.setup.preview(str(self.output)))
        with patch("zhidiao_agent.pairing.os.link", side_effect=OSError()):
            self.assertFalse(self.setup.apply(proposal).success)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".zhidiao-setup-*")), [])
