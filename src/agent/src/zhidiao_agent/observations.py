"""Validated observation seam; actual PL/Linux access is supplied by hardware code."""

import math
from collections.abc import Callable
from typing import Any

from .errors import AgentError, ErrorCode
from .models import OperationResult, invoke


def number(value: Any, *, zero: bool = False) -> float:
    try:
        result = float(value) if type(value) in (int, float) else float("nan")
    except (OverflowError, ValueError):
        result = float("nan")
    if not math.isfinite(result) or result < 0 or (not zero and result == 0):
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require a finite positive numeric value.")
    return result


def gpio_result(params: dict[str, Any], measurements: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(params, dict) or set(params) != {"expected_period_ms", "tolerance_ms"}:
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require expected_period_ms and tolerance_ms.")
    expected = number(params["expected_period_ms"])
    tolerance = number(params["tolerance_ms"], zero=True)
    if not isinstance(measurements, dict):
        raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid physical measurements.")
    try:
        measured = number(measurements.get("period_ms"))
    except AgentError:
        raise AgentError(ErrorCode.INVALID_RESPONSE, "Missing valid measured GPIO period.") from None
    frequency = 1000 / measured
    if not math.isfinite(frequency):
        raise AgentError(ErrorCode.INVALID_RESPONSE, "Measured GPIO period is outside the numeric range.")
    result = {
        "test_id": "gpio_period",
        "measurements": {"period_ms": measured, "frequency_hz": frequency},
        "expected": {"period_ms": expected, "tolerance_ms": tolerance},
        "passed": abs(measured - expected) <= tolerance,
    }
    # Preserve bounded acquisition evidence for audit without trusting a provider's
    # own PASS field. The numeric acceptance check above remains authoritative.
    metadata = {}
    for name in ("period_ticks", "high_ticks", "edge_start", "edge_end", "fresh_edges", "valid", "pl_clock_hz"):
        if name in measurements:
            value = measurements[name]
            if type(value) is not int or not 0 <= value <= 0xffffffff:
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid PL acquisition counter.")
            metadata[name] = value
    if "freshness_verified" in measurements:
        if measurements["freshness_verified"] is not True:
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Physical measurement is not fresh.")
        metadata["freshness_verified"] = True
    if "evidence_source" in measurements:
        source = measurements["evidence_source"]
        if not isinstance(source, str) or not 1 <= len(source) <= 64:
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid evidence source.")
        metadata["evidence_source"] = source
    for name in ("high_ms", "duty_cycle"):
        if name in measurements:
            try:
                value = number(measurements[name], zero=True)
            except AgentError:
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid pulse measurement.") from None
            if value > (measured if name == "high_ms" else 1):
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Pulse measurement exceeds the period.")
            result["measurements"][name] = value
    if metadata:
        result["observation"] = metadata
    return result


class ObservationBackend:
    """Callbacks must implement their own I/O deadlines; this seam does no I/O.

    uart_reader(duration_s, timeout_s) -> timestamped log list, or
        {"logs": [...], "overflow": bool, "truncated": bool,
         "partial_tail": bool, "capture_end_reason": "deadline" | "capture_limit"}
    A normal deadline tail is not fatal truncation. Legacy truncated=true and
    all hardware/decoding error flags retain their strict meaning.
    period_reader(timeout_s) -> {"period_ms": float}
    The callbacks must obtain real evidence, never synthesize a hardware result.
    """

    def __init__(
        self, *, uart_reader: Callable | None = None, period_reader: Callable | None = None,
        timeout_s: float = 15,
    ):
        self.uart_reader = uart_reader
        self.period_reader = period_reader
        self.timeout_s = timeout_s

    def read_target_log(self, duration_s: float) -> OperationResult:
        def operation():
            duration = number(duration_s)
            if duration > 60:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Capture duration must not exceed 60 seconds.")
            if self.uart_reader is None:
                raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "UART reader is not connected.")
            rows = self.uart_reader(duration, duration + number(self.timeout_s))
            capture = {}
            if isinstance(rows, dict):
                allowed = {"logs", "overflow", "truncated", "decoding_errors", "frame_errors", "parity_errors",
                           "bytes_captured", "capture_elapsed_ms", "fifo_reset", "timestamp_basis",
                           "partial_tail", "capture_end_reason"}
                if (not {"logs"} <= set(rows) <= allowed
                        or any(type(rows[key]) is not bool for key in ("overflow", "truncated", "fifo_reset", "partial_tail") if key in rows)
                        or any(type(rows[key]) is not int or not 0 <= rows[key] <= 131072
                               for key in ("decoding_errors", "frame_errors", "parity_errors", "bytes_captured", "capture_elapsed_ms")
                               if key in rows)
                        or ("timestamp_basis" in rows and rows["timestamp_basis"] != "board_monotonic_capture_elapsed_ms")
                        or ("capture_end_reason" in rows and rows["capture_end_reason"] not in ("deadline", "capture_limit"))
                        or (rows.get("capture_end_reason") == "capture_limit" and rows.get("truncated") is not True)):
                    raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid UART capture metadata.")
                capture = {key: value for key, value in rows.items() if key != "logs"}
                rows = rows["logs"]
            if not isinstance(rows, list) or len(rows) > 10000:
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid UART log list.")
            logs = []
            total = 0
            previous = 0.0
            for row in rows:
                if not isinstance(row, dict) or set(row) != {"timestamp_ms", "text"}:
                    raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid UART log entry.")
                try:
                    timestamp = number(row["timestamp_ms"], zero=True)
                except AgentError:
                    raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid UART timestamp.") from None
                text = row["text"]
                if timestamp < previous or not isinstance(text, str) or len(text) > 16384:
                    raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid UART text or time order.")
                try:
                    text.encode("utf-8")
                except UnicodeError:
                    raise AgentError(ErrorCode.INVALID_RESPONSE, "UART text must be valid Unicode.") from None
                previous = timestamp
                total += len(text)
                if total > 131072:
                    raise AgentError(ErrorCode.INVALID_RESPONSE, "UART capture is too large.")
                logs.append({"timestamp_ms": timestamp, "text": text})
            if capture.get("partial_tail") is True and (not logs or not logs[-1]["text"]):
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Missing UART partial tail evidence.")
            return {"duration_s": duration, "logs": logs, **capture}
        return invoke(operation, backend="observation_uart")

    def run_hardware_test(self, test_id: str, params: dict[str, Any]) -> OperationResult:
        def operation():
            if test_id != "gpio_period":
                raise AgentError(ErrorCode.PL_TEST_UNAVAILABLE, "Unsupported physical test.")
            # Validate goal before asking the provider to touch any hardware.
            gpio_result(params, {"period_ms": 1})
            if self.period_reader is None:
                raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "PL period reader is not connected.")
            measured = self.period_reader(number(self.timeout_s))
            return gpio_result(params, measured)
        return invoke(operation, backend="observation_pl")
