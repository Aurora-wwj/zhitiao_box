import json
import os
import shutil
import subprocess
import sys
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from zhidiao_agent.deployment import DeploymentConfig, PLObserverConfig, UARTObserverConfig
from zhidiao_agent.errors import AgentError, ErrorCode
from zhidiao_agent.observations import ObservationBackend
from zhidiao_agent.tools.commands import CommandResult
from zhidiao_agent.tools.pl_uart import PLUARTReader
from zhidiao_agent.tools.real_backend import RealBackend


def envelope(raw=b"ZHIDIAO_OK\r\n", *, elapsed=5000, overflow=0, frame=0, parity=0, limited=0):
    rows = ["ZHIDIAO_UART_V1"] + [f"B {index * 7} {value:02X}" for index, value in enumerate(raw)]
    rows.append(f"E {elapsed} {len(raw)} {overflow} {frame} {parity} {limited}")
    return "\n".join(rows)


class UARTReaderTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="zhidiao-uart-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.hosts = self.root / "known_hosts"
        self.hosts.write_text("trusted offline fixture")
        self.config = DeploymentConfig(allowed_roots=(str(self.root),), known_hosts=str(self.hosts),
                                       uart_observer=UARTObserverConfig())
        self.runner = Mock()
        self.runner.run.return_value = CommandResult(0, envelope())
        self.reader = PLUARTReader(self.config, runner=self.runner)

    def capture(self, raw=b"ZHIDIAO_OK\r\n", **metadata):
        self.runner.run.return_value = CommandResult(0, envelope(raw, **metadata))
        return self.reader(5, 20)

    def test_preview_discloses_one_fifo_reset_and_transport_margin_without_io(self):
        plan = self.reader.preview(5, 20)
        self.assertEqual(plan["timeout_s"], 8)
        self.assertEqual(len(plan["commands"]), 1)
        script = plan["commands"][0][-1]
        self.assertEqual(script.count('devmem 0x43C5000C 32 0x00000002'), 1)
        self.assertIn("Reset UART RX FIFO", plan["effects"])
        self.assertIn('"$BB" usleep 10000', script)
        self.assertIn('/proc/uptime', script)
        self.assertNotIn('"$BB" sleep ', script)
        self.assertNotIn('/dev/xdevcfg', script)
        self.runner.run.assert_not_called()

    def test_multiline_crlf_and_utf8_are_reassembled_with_real_byte_timestamps(self):
        result = self.capture("ZHIDIAO_OK\r\n日志正常\r\n".encode())
        self.assertEqual([row["text"] for row in result["logs"]], ["ZHIDIAO_OK", "日志正常"])
        self.assertLess(result["logs"][0]["timestamp_ms"], result["logs"][1]["timestamp_ms"])
        self.assertEqual(result["decoding_errors"], 0)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["timestamp_basis"], "board_monotonic_capture_elapsed_ms")

    def test_successful_empty_capture_is_not_a_measurement_verdict(self):
        self.capture(b"")
        result = ObservationBackend(uart_reader=self.reader).read_target_log(5)
        self.assertTrue(result.success)
        self.assertEqual(result.data["logs"], [])
        self.assertNotIn("passed", result.data)

    def test_deadline_partial_line_is_returned_without_fatal_truncation(self):
        result = self.capture(b"first\nZHIDIAO_")
        self.assertEqual([row["text"] for row in result["logs"]], ["first", "ZHIDIAO_"])
        self.assertFalse(result["truncated"])
        self.assertTrue(result["partial_tail"])
        self.assertEqual(result["capture_end_reason"], "deadline")

    def test_invalid_utf8_is_counted_but_valid_replacement_character_is_not(self):
        result = self.capture(b"\xff\xfe\n" + "\ufffd\n".encode())
        self.assertEqual(result["decoding_errors"], 2)
        self.assertEqual(result["logs"][1]["text"], "\ufffd")

    def test_health_and_capacity_flags_are_preserved(self):
        result = self.capture(b"ok\n", elapsed=100, overflow=1, frame=1, parity=1, limited=1)
        self.assertTrue(result["overflow"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["frame_errors"], 1)
        self.assertEqual(result["parity_errors"], 1)
        self.assertEqual(result["bytes_captured"], 3)

    def test_malformed_truncated_or_inconsistent_transport_output_is_rejected(self):
        for output in ("", "B 0 55", "ZHIDIAO_UART_V1\nE 5000 1 0 0 0 0",
                       "ZHIDIAO_UART_V1\nB 5001 55\nE 5001 1 0 0 0 0",
                       "ZHIDIAO_UART_V1\nB 5 55\nB 4 55\nE 5000 2 0 0 0 0",
                       "ZHIDIAO_UART_V1\nE 1 0 0 0 0 0", envelope()+"\nextra",
                       "ZHIDIAO_UART_V1\nB 0 FFZZ\nE 5000 1 0 0 0 0"):
            self.runner.run.return_value = CommandResult(0, output)
            with self.subTest(output=output), self.assertRaises(AgentError) as caught:
                self.reader(5, 20)
            self.assertEqual(caught.exception.code, ErrorCode.INVALID_RESPONSE)

    def test_unavailable_registers_transport_and_timeout_use_structured_errors(self):
        for code, expected in ((255, "SSH_CONNECT_FAILED"), (72, "UART_READ_FAILED"),
                               (73, "UART_READ_FAILED"), (74, "INVALID_RESPONSE"), (75, "TIMEOUT")):
            self.runner.run.return_value = CommandResult(code, "private transport stderr")
            result = ObservationBackend(uart_reader=self.reader).read_target_log(5)
            self.assertEqual(result.error_code, expected)
            self.assertNotIn("private", result.message)
        self.runner.run.side_effect = TimeoutError("private")
        self.assertEqual(ObservationBackend(uart_reader=self.reader).read_target_log(5).error_code, "TIMEOUT")

    def test_invalid_inputs_and_insufficient_transport_budget_do_not_start_capture(self):
        for duration, timeout in ((0, 10), (61, 100), (True, 10), (float("nan"), 10), (5, 5), (5, -1)):
            with self.subTest(duration=duration, timeout=timeout), self.assertRaises(AgentError):
                self.reader(duration, timeout)
        self.runner.run.assert_not_called()

    def test_config_json_and_register_write_scope_are_strict(self):
        filename = self.root / "deployment.json"
        filename.write_text(json.dumps(asdict(self.config)), encoding="utf-8")
        self.assertEqual(DeploymentConfig.load(str(filename)), self.config)
        for fields in ({"rx_addr": "0x43C50000;reboot"}, {"control_addr": "0x43C40000"},
                       {"status_addr": "0x43C50009"}, {"baud_rate": 9600}, {"max_bytes": 1025},
                       {"max_bytes": True}, {"pl_rx_pin": "bad pin"}, {"monotonic_path": "/proc/../secret"},
                       {"poll_interval_s": float("inf")}):
            with self.subTest(fields=fields), self.assertRaises(AgentError):
                UARTObserverConfig(**fields)

    def test_real_backend_requires_single_use_capture_permission_and_labels_pa2(self):
        backend = RealBackend(self.config, runner=self.runner)
        self.assertEqual(backend.read_target_log(5).error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()
        ticket = backend._preview_uart_capture(5).data
        backend.approvals.decide(ticket["proposal_id"], ticket["fingerprint"], approved=True)
        outcome = backend.read_target_log(5)
        self.assertTrue(outcome.success, outcome.to_dict())
        self.assertNotIn("observed_gpio", outcome.data)
        self.assertEqual(outcome.data["uart_tx_gpio"], "PA2")
        self.assertEqual(outcome.data["pl_rx_pin"], "M17")
        self.assertEqual(outcome.data["evidence_source"], "real_pl_uart")
        self.assertEqual(backend.read_target_log(5).error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_called_once()

    def test_changed_duration_or_reader_identity_cannot_reuse_a_capture(self):
        backend = RealBackend(self.config, runner=self.runner)
        ticket = backend._preview_uart_capture(5).data
        backend.approvals.decide(ticket["proposal_id"], ticket["fingerprint"], approved=True)
        self.assertEqual(backend.read_target_log(3).error_code, "APPROVAL_REQUIRED")
        backend.observations.uart_reader.config = replace(self.config, host="192.168.10.3")
        self.assertEqual(backend.preview_observation().error_code, "APPROVAL_REQUIRED")
        self.runner.run.assert_not_called()

    def test_real_backend_automatically_wires_both_independent_channels(self):
        backend = RealBackend(replace(self.config, observer=PLObserverConfig()), runner=self.runner)
        self.assertIsInstance(backend.observations.uart_reader, PLUARTReader)
        preview = backend.preview_observation("read_target_log", 5)
        self.assertTrue(preview.success)
        self.assertTrue(preview.data["period_available"])
        self.assertTrue(preview.data["uart_available"])
        self.assertIn("resets its RX FIFO", preview.data["descriptor"]["effects"])


@unittest.skipUnless(os.name == "posix" and shutil.which("sh"), "POSIX UART helper regression")
class UARTShellTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="zhidiao-uart-shell-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.state = self.root / "state.json"
        self.done = self.root / "prog_done"
        self.done.write_text("1\n")
        hosts = self.root / "known_hosts"
        hosts.write_text("offline fixture")
        busybox = self.root / "busybox"
        busybox.write_text("#!" + sys.executable + "\n" + '''import json,pathlib,sys,time
state_file=pathlib.Path(__file__).with_name('state.json')
cmd=sys.argv[1]
if cmd=='cat': print(pathlib.Path(sys.argv[2]).read_text(),end='')
elif cmd=='usleep' and sys.argv[2].isdigit(): time.sleep(min(int(sys.argv[2])/1000000,.001))
elif cmd=='devmem':
    state=json.loads(state_file.read_text())
    if sys.argv[2]=='0x43C5000C' and sys.argv[3:]==['32','0x00000002']:
        state['reset']=state.get('reset',0)+1; state['index']=0
    elif sys.argv[2]=='0x43C50008':
        print(hex((1 if state['index']<len(state['bytes']) else 0) | (state.get('flags',0) if state.get('reset') else 32)))
    elif sys.argv[2]=='0x43C50000':
        print(hex(state['bytes'][state['index']] if state.get('reset') else 79))
        state['index']+=1
        if state.get('clock_path') and state['index']==state.get('jump_after'):
            pathlib.Path(state['clock_path']).write_text('2.00 0.00' + chr(10))
    else: sys.exit(1)
    state_file.write_text(json.dumps(state))
else: sys.exit(127)
''', encoding="utf-8")
        busybox.chmod(0o700)
        config = DeploymentConfig(allowed_roots=(str(self.root),), known_hosts=str(hosts),
            uart_observer=UARTObserverConfig(busybox_path=str(busybox), prog_done_path=str(self.done)))
        def execute(argv, timeout):
            outcome = subprocess.run(["sh", "-c", argv[-1]], capture_output=True, encoding="utf-8", timeout=timeout)
            return CommandResult(outcome.returncode, outcome.stdout+outcome.stderr)
        self.reader = PLUARTReader(config, runner=Mock(run=Mock(side_effect=execute)))

    def capture(self, raw, flags=0):
        self.state.write_text(json.dumps({"bytes": list(raw), "index": 0, "flags": flags}))
        return self.reader(2, 6)

    def test_actual_shell_resets_fifo_once_drains_lines_and_uses_monotonic_time(self):
        result = self.capture(b"ZHIDIAO_OK\r\nZHIDIAO_OK\r\n")
        self.assertEqual([row["text"] for row in result["logs"]], ["ZHIDIAO_OK", "ZHIDIAO_OK"])
        self.assertEqual(json.loads(self.state.read_text())["reset"], 1)
        self.assertFalse(result["overflow"], "Old sticky errors must not leak into the new session.")
        self.assertGreater(result["logs"][0]["timestamp_ms"], 0)
        self.assertGreaterEqual(result["capture_elapsed_ms"], 2000)

    def test_actual_shell_successfully_captures_silence(self):
        result = self.capture(b"")
        self.assertEqual(result["logs"], [])
        self.assertFalse(result["truncated"])

    def test_actual_shell_preserves_partial_and_hardware_health(self):
        result = self.capture(b"ZHIDIAO_", flags=32|64|128)
        self.assertFalse(result["truncated"])
        self.assertTrue(result["partial_tail"])
        self.assertTrue(result["overflow"])
        self.assertEqual(result["frame_errors"], 1)
        self.assertEqual(result["parity_errors"], 1)

    def test_byte_read_crossing_deadline_is_not_a_capacity_failure(self):
        clock = self.root / "clock"
        clock.write_text("0.00 0.00\n")
        self.reader.config = replace(self.reader.config,
            uart_observer=replace(self.reader.config.uart_observer, monotonic_path=str(clock)))
        self.state.write_text(json.dumps({"bytes": list(b"ok\nZx"), "index": 0,
                                         "clock_path": str(clock), "jump_after": 5}))
        result = self.reader(2, 6)
        self.assertEqual([row["text"] for row in result["logs"]], ["ok", "Z"])
        self.assertEqual(result["bytes_captured"], 4)
        self.assertTrue(result["partial_tail"])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["capture_end_reason"], "deadline")

    def test_actual_shell_byte_budget_still_marks_capture_limit(self):
        self.reader.config = replace(self.reader.config,
            uart_observer=replace(self.reader.config.uart_observer, max_bytes=4))
        result = self.capture(b"ok\nZMORE")
        self.assertEqual(result["bytes_captured"], 4)
        self.assertTrue(result["partial_tail"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["capture_end_reason"], "capture_limit")
