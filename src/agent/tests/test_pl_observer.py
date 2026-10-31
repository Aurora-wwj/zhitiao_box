import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock

from zhidiao_agent.deployment import DeploymentConfig, PLObserverConfig
from zhidiao_agent.errors import AgentError, ErrorCode
from zhidiao_agent.observations import ObservationBackend
from zhidiao_agent.tools.commands import CommandResult
from zhidiao_agent.tools.pl_observer import PLPeriodReader


class PLReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hosts = self.root / "known hosts"
        self.hosts.write_text("verified host fixture")
        self.config = DeploymentConfig(allowed_roots=(str(self.root),), known_hosts=str(self.hosts),
                                       observer=PLObserverConfig())
        self.runner = Mock()
        self.reader = PLPeriodReader(self.config, runner=self.runner)
        self.runner.run.return_value = CommandResult(0, "ZHIDIAO_PL_V1 128 135 135 1 60096000 30048000\n")

    def test_preview_is_pure_and_discloses_readiness_and_image_limits(self):
        preview = self.reader.preview(15)
        self.assertEqual(len(preview["commands"]), 1)
        command = preview["commands"][0]
        self.assertEqual(command[0], "ssh")
        self.assertIn("BatchMode=yes", command)
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("HostKeyAlgorithms=+ssh-rsa", command)
        script = command[-1]
        self.assertIn("/bin/busybox", script)
        self.assertIn("0x43C30000", script)
        self.assertIn("0x43C40008", script)
        self.assertNotIn("/dev/xdevcfg", script)
        self.assertIn("do not identify", preview["image_identity"])
        self.runner.run.assert_not_called()

    def test_fresh_measurement_is_parsed_with_quality_evidence(self):
        measured = self.reader(15)
        self.assertEqual(measured["period_ms"], 600.96)
        self.assertEqual(measured["high_ms"], 300.48)
        self.assertEqual(measured["duty_cycle"], 0.5)
        self.assertEqual(measured["fresh_edges"], 7)
        self.assertTrue(measured["freshness_verified"])
        self.runner.run.assert_called_once()
        self.assertEqual(self.runner.run.call_args.args[1], 18)
        self.assertEqual(self.reader.preview(15)["observation_timeout_s"], 15)
        self.assertIn('"$BB" usleep 50000', self.reader.preview(15)["commands"][0][-1])
        self.assertNotIn('"$BB" sleep ', self.reader.preview(15)["commands"][0][-1])

    def test_wrap_around_accepts_two_new_edges(self):
        self.runner.run.return_value = CommandResult(0, "ZHIDIAO_PL_V1 4294967295 1 1 1 60000000 30000000")
        self.assertEqual(self.reader(15)["fresh_edges"], 2)

    def test_stale_invalid_and_inconsistent_snapshots_are_rejected(self):
        rows = [
            "ZHIDIAO_PL_V1 128 128 128 1 60000000 30000000",  # stale
            "ZHIDIAO_PL_V1 128 129 129 1 60000000 30000000",  # one edge only
            "ZHIDIAO_PL_V1 128 130 131 1 60000000 30000000",  # torn snapshot
            "ZHIDIAO_PL_V1 128 130 130 0 60000000 30000000",  # invalid
            "ZHIDIAO_PL_V1 128 130 130 1 0 0",  # zero period
            "ZHIDIAO_PL_V1 128 130 130 1 60000000 60000001",  # invalid high
            "ZHIDIAO_PL_V1 128 127 127 1 60000000 30000000",  # reset/backwards
            "ZHIDIAO_PL_V1 0 4294967296 4294967296 1 1 1",  # overflow
            "banner\nZHIDIAO_PL_V1 128 130 130 1 60000000 30000000",
            "ZHIDIAO_PL_V1 128 130 130 1 60000000 30000000\nextra",
            "", "not a register snapshot",
        ]
        for row in rows:
            with self.subTest(row=row), self.assertRaises(AgentError) as failure:
                self.runner.run.return_value = CommandResult(0, row)
                self.reader(15)
            self.assertEqual(failure.exception.code, ErrorCode.INVALID_RESPONSE)

    def test_transport_and_deployment_failures_have_uniform_codes(self):
        for returncode, expected in ((255, "SSH_CONNECT_FAILED"), (75, "TIMEOUT"),
                                     (72, "PL_TEST_UNAVAILABLE"), (73, "PL_TEST_UNAVAILABLE"),
                                     (127, "PL_TEST_UNAVAILABLE"), (74, "INVALID_RESPONSE")):
            with self.subTest(returncode=returncode):
                self.runner.run.return_value = CommandResult(returncode, "private stderr")
                result = ObservationBackend(period_reader=self.reader).run_hardware_test(
                    "gpio_period", {"expected_period_ms": 600, "tolerance_ms": 50})
                self.assertFalse(result.success)
                self.assertEqual(result.error_code, expected)
                self.assertNotIn("private stderr", result.message)
        self.runner.run.side_effect = TimeoutError("private transport exception")
        result = ObservationBackend(period_reader=self.reader).run_hardware_test(
            "gpio_period", {"expected_period_ms": 600, "tolerance_ms": 50})
        self.assertEqual(result.error_code, "TIMEOUT")

    def test_success_and_pass_are_independent_for_real_evidence(self):
        observations = ObservationBackend(period_reader=self.reader)
        result = observations.run_hardware_test("gpio_period", {"expected_period_ms": 1000, "tolerance_ms": 50})
        self.assertTrue(result.success)
        self.assertFalse(result.data["passed"])
        result = observations.run_hardware_test("gpio_period", {"expected_period_ms": 600, "tolerance_ms": 50})
        self.assertTrue(result.success)
        self.assertTrue(result.data["passed"])

    def test_profile_json_and_invalid_configuration(self):
        filename = self.root / "deployment.json"
        document = {**asdict(self.config), "allowed_roots": [str(self.root)]}
        filename.write_text(json.dumps(document), encoding="utf-8")
        self.assertEqual(DeploymentConfig.load(str(filename)), self.config)
        for changes in ({"period_addr": "0x43C30000; reboot"}, {"edge_addr": "0x43C30001"},
                        {"pl_clock_hz": True}, {"min_new_edges": 1}, {"valid_addr": "0x43C30000"},
                        {"busybox_path": "/bin/busybox;reboot"}, {"prog_done_path": "relative"},
                        {"poll_interval_s": 0}, {"timeout_s": float("nan")},
                        {"bitstream": "/sd/pl/image.bit"}, {"bitstream_sha256": "0" * 64}):
            with self.subTest(changes=changes), self.assertRaises(AgentError):
                replace(self.config.observer, **changes)

    def test_invalid_timeout_or_missing_ssh_trust_has_no_io(self):
        for timeout in (True, 0, -1, float("nan"), 121):
            with self.subTest(timeout=timeout), self.assertRaises(AgentError):
                self.reader(timeout)
        self.hosts.unlink()
        with self.assertRaises(AgentError):
            self.reader(15)
        self.runner.run.assert_not_called()


