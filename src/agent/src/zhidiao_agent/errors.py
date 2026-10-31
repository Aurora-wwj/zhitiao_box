"""Stable error codes shared by public API boundaries."""

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    NETWORK_UNREACHABLE = "NETWORK_UNREACHABLE"
    SERVICE_ERROR = "SERVICE_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    BUILD_FAILED = "BUILD_FAILED"
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    SSH_CONNECT_FAILED = "SSH_CONNECT_FAILED"
    FLASH_PROGRAM_FAILED = "FLASH_PROGRAM_FAILED"
    FLASH_VERIFY_FAILED = "FLASH_VERIFY_FAILED"
    TARGET_RESET_FAILED = "TARGET_RESET_FAILED"
    UART_READ_FAILED = "UART_READ_FAILED"
    PL_TEST_UNAVAILABLE = "PL_TEST_UNAVAILABLE"


class AgentError(Exception):
    """A sanitized error safe to return to callers.

    Do not put API keys, authorization headers, raw response bodies,
    or unfiltered transport exceptions into the message.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
