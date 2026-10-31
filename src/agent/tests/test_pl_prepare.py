import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from zhidiao_agent.deployment import DeploymentConfig, PLObserverConfig
from zhidiao_agent.errors import AgentError, ErrorCode
from zhidiao_agent.tools.commands import CommandResult
from zhidiao_agent.tools.pl_prepare import PLPreparation


class PreparationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="zhidiao-prepare-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        hosts = self.root / "known_hosts"
        hosts.write_text("offline host fixture")
        self.config = DeploymentConfig(allowed_roots=(str(self.root),), known_hosts=str(hosts),
                                       observer=PLObserverConfig())
        self.runner = Mock()

    def provider(self, **observer_values):
        return PLPreparation(replace(self.config, observer=replace(self.config.observer, **observer_values)),
                             runner=self.runner)

    def test_check_only_preview_is_pure_and_has_no_loader_write(self):
        provider = self.provider()
        preview = provider.preview(15)
        self.assertFalse(preview["requires_loading"])
        self.assertFalse(provider.requires_loading)
        self.assertEqual(len(preview["commands"]), 1)
        script = preview["commands"][0][-1]
        self.assertNotIn("DEVICE=", script)
        self.assertNotIn("BOOT.BIN", script)
        self.assertNotIn("image.ub", script)
        self.assertIn("BatchMode=yes", preview["commands"][0])
        self.assertIn("StrictHostKeyChecking=yes", preview["commands"][0])
        self.runner.run.assert_not_called()

    def test_check_only_reports_no_running_image_attestation(self):
        self.runner.run.return_value = CommandResult(0, "ZHIDIAO_PREP_V1 CHECKED - 1\n")
        outcome = self.provider()(15)
        self.assertTrue(outcome["prepared"])
        self.assertFalse(outcome["loaded"])
        self.assertEqual(outcome["running_image_identity"], "not_verified")
        self.assertIsNone(outcome["image_sha256"])

    def test_loading_preview_discloses_exact_image_and_destructive_effect(self):
        digest = "a" * 64
        provider = self.provider(prepare_policy="load_verified", bitstream="/sd/pl/measurement.bit",
                                 bitstream_sha256=digest)
        preview = provider.preview(12)
        self.assertTrue(preview["requires_loading"])
        self.assertIn("resets", preview["effects"])
        script = preview["commands"][0][-1]
        self.assertIn("/dev/xdevcfg", script)
        self.assertIn(digest, script)
        self.assertIn("/sd/pl/measurement.bit", script)
        self.assertIn("timeout -s KILL", script)
        # Hash is verified again immediately before opening the loader; an
        # already-set prog_done is never used to skip the explicitly chosen load.
        self.assertGreaterEqual(script.count('sha256sum < "$IMAGE"'), 2)
        self.assertLess(script.rindex('sha256sum < "$IMAGE"'), script.index("timeout -s KILL"))
        self.assertLess(script.index("timeout -s KILL"), script.index('done_value=$("$BB" cat "$DONE")'))
        self.runner.run.assert_not_called()

    def test_loading_accepts_only_matching_preparation_evidence(self):
        digest = "b" * 64
        provider = self.provider(prepare_policy="load_verified", bitstream="/sd/pl/measurement.bit",
                                 bitstream_sha256=digest)
        self.runner.run.return_value = CommandResult(0, "ZHIDIAO_PREP_V1 LOADED " + digest + " 1\n")
        outcome = provider(9)
        self.assertTrue(outcome["loaded"])
        self.assertEqual(outcome["image_sha256"], digest)
        self.assertEqual(outcome["running_image_identity"], "approved_file_loaded")
        self.runner.run.assert_called_once()
        self.assertEqual(self.runner.run.call_args.args[1], 9)
        for evidence in ("ZHIDIAO_PREP_V1 CHECKED " + digest + " 1",
                         "ZHIDIAO_PREP_V1 LOADED " + "c" * 64 + " 1",
                         "ZHIDIAO_PREP_V1 LOADED " + digest + " 0",
                         "ZHIDIAO_PREP_V1 LOADED " + digest + " 1\nextra", ""):
            self.runner.run.return_value = CommandResult(0, evidence)
            with self.subTest(evidence=evidence), self.assertRaises(AgentError) as failure:
                provider(9)
            self.assertEqual(failure.exception.code, ErrorCode.INVALID_RESPONSE)

    def test_loader_paths_stay_inside_sd_and_never_accept_boot_images(self):
        for path in ("/tmp/measurement.bit", "/sd/../boot/measurement.bit", "/sd/BOOT.BIN", "/sd/image.ub"):
            with self.subTest(path=path), self.assertRaises(AgentError) as failure:
                self.provider(bitstream=path, bitstream_sha256="a" * 64).preview(15)
            self.assertEqual(failure.exception.code, ErrorCode.CONFIGURATION_ERROR)
        self.runner.run.assert_not_called()

    def test_timeout_transport_hash_and_tool_failures_are_sanitized(self):
        for status, expected in ((255, ErrorCode.SSH_CONNECT_FAILED), (75, ErrorCode.TIMEOUT),
                                 (72, ErrorCode.PL_TEST_UNAVAILABLE), (73, ErrorCode.PL_TEST_UNAVAILABLE),
                                 (76, ErrorCode.PL_TEST_UNAVAILABLE), (77, ErrorCode.PL_TEST_UNAVAILABLE),
                                 (127, ErrorCode.PL_TEST_UNAVAILABLE), (74, ErrorCode.INVALID_RESPONSE)):
            self.runner.run.return_value = CommandResult(status, "private board failure")
            with self.subTest(status=status), self.assertRaises(AgentError) as failure:
                self.provider()(15)
            self.assertEqual(failure.exception.code, expected)
            self.assertNotIn("private", str(failure.exception))

    def test_invalid_budgets_or_missing_configuration_never_call_transport(self):
        for timeout in (True, 0, -1, float("nan"), float("inf"), 121):
            with self.subTest(timeout=timeout), self.assertRaises(AgentError):
                self.provider()(timeout)
        with self.assertRaises(AgentError):
            PLPreparation(replace(self.config, observer=None), runner=self.runner).preview(1)
        self.runner.run.assert_not_called()