@unittest.skipUnless(os.name == "posix" and shutil.which("sh"), "POSIX helper execution regression")
class RemoteHelperTests(PLReaderTests):
    """Execute the generated shell locally against a fake BusyBox, never SSH.

    These checks test the polling algorithm itself rather than only accepting a
    mocked final SSH response. All register reads and sleeps remain simulated.
    """

    def setUp(self):
        super().setUp()
        self.state_file = self.root / "registers.json"
        self.prog_done = self.root / "prog_done"
        self.prog_done.write_text("1\n")
        self.busybox = self.root / "fake_busybox"
        self.busybox.write_text("#!" + sys.executable + "\n" + '''import hashlib,json,pathlib,sys
state_file = pathlib.Path(__file__).with_name('registers.json')
cmd = sys.argv[1]
if cmd == 'cat':
    print(pathlib.Path(sys.argv[2]).read_text(), end='')
elif cmd == 'usleep' and sys.argv[2].isdigit():
    pass
elif cmd == 'sha256sum':
    print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest() + '  -')
elif cmd == 'devmem':
    state = json.loads(state_file.read_text())
    if state.get('malformed'):
        print('not hex')
    elif sys.argv[2] == '0x43C40000':
        index = state.get('index', 0)
        print('0x%08X' % state['edges'][min(index, len(state['edges']) - 1)])
        state['index'] = index + 1
        state_file.write_text(json.dumps(state))
    else:
        registers = {'0x43C40008': state.get('valid', 1),
                     '0x43C30000': state.get('period', 60000000),
                     '0x43C30008': state.get('high', 30000000)}
        print('0x%08X' % registers[sys.argv[2]])
else:
    sys.exit(127)
''', encoding="utf-8")
        self.busybox.chmod(0o700)
        observer = replace(self.config.observer, busybox_path=str(self.busybox),
                           prog_done_path=str(self.prog_done), poll_interval_s=0.1)
        self.config = replace(self.config, observer=observer)
        self.reader = PLPeriodReader(self.config, runner=self.runner)

        def execute(argv, timeout_s):
            output = subprocess.run(["sh", "-c", argv[-1]], capture_output=True, text=True, timeout=timeout_s)
            return CommandResult(output.returncode, output.stdout + output.stderr)
        self.runner.run.side_effect = execute

    # Do not re-run mock-response tests from the superclass against a local shell.
    test_preview_is_pure_and_discloses_readiness_and_image_limits = None
    test_fresh_measurement_is_parsed_with_quality_evidence = None
    test_wrap_around_accepts_two_new_edges = None
    test_stale_invalid_and_inconsistent_snapshots_are_rejected = None
    test_transport_and_deployment_failures_have_uniform_codes = None
    test_success_and_pass_are_independent_for_real_evidence = None
    test_profile_json_and_invalid_configuration = None
    test_invalid_timeout_or_missing_ssh_trust_has_no_io = None

    def write_state(self, **changes):
        self.state_file.write_text(json.dumps({"edges": [100, 102, 102], **changes}))

    def test_helper_waits_for_two_edges_and_returns_fresh_snapshot(self):
        self.write_state(edges=[100, 101, 102, 102])
        self.assertEqual(self.reader(2)["fresh_edges"], 2)

    def test_helper_waits_on_stale_counter_and_valid_zero(self):
        for changes in ({"edges": [100]}, {"valid": 0}):
            with self.subTest(changes=changes):
                self.write_state(**changes)
                with self.assertRaises(AgentError) as failure:
                    self.reader(2)
                self.assertEqual(failure.exception.code, ErrorCode.TIMEOUT)

    def test_helper_retries_a_snapshot_with_intervening_edge(self):
        self.write_state(edges=[100, 102, 103, 104, 104])
        self.assertEqual(self.reader(2)["fresh_edges"], 4)

    def test_helper_accepts_wrap_around(self):
        self.write_state(edges=[0xFFFFFFFF, 1, 1])
        self.assertEqual(self.reader(2)["fresh_edges"], 2)

    def test_helper_refuses_unready_pl_and_malformed_register_data(self):
        self.prog_done.write_text("0\n")
        self.write_state()
        with self.assertRaises(AgentError) as failure:
            self.reader(2)
        self.assertEqual(failure.exception.code, ErrorCode.PL_TEST_UNAVAILABLE)
        self.assertNotIn("index", json.loads(self.state_file.read_text()))
        self.prog_done.write_text("1\n")
        self.write_state(malformed=True)
        with self.assertRaises(AgentError) as failure:
            self.reader(2)
        self.assertEqual(failure.exception.code, ErrorCode.INVALID_RESPONSE)

    def test_helper_checks_optional_image_hash_but_never_loads_it(self):
        image = self.root / "measurement.bit"
        image.write_bytes(b"known good fixture")
        observer = replace(self.config.observer, bitstream=str(image),
                           bitstream_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
        reader = PLPeriodReader(replace(self.config, observer=observer), runner=self.runner)
        self.write_state()
        self.assertEqual(reader(2)["fresh_edges"], 2)
        image.write_bytes(b"modified image")
        with self.assertRaises(AgentError) as failure:
            reader(2)
        self.assertEqual(failure.exception.code, ErrorCode.PL_TEST_UNAVAILABLE)
