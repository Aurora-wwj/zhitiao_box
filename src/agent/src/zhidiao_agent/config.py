"""Explicit API settings and SD deployment contract v0.1."""

import math
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from .errors import AgentError, ErrorCode

NICECODE_BASE_URL = "https://api.nicecode.ai/v1"
NICECODE_MODEL = "gpt-5-codex"


@dataclass(frozen=True)
class NiceCodeConfig:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    timeout_s: float = 30.0

    def __post_init__(self) -> None:
        try:
            url = urlsplit(self.base_url)
            # Accessing port validates malformed and out-of-range port values.
            port = url.port
            valid_url = (
                url.scheme == "https"
                and bool(url.hostname)
                and url.username is None
                and url.password is None
                and not url.query
                and not url.fragment
                and (port is None or 1 <= port <= 65535)
                and not any(ord(char) <= 32 or ord(char) == 127 for char in self.base_url)
            )
            valid_timeout = (
                not isinstance(self.timeout_s, bool)
                and math.isfinite(self.timeout_s)
                and self.timeout_s > 0
            )
            valid = (
                valid_url
                and bool(self.model.strip())
                and bool(self.api_key.strip())
                and not any(ord(char) < 32 or ord(char) == 127 for char in self.api_key)
                and valid_timeout
            )
        except (TypeError, ValueError, AttributeError, OverflowError):
            valid = False
        if not valid:
            raise AgentError(
                ErrorCode.CONFIGURATION_ERROR,
                "Require an HTTPS API URL, model, API key and positive timeout.",
            )


@dataclass(frozen=True)
class BoardPaths:
    """Remote POSIX paths; never interpret these as PC-local paths."""

    mount_root: PurePosixPath = PurePosixPath("/sd")

    def __post_init__(self) -> None:
        if (
            not isinstance(self.mount_root, PurePosixPath)
            or not self.mount_root.is_absolute()
            or ".." in self.mount_root.parts
        ):
            raise AgentError(
                ErrorCode.CONFIGURATION_ERROR, "Require an absolute remote root."
            )

    @property
    def openocd_bin(self) -> PurePosixPath:
        return self.mount_root / "tools/openocd/bin/openocd"

    @property
    def openocd_scripts(self) -> PurePosixPath:
        return self.mount_root / "tools/openocd/share/openocd/scripts"

    @property
    def log_root(self) -> PurePosixPath:
        return self.mount_root / "logs"

    def firmware_path(self, run_id: str) -> PurePosixPath:
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid run_id.")
        return self.mount_root / "firmware" / run_id / "firmware.hex"