@unittest.skipUnless(os.name == "posix" and shutil.which("sh"), "POSIX preparation helper regression")
class PreparationHelperTests(unittest.TestCase):
    """Run the generated check helper against temporary image/readiness fixtures."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="zhidiao-prepare-helper-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.hosts = self.root / "known_hosts"
        self.hosts.write_text("offline host fixture")
        self.done = self.root / "prog_done"
        self.done.write_text("1\n")
        self.image = self.root / "measurement.bit"
        self.image.write_bytes(b"known measurement image")
        self.sha = hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.busybox = self.root / "busybox"
        self.busybox.write_text("#!" + sys.executable + "\n" + '''import hashlib,pathlib,subprocess,sys,time
if sys.argv[1] == 'sha256sum':
    print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()+'  -')
elif sys.argv[1] == 'cat':
    if pathlib.Path(__file__).with_name('fail_load').exists() and sys.argv[2].endswith('.bit'):
        sys.exit(1)
    sys.stdout.buffer.write(pathlib.Path(sys.argv[2]).read_bytes())
elif sys.argv[1] == 'date':
    print(int(time.time()))
elif sys.argv[1] == 'usleep' and sys.argv[2].isdigit():
    pass
elif sys.argv[1] == 'sh':
    sys.exit(subprocess.run(['sh', *sys.argv[2:]]).returncode)
elif sys.argv[1] == 'timeout':
    if sys.argv[2:] == ['--help']:
        sys.exit(0)
    if pathlib.Path(__file__).with_name('timeout_load').exists():
        sys.exit(124)
    try:
        sys.exit(subprocess.run(sys.argv[5:],timeout=int(sys.argv[4])).returncode)
    except subprocess.TimeoutExpired:
        sys.exit(124)
else:
    sys.exit(127)
''', encoding="utf-8")
        self.busybox.chmod(0o700)
        self.config = DeploymentConfig(allowed_roots=(str(self.root),), known_hosts=str(self.hosts),
            mount_root=str(self.root), observer=PLObserverConfig(bitstream=str(self.image),
                bitstream_sha256=self.sha, busybox_path=str(self.busybox), prog_done_path=str(self.done)))
        def command(argv, timeout):
            outcome = subprocess.run(["sh", "-c", argv[-1]], capture_output=True, text=True, timeout=timeout)
            return CommandResult(outcome.returncode, outcome.stdout + outcome.stderr)
        self.runner = Mock(run=Mock(side_effect=command))

    def load_fixture(self):
        """Execute the real generated algorithm against a regular temp device.

        Only the harness substitutes the kernel device and character-device
        preflight. Production code always insists on /dev/xdevcfg; tests cannot
        reach it. SHA, loader timeout, load and readiness logic are unchanged.
        """
        self.device = self.root / "simulated_xdevcfg"
        self.device.write_bytes(b"old fixture configuration")
        config = replace(self.config, observer=replace(self.config.observer, prepare_policy="load_verified",
                                                      poll_interval_s=1))
        def command(argv, timeout):
            script = argv[-1]
            self.assertEqual(script.count("DEVICE=/dev/xdevcfg"), 1)
            script = script.replace("DEVICE=/dev/xdevcfg", "DEVICE=" + str(self.device))
            script = script.replace('test -c "$DEVICE"', 'test -f "$DEVICE"')
            outcome = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=timeout)
            return CommandResult(outcome.returncode, outcome.stdout + outcome.stderr)
        return PLPreparation(config, runner=Mock(run=Mock(side_effect=command)))

    def test_prepared_image_is_checked_without_loading(self):
        result = PLPreparation(self.config, runner=self.runner)(5)
        self.assertTrue(result["prepared"])
        self.assertFalse(result["loaded"])
        self.assertEqual(result["image_sha256"], self.sha)

    def test_hash_mismatch_and_missing_readiness_fail_closed(self):
        self.image.write_bytes(b"changed image")
        with self.assertRaises(AgentError) as failure:
            PLPreparation(self.config, runner=self.runner)(5)
        self.assertEqual(failure.exception.code, ErrorCode.PL_TEST_UNAVAILABLE)
        self.image.write_bytes(b"known measurement image")
        self.done.unlink()
        with self.assertRaises(AgentError) as failure:
            PLPreparation(self.config, runner=self.runner)(5)
        self.assertEqual(failure.exception.code, ErrorCode.PL_TEST_UNAVAILABLE)

    def test_hash_mismatch_prevents_load_before_device_access(self):
        self.image.write_bytes(b"changed image")
        config = replace(self.config, observer=replace(self.config.observer, prepare_policy="load_verified"))
        with self.assertRaises(AgentError) as failure:
            PLPreparation(config, runner=self.runner)(5)
        self.assertIn("SHA-256", str(failure.exception))
        self.assertEqual(self.done.read_text(), "1\n")

    def test_approved_load_writes_fixture_even_when_prog_done_already_one(self):
        provider = self.load_fixture()
        result = provider(5)
        self.assertTrue(result["loaded"])
        self.assertEqual(self.device.read_bytes(), self.image.read_bytes())

    def test_failed_load_or_loader_timeout_does_not_report_prepared(self):
        for marker, expected in (("fail_load", ErrorCode.PL_TEST_UNAVAILABLE), ("timeout_load", ErrorCode.TIMEOUT)):
            with self.subTest(marker=marker):
                provider = self.load_fixture()
                path = self.root / marker
                path.touch()
                try:
                    with self.assertRaises(AgentError) as failure:
                        provider(5)
                    self.assertEqual(failure.exception.code, expected)
                finally:
                    path.unlink()

    def test_loaded_image_without_prog_done_confirmation_is_not_ready(self):
        provider = self.load_fixture()
        self.done.write_text("0\n")
        with self.assertRaises(AgentError) as failure:
            provider(2)
        self.assertEqual(failure.exception.code, ErrorCode.TIMEOUT)
        self.assertEqual(self.device.read_bytes(), self.image.read_bytes())
