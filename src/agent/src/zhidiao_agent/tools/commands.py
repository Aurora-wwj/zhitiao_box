"""Bounded noninteractive process execution, injectable in backend tests."""

import os
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from threading import Event
from typing import Protocol

from ..errors import AgentError, ErrorCode

LOG_LIMIT = 32768


def sanitized_log(text: str) -> str:
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "[REDACTED]", text, flags=re.S)
    text = re.sub(r"(?i)\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", text)
    text = re.sub(r"(?i)\b(password|token|api_key)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
    return text[-LOG_LIMIT:]


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str


class CommandRunner(Protocol):
    def run(self, argv: tuple[str, ...], timeout_s: float) -> CommandResult: ...


class ProcessRunner:
    def __init__(self, *, cancel_event: Event | None = None):
        self._cancel_event = cancel_event

    def _check_cancelled(self) -> None:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise AgentError(ErrorCode.CANCELLED, "Human cancelled the command.")

    def _wait(self, process, timeout_s: float) -> None:
        if self._cancel_event is None:
            process.wait(timeout=timeout_s)
            return
        deadline = time.monotonic() + timeout_s
        while True:
            self._check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout_s)
            try:
                process.wait(timeout=min(.1, remaining))
            except subprocess.TimeoutExpired:
                continue
            self._check_cancelled()
            return

    def _stop(self, process) -> None:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=10, check=False,
                )
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            process.kill()
        except ProcessLookupError:
            # The process may have exited between cancellation and tree cleanup.
            pass
        process.wait(timeout=5)

    def run(self, argv: tuple[str, ...], timeout_s: float) -> CommandResult:
        self._check_cancelled()
        try:
            with tempfile.TemporaryFile() as output:
                options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                           if os.name == "nt" else {"start_new_session": True})
                with subprocess.Popen(
                    argv, shell=False, stdin=subprocess.DEVNULL, stdout=output,
                    stderr=subprocess.STDOUT, **options,
                ) as process:
                    try:
                        self._wait(process, timeout_s)
                    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                        self._stop(process)
                        if isinstance(exc, KeyboardInterrupt):
                            raise AgentError(ErrorCode.CANCELLED, "Human cancelled the command.") from None
                        raise AgentError(ErrorCode.TIMEOUT, "Command exceeded its time budget.") from None
                    except AgentError:
                        self._stop(process)
                        raise
                    output.seek(max(0, output.tell() - LOG_LIMIT))
                    text = output.read(LOG_LIMIT).decode("utf-8", errors="replace")
                    return CommandResult(process.returncode, sanitized_log(text))
        except FileNotFoundError:
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Required executable was not found.") from None
        except OSError:
            raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "Cannot start the configured executable.") from None
