"""Non-secret deployment settings for build, flash and physical observations."""

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .config import BoardPaths
from .errors import AgentError, ErrorCode


@dataclass(frozen=True)
class PLObserverConfig:
    """Read-only access to the GPIO part of a prepared observation subsystem.

    ``prog_done`` proves configuration completion, not bitstream identity. The
    deployment owner must prepare the expected image; this reader never loads
    an FPGA or changes a register. Optional file hash checks validate the SD
    image only, and do not claim to identify the running FPGA configuration.
    """

    pl_clock_hz: int = 100_000_000
    observed_gpio: str = "PA1"
    period_addr: str = "0x43C30000"
    high_addr: str = "0x43C30008"
    edge_addr: str = "0x43C40000"
    valid_addr: str = "0x43C40008"
    busybox_path: str = "/bin/busybox"
    prog_done_path: str = "/sys/class/xdevcfg/xdevcfg/device/prog_done"
    bitstream: str | None = None
    bitstream_sha256: str | None = None
    prepare_policy: str = "check_only"
    bitstream_device: str = "/dev/xdevcfg"
    min_new_edges: int = 2
    poll_interval_s: float = 0.05
    timeout_s: float = 15
    transport_margin_s: float = 3
    monotonic_path: str = "/proc/uptime"

    def __post_init__(self):
        def invalid():
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Invalid PL observer configuration.")

        if type(self.pl_clock_hz) is not int or not 1 <= self.pl_clock_hz <= 1_000_000_000:
            invalid()
        if not isinstance(self.observed_gpio, str) or not re.fullmatch(r"P[A-K](?:[0-9]|1[0-5])", self.observed_gpio):
            invalid()
        if self.prepare_policy not in ("check_only", "load_verified") or self.bitstream_device != "/dev/xdevcfg":
            invalid()
        if type(self.min_new_edges) is not int or not 2 <= self.min_new_edges <= 1024:
            invalid()
        for value, lower, upper in ((self.poll_interval_s, 0.01, 1), (self.timeout_s, 0.1, 120),
                                    (self.transport_margin_s, 0.1, 10)):
            # Check bounds before float conversion, including arbitrarily large
            # JSON integers that math.isfinite cannot represent as a double.
            if type(value) not in (int, float) or not lower <= value <= upper or not math.isfinite(value):
                invalid()
        addresses = (self.period_addr, self.high_addr, self.edge_addr, self.valid_addr)
        for address in addresses:
            if not isinstance(address, str) or not re.fullmatch(r"0x[0-9a-fA-F]{8}", address):
                invalid()
            if int(address, 16) % 4:
                invalid()
        if len({int(value, 16) for value in addresses}) != len(addresses):
            invalid()
        for path in (self.busybox_path, self.prog_done_path, self.bitstream, self.monotonic_path):
            if path is not None and (not isinstance(path, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", path)
                                     or ".." in PurePosixPath(path).parts or path == "/"):
                invalid()
        if self.busybox_path is None or self.prog_done_path is None or self.monotonic_path is None:
            invalid()
        if (self.bitstream is None) != (self.bitstream_sha256 is None):
            invalid()
        if self.prepare_policy == "load_verified" and (self.bitstream is None or not self.bitstream.endswith(".bit")):
            invalid()
        if self.bitstream_sha256 is not None and (
            not isinstance(self.bitstream_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.bitstream_sha256)
        ):
            invalid()


@dataclass(frozen=True)
class UARTObserverConfig:
    """AXI Uartlite receive channel built into the known-good observation-v4.

    These fields describe hardware already configured by the bitstream; the
    reader does not change baud rate, pin routing, or STM32 initialization.
    """

    stm32_tx_gpio: str = "PA2"
    pl_rx_pin: str = "M17"
    baud_rate: int = 115200
    data_bits: int = 8
    parity: str = "none"
    stop_bits: int = 1
    rx_addr: str = "0x43C50000"
    status_addr: str = "0x43C50008"
    control_addr: str = "0x43C5000C"
    busybox_path: str = "/bin/busybox"
    prog_done_path: str = "/sys/class/xdevcfg/xdevcfg/device/prog_done"
    monotonic_path: str = "/proc/uptime"
    poll_interval_s: float = 0.01
    transport_margin_s: float = 3
    max_bytes: int = 1024

    def __post_init__(self):
        def invalid():
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Invalid UART observer configuration.")
        if not isinstance(self.stm32_tx_gpio, str) or not re.fullmatch(r"P[A-K](?:[0-9]|1[0-5])", self.stm32_tx_gpio):
            invalid()
        if not isinstance(self.pl_rx_pin, str) or not re.fullmatch(r"[A-Z]{1,2}[1-9][0-9]{0,2}", self.pl_rx_pin):
            invalid()
        if (type(self.baud_rate) is not int or self.baud_rate != 115200
                or type(self.data_bits) is not int or self.data_bits != 8
                or self.parity != "none" or type(self.stop_bits) is not int or self.stop_bits != 1):
            invalid()
        addresses = (self.rx_addr, self.status_addr, self.control_addr)
        if any(not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{8}", value)
               or int(value, 16) % 4 for value in addresses):
            invalid()
        if int(self.status_addr, 16) != int(self.rx_addr, 16) + 8 or int(self.control_addr, 16) != int(self.rx_addr, 16) + 12:
            invalid()
        for path in (self.busybox_path, self.prog_done_path, self.monotonic_path):
            if (not isinstance(path, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", path)
                    or ".." in PurePosixPath(path).parts or path == "/"):
                invalid()
        for value, lower, upper in ((self.poll_interval_s, .001, 1), (self.transport_margin_s, .1, 10)):
            if type(value) not in (int, float) or not lower <= value <= upper or not math.isfinite(value):
                invalid()
        if type(self.max_bytes) is not int or not 1 <= self.max_bytes <= 1024:
            invalid()


@dataclass(frozen=True)
class StatusIndicatorConfig:
    """Optional presentation-only LED bank; no arbitrary MMIO capability."""

    type: str = "axi_gpio_led_bar"
    data_addr: str = "0x43C60000"
    active_low: bool = True

    def __post_init__(self):
        if (self.type != "axi_gpio_led_bar" or not isinstance(self.data_addr, str)
                or self.data_addr.lower() != "0x43c60000" or type(self.active_low) is not bool):
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Invalid LED status indicator configuration.")


@dataclass(frozen=True)
class DeploymentConfig:
    allowed_roots: tuple[str, ...]
    keil_executable: str | None = None
    project_file: str | None = None
    target: str | None = None
    build_timeout_s: float = 120
    flash_timeout_s: float = 120
    host: str = "192.168.10.2"
    port: int = 22
    user: str = "root"
    known_hosts: str | None = None
    identity_file: str | None = None
    allow_legacy_rsa: bool = True
    legacy_scp: bool = True
    mount_root: str = "/sd"
    observer: PLObserverConfig | None = None
    uart_observer: UARTObserverConfig | None = None
    status_indicator: StatusIndicatorConfig | None = None

    def __post_init__(self):
        def invalid():
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Invalid deployment configuration.")

        if not isinstance(self.allowed_roots, tuple) or not self.allowed_roots:
            invalid()
        for root in self.allowed_roots:
            if not isinstance(root, str) or not Path(root).is_absolute():
                invalid()
        for value in (self.build_timeout_s, self.flash_timeout_s):
            try:
                valid = type(value) in (int, float) and math.isfinite(value) and 0 < value <= 1800
            except OverflowError:
                valid = False
            if not valid:
                invalid()
        if not isinstance(self.host, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", self.host):
            invalid()
        if not isinstance(self.user, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,31}", self.user):
            invalid()
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            invalid()
        if type(self.allow_legacy_rsa) is not bool or type(self.legacy_scp) is not bool:
            invalid()
        if self.observer is not None and not isinstance(self.observer, PLObserverConfig):
            invalid()
        if self.uart_observer is not None and not isinstance(self.uart_observer, UARTObserverConfig):
            invalid()
        if self.status_indicator is not None and not isinstance(self.status_indicator, StatusIndicatorConfig):
            invalid()
        if self.status_indicator is not None:
            # The write-only display bank must never alias an observation register.
            for config, names in ((self.observer, ("period_addr", "high_addr", "edge_addr", "valid_addr")),
                                  (self.uart_observer, ("rx_addr", "status_addr", "control_addr"))):
                if config is not None and any(int(getattr(config, name), 16) == 0x43C60000 for name in names):
                    invalid()
        if self.observer is not None and self.uart_observer is not None:
            period_regs = {int(getattr(self.observer, key), 16)
                           for key in ("period_addr", "high_addr", "edge_addr", "valid_addr")}
            if period_regs.intersection(int(getattr(self.uart_observer, key), 16)
                                        for key in ("rx_addr", "status_addr", "control_addr")):
                invalid()
        if not isinstance(self.mount_root, str) or not re.fullmatch(r"/[A-Za-z0-9_/-]+", self.mount_root):
            invalid()
        if self.mount_root == "/" or ".." in PurePosixPath(self.mount_root).parts:
            invalid()
        for value in (self.keil_executable, self.project_file, self.target, self.known_hosts, self.identity_file):
            if value is not None and (not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value)):
                invalid()
        for value in (self.keil_executable, self.known_hosts, self.identity_file):
            if value is not None and not Path(value).is_absolute():
                invalid()

    @property
    def board(self) -> BoardPaths:
        return BoardPaths(PurePosixPath(self.mount_root))

    def local_path(self, value: str) -> Path:
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid local path.")
        path = Path(value)
        if not path.is_absolute():
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require an absolute local path.")
        path = path.resolve()
        if not any(path.is_relative_to(Path(root).resolve()) for root in self.allowed_roots):
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Local path is outside deployment roots.")
        return path

    @classmethod
    def load(cls, filename: str) -> "DeploymentConfig":
        try:
            document = json.loads(Path(filename).read_text(encoding="utf-8-sig"))
            if not isinstance(document, dict) or not isinstance(document.get("allowed_roots"), list):
                raise ValueError()
            document["allowed_roots"] = tuple(document["allowed_roots"])
            if document.get("observer") is not None:
                if not isinstance(document["observer"], dict):
                    raise ValueError()
                document["observer"] = PLObserverConfig(**document["observer"])
            if document.get("uart_observer") is not None:
                if not isinstance(document["uart_observer"], dict):
                    raise ValueError()
                document["uart_observer"] = UARTObserverConfig(**document["uart_observer"])
            if document.get("status_indicator") is not None:
                if not isinstance(document["status_indicator"], dict):
                    raise ValueError()
                document["status_indicator"] = StatusIndicatorConfig(**document["status_indicator"])
            return cls(**document)
        except (OSError, ValueError, TypeError):
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Cannot load deployment JSON.") from None
