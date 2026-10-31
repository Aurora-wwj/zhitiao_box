"""Optional four-LED presentation adapter driven by trusted workflow events.

All I/O lives on a separate worker/transport. No model-facing tool, shell input,
GPIO-direction write, FPGA loading, or DUT verdict is introduced here.
"""

import logging
import threading
import time

from .deployment import DeploymentConfig, StatusIndicatorConfig
from .errors import AgentError, ErrorCode
from .tools.commands import ProcessRunner
from .tools.ssh import ssh_command

TOOLS = ("build_firmware", "flash_firmware", "read_target_log", "run_hardware_test")
STARTS = {"build_firmware": "BUILDING", "flash_firmware": "FLASHING",
          "read_target_log": "OBSERVING", "run_hardware_test": "OBSERVING"}
LOGGER = logging.getLogger(__name__)
WRITE_TIMEOUT_S = 2.0


class LEDProgress:
    """Pure state/reducer: tool success is independent of a measurement's pass."""

    def __init__(self, config: StatusIndicatorConfig):
        self.config = config
        self.attempt = 0
        self.completed = 0
        self.active = None
        self.failed = None
        self.started = 0.0
        self.sequence = 0

    def accept(self, event: dict, now: float) -> bool:
        sequence, attempt = event.get("sequence"), event.get("attempt")
        if (type(sequence) is not int or sequence <= self.sequence or type(attempt) is not int
                or not 1 <= attempt <= 3):
            return False
        self.sequence = sequence
        kind, tool = event.get("kind"), event.get("tool_name")
        if kind == "BUILDING" and tool == TOOLS[0] and attempt > self.attempt:
            self.attempt, self.completed = attempt, 0
            self.active, self.failed, self.started = 0, None, now
            return True
        if attempt != self.attempt or not self.attempt:
            return False
        if tool in TOOLS:
            index = TOOLS.index(tool)
            if kind == STARTS[tool] and self.failed is None and not self.completed & (1 << index):
                self.active, self.started = index, now
                return True
            if kind == "TOOL_FINISHED" and self.active == index:
                success = event.get("success")
                if type(success) is not bool:
                    return False
                if success:
                    self.completed |= 1 << index
                    self.active = None
                else:
                    self.failed, self.active, self.started = index, None, now
                return True
        if kind in {"ERROR", "STOPPED"} and self.active is not None:
            self.failed, self.active, self.started = self.active, None, now
            return True
        # ANALYZING, WAITING_APPROVAL, FAIL, PASS: preserve real tool progress.
        # In PL-only mode LED3 stays off even if the selected checks pass.
        return False

    @property
    def blinking(self):
        return self.active is not None or self.failed is not None

    def value(self, now: float) -> int:
        logical = self.completed
        elapsed = max(0, now - self.started)
        if self.failed is not None:
            # Two short pulses, followed by a visible pause (one-second cycle).
            phase = elapsed % 1.0
            if phase < .12 or .24 <= phase < .36:
                logical |= 1 << self.failed
        elif self.active is not None and elapsed % 1.0 < .5:
            logical |= 1 << self.active
        return logical ^ 0xF if self.config.active_low else logical


class AXIGPIOLedWriter:
    """Only a fixed LED address and a validated 4-bit value can be written."""

    timeout_s = WRITE_TIMEOUT_S

    def __init__(self, deployment: DeploymentConfig, *, runner=None):
        if not isinstance(deployment.status_indicator, StatusIndicatorConfig):
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "LED indicator is not configured.")
        self._deployment = deployment
        self._cancel = threading.Event()
        self._runner = runner if runner is not None else ProcessRunner(cancel_event=self._cancel)

    def __call__(self, value: int):
        if type(value) is not int or not 0 <= value <= 0xF:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require a four-bit LED value.")
        # Never use strings supplied by a model, event, or UI in this command.
        command = f"/bin/busybox devmem 0x43C60000 32 0x{value:X}"
        result = self._runner.run(ssh_command(self._deployment) + (command,), self.timeout_s)
        if result.returncode != 0:
            raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "LED status write failed.")

    def cancel(self):
        self._cancel.set()


class LEDStatusAdapter:
    """Nonblocking, coalescing consumer with a bounded failure circuit breaker.

    Constructors/subscription are pure. The first approved BUILDING event starts
    the worker; static states are written once and the worker then exits. Only
    running/error states keep a blinking worker alive. Close before replacing
    the owning task or shutting down the frontend.
    """

    def __init__(self, deployment: DeploymentConfig, events, *, writer=None):
        self._progress = LEDProgress(deployment.status_indicator)
        self._events = events
        self._writer = writer if writer is not None else AXIGPIOLedWriter(deployment)
        self._condition = threading.Condition()
        self._thread = None
        self._closed = self._closing = self._disabled = False
        self._version = 0
        self._last_value = None
        self._unsubscribe = events.subscribe(self._accept)

    def _accept(self, event):
        startup_failed = False
        with self._condition:
            if self._closed or self._closing or self._disabled or not self._progress.accept(event, time.monotonic()):
                return
            self._version += 1
            self._condition.notify_all()
            if self._thread is None:
                try:
                    self._thread = threading.Thread(target=self._run, name="zhitiao-led-status", daemon=True)
                    self._thread.start()
                except Exception:
                    # A failed start leaves an unjoinable Thread object. Retire
                    # it here so optional display cleanup cannot fail the CLI.
                    self._thread = None
                    self._disabled = startup_failed = True
        if startup_failed:
            self._warn()

    def _warn(self):
        # Raw transport/exception text can contain paths or credentials.
        LOGGER.warning("Optional LED status indicator unavailable; hardware verdict is unchanged.")
        self._events.emit("INDICATOR_ERROR", attempt=self._progress.attempt,
                          error_code="STATUS_INDICATOR_UNAVAILABLE")

    def _run(self):
        try:
            while True:
                with self._condition:
                    if self._closed:
                        return
                    version = self._version
                    value = self._progress.value(time.monotonic())
                if value != self._last_value:
                    self._writer(value)
                    self._last_value = value
                with self._condition:
                    if self._version != version:
                        continue
                    if not self._progress.blinking:
                        self._thread = None
                        return
                    self._condition.wait(timeout=.04)
        except Exception:
            with self._condition:
                self._disabled = True
                closing = self._closed
            if not closing:
                self._warn()
        finally:
            with self._condition:
                if self._thread is threading.current_thread():
                    self._thread = None

    def close(self):
        self._unsubscribe()
        with self._condition:
            self._closing = True
            # Let a pending final static write finish; do not turn LEDs off.
            thread = self._thread
            flush = not self._progress.blinking
            if flush and thread is not None:
                self._condition.notify_all()
        if thread is not None and flush:
            thread.join(timeout=WRITE_TIMEOUT_S + .5)
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        if thread is not None and thread.is_alive():
            self._writer.cancel()
            # Windows ProcessRunner may need taskkill's bounded tree cleanup.
            thread.join(timeout=18)
