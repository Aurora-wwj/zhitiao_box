"""Shared results and exception handling for public operations."""

from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from .errors import AgentError, ErrorCode


@dataclass(frozen=True)
class OperationResult:
    success: bool
    error_code: str | None
    message: str
    backend: str
    duration_ms: int = 0
    contract_version: str = "0.2"
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        reserved = {
            "success", "error_code", "message", "backend",
            "duration_ms", "contract_version",
        }
        if reserved.intersection(self.data):
            raise AgentError(
                ErrorCode.INVALID_ARGUMENT,
                "Result data cannot overwrite common fields.",
            )
        if self.success != (self.error_code is None):
            raise AgentError(
                ErrorCode.INVALID_ARGUMENT,
                "Success and error_code are inconsistent.",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.data,
            "success": self.success,
            "error_code": self.error_code,
            "message": self.message,
            "backend": self.backend,
            "duration_ms": self.duration_ms,
            "contract_version": self.contract_version,
        }


def invoke(
    operation: Callable[[], dict[str, Any]],
    *,
    backend: str,
) -> OperationResult:
    """Capture failures without exposing raw exception messages."""
    started = perf_counter()
    data: dict[str, Any] = {}
    error: AgentError | None = None
    try:
        data = operation()
        if not isinstance(data, dict):
            raise AgentError(
                ErrorCode.INVALID_RESPONSE,
                "Operation returned an invalid result.",
            )
        # Validate payload fields inside the exception boundary.
        OperationResult(True, None, "Operation completed.", backend, data=data)
    except AgentError as exc:
        error = exc
    except TimeoutError:
        error = AgentError(ErrorCode.TIMEOUT, "Operation timed out.")
    except KeyboardInterrupt:
        error = AgentError(ErrorCode.CANCELLED, "Human cancelled the operation.")
    except OSError:
        error = AgentError(
            ErrorCode.NETWORK_UNREACHABLE,
            "An I/O or network operation failed.",
        )
    except Exception:
        error = AgentError(
            ErrorCode.INTERNAL_ERROR,
            "An unexpected operation error occurred.",
        )

    return OperationResult(
        success=error is None,
        error_code=error.code.value if error else None,
        message=str(error) if error else "Operation completed.",
        backend=backend,
        duration_ms=max(0, int((perf_counter() - started) * 1000)),
        data=({"status_code": error.status_code}
              if error and error.status_code is not None
              else {} if error else data),
    )
