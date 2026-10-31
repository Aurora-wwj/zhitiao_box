"""Bounded structured workflow events shared by UI, reports and future adapters."""

import math
import threading
import time
from collections import deque
from datetime import datetime, timezone


class WorkflowEvents:
    def __init__(self):
        self._lock = threading.Lock()
        self._rows = deque(maxlen=256)
        self._sequence = 0
        self._started = time.monotonic()
        self._listeners = []

    def subscribe(self, listener):
        """Trusted, fast event consumers only; returns an idempotent unsubscribe."""
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe():
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)
        return unsubscribe

    def emit(self, kind: str, *, attempt: int = 0, tool_name: str | None = None,
             success: bool | None = None, error_code: str | None = None,
             period_ms: float | None = None, passed: bool | None = None, log_count: int | None = None):
        period_ms = (period_ms if type(period_ms) in (int, float) and 0 < period_ms < 1e12
                     and math.isfinite(period_ms) else None)
        passed = passed if type(passed) is bool else None
        log_count = log_count if type(log_count) is int and 0 <= log_count <= 10000 else None
        error_code = error_code if isinstance(error_code, str) and len(error_code) <= 64 else None
        with self._lock:
            self._sequence += 1
            row = {"sequence": self._sequence, "kind": kind, "attempt": attempt,
                   "elapsed_ms": round((time.monotonic() - self._started) * 1000),
                   "timestamp": datetime.now(timezone.utc).isoformat()}
            for name, value in (("tool_name", tool_name), ("success", success), ("error_code", error_code),
                                ("period_ms", period_ms), ("passed", passed), ("log_count", log_count)):
                if value is not None:
                    row[name] = value
            self._rows.append(row)
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(dict(row))
            except Exception:
                # Display callbacks cannot change a hardware operation's outcome.
                # Do not expose callback exception text or recursively notify it.
                with self._lock:
                    self._sequence += 1
                    self._rows.append({"sequence": self._sequence, "kind": "INDICATOR_ERROR",
                                       "attempt": attempt, "error_code": "EVENT_LISTENER_FAILED",
                                       "elapsed_ms": round((time.monotonic() - self._started) * 1000),
                                       "timestamp": datetime.now(timezone.utc).isoformat()})

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self._rows]
