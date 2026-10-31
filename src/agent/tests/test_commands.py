import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from zhidiao_agent.errors import AgentError, ErrorCode
from zhidiao_agent.tools.commands import LOG_LIMIT, ProcessRunner, sanitized_log


class ProcessRunnerTests(unittest.TestCase):
    def test_process_output_and_exit_status_without_shell(self):
        result = ProcessRunner().run((sys.executable, "-B", "-c", "print('literal;$(not-a-shell)')"), 10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.output.strip(), "literal;$(not-a-shell)")
        result = ProcessRunner().run((sys.executable, "-B", "-c", "raise SystemExit(2)"), 10)
        self.assertEqual(result.returncode, 2)

    def test_timeout_is_stable_error(self):
        with self.assertRaises(AgentError) as caught:
            ProcessRunner().run((sys.executable, "-B", "-c", "import time; time.sleep(10)"), .1)
        self.assertEqual(caught.exception.code, ErrorCode.TIMEOUT)

    def test_logs_are_bounded_and_redacted(self):
        result = ProcessRunner().run((sys.executable, "-B", "-c", "print('x' * 50000)"), 10)
        self.assertLessEqual(len(result.output), LOG_LIMIT)
        log = sanitized_log("password=hidden token:secret api_key=secret Bearer abcdef sk-123456789abcdef")
        for value in ("hidden", "secret", "abcdef", "sk-123456789abcdef"):
            self.assertNotIn(value, log)

    def test_keyboard_interrupt_stops_owned_process(self):
        runner = ProcessRunner()
        with patch("zhidiao_agent.tools.commands.subprocess.Popen") as popen, patch.object(runner, "_stop") as stop:
            process = popen.return_value.__enter__.return_value
            process.wait.side_effect = KeyboardInterrupt()
            with self.assertRaises(AgentError) as caught:
                runner.run(("not-actually-executed",), 10)
            self.assertEqual(caught.exception.code, ErrorCode.CANCELLED)
            stop.assert_called_once_with(process)

    def test_pre_cancelled_command_never_starts_a_process(self):
        cancelled = threading.Event()
        cancelled.set()
        with patch("zhidiao_agent.tools.commands.subprocess.Popen") as popen:
            with self.assertRaises(AgentError) as caught:
                ProcessRunner(cancel_event=cancelled).run(("not-actually-executed",), 1)
        self.assertEqual(caught.exception.code, ErrorCode.CANCELLED)
        popen.assert_not_called()

    def test_cancellation_stops_running_local_process_and_its_child(self):
        with TemporaryDirectory(prefix="zhidiao-process-cancel-") as temporary:
            root = Path(temporary)
            ready, finished = root / "ready", root / "should-not-finish"
            child = ("from pathlib import Path; import time; "
                     f"Path({str(ready)!r}).write_text('ready'); "
                     f"time.sleep(1.5); Path({str(finished)!r}).write_text('continued')")
            parent = ("import subprocess, sys, time; "
                      f"subprocess.Popen([sys.executable, '-B', '-c', {child!r}]); "
                      "time.sleep(10)")
            cancelled = threading.Event()
            runner = ProcessRunner(cancel_event=cancelled)
            def request_cancel():
                deadline = time.monotonic() + 3
                while not ready.exists() and time.monotonic() < deadline:
                    cancelled.wait(.01)
                cancelled.set()
            requester = threading.Thread(target=request_cancel)
            requester.start()
            try:
                with self.assertRaises(AgentError) as caught:
                    runner.run((sys.executable, "-B", "-c", parent), 5)
                self.assertEqual(caught.exception.code, ErrorCode.CANCELLED)
                self.assertTrue(ready.exists(), "Cancellation must happen after the child starts.")
                # A surviving grandchild would leave this file after its delay.
                threading.Event().wait(1.8)
                self.assertFalse(finished.exists(), "Local descendant outlived cancellation.")
            finally:
                requester.join(timeout=4)

    def test_cancel_capable_runner_keeps_timeout_error_when_not_cancelled(self):
        with self.assertRaises(AgentError) as caught:
            ProcessRunner(cancel_event=threading.Event()).run(
                (sys.executable, "-B", "-c", "import time; time.sleep(10)"), .1)
        self.assertEqual(caught.exception.code, ErrorCode.TIMEOUT)

    def test_process_exit_race_does_not_hide_cancellation(self):
        runner = ProcessRunner()
        with patch("zhidiao_agent.tools.commands.subprocess.Popen") as popen:
            process = popen.return_value.__enter__.return_value
            process.wait.side_effect = [KeyboardInterrupt(), 0]
            process.kill.side_effect = ProcessLookupError()
            with patch.object(runner, "_stop", wraps=runner._stop), \
                    patch("zhidiao_agent.tools.commands.os.killpg", create=True), \
                    patch("zhidiao_agent.tools.commands.subprocess.run"):
                with self.assertRaises(AgentError) as caught:
                    runner.run(("not-actually-executed",), 1)
        self.assertEqual(caught.exception.code, ErrorCode.CANCELLED)
