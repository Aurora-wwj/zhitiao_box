"""Deterministic simulation; never accesses files, networks or hardware."""

import math
from typing import Any

from ..config import BoardPaths
from ..errors import AgentError, ErrorCode
from ..models import OperationResult, invoke
from ..observations import gpio_result


def _text(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require nonempty text.")
    return value


def _positive(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require a positive number.")
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise AgentError(
            ErrorCode.INVALID_ARGUMENT, "Require a finite positive number."
        ) from None
    if not math.isfinite(number) or number <= 0:
        raise AgentError(
            ErrorCode.INVALID_ARGUMENT, "Require a finite positive number."
        )
    return number


class MockBackend:
    name = "mock"
    requires_approval = False

    def build_firmware(self, project_path: str) -> OperationResult:
        def operation() -> dict[str, Any]:
            path = _text(project_path).rstrip("/\\")
            return {
                "artifact_path": path + "/Objects/firmware.hex",
                "compiler_log": "MOCK: 0 errors; no compiler was executed.",
            }

        return invoke(operation, backend=self.name)

    def flash_firmware(self, firmware_path: str) -> OperationResult:
        def operation() -> dict[str, Any]:
            path = _text(firmware_path)
            if not path.lower().endswith(".hex"):
                raise AgentError(
                    ErrorCode.INVALID_ARGUMENT, "Require a .hex firmware path."
                )
            return {
                "verified": True,
                "artifact_path": path,
                "remote_path": str(BoardPaths().firmware_path("mock_run")),
                "target": "STM32G431RBT6",
                "tool_log": "MOCK: programming, verification and reset simulated.",
            }

        return invoke(operation, backend=self.name)

    def read_target_log(self, duration_s: float) -> OperationResult:
        def operation() -> dict[str, Any]:
            duration = _positive(duration_s)
            if duration > 60:
                raise AgentError(
                    ErrorCode.INVALID_ARGUMENT,
                    "Log collection duration must not exceed 60 seconds.",
                )
            return {
                "duration_s": duration,
                "logs": [{"timestamp_ms": 0, "text": "MOCK: FW_BOOT_OK"}],
            }

        return invoke(operation, backend=self.name)

    def run_hardware_test(
        self, test_id: str, params: dict[str, Any],
    ) -> OperationResult:
        def operation() -> dict[str, Any]:
            if test_id != "gpio_period":
                raise AgentError(
                    ErrorCode.PL_TEST_UNAVAILABLE, "Unsupported mock test."
                )
            if not isinstance(params, dict):
                raise AgentError(
                    ErrorCode.INVALID_ARGUMENT, "Require a parameter dictionary."
                )
            return gpio_result(params, {"period_ms": 1001.4})

        return invoke(operation, backend=self.name)
