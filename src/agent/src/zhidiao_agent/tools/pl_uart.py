"""One-SSH AXI Uartlite capture with an explicitly approved FIFO reset.

    Remote timestamps use /proc/uptime, not a poll counter. They describe when
    bytes were drained, not an unavailable hardware timestamp of wire arrival.
"""

import math
import re
import shlex
from dataclasses import asdict

from ..deployment import DeploymentConfig
from ..errors import AgentError, ErrorCode
from ..observations import number
from .commands import CommandRunner, ProcessRunner
from .remote import REGISTER_HELPER, clock_helper, interval_us
from .ssh import ssh_command


def _decode(raw: bytes) -> tuple[str, int]:
    """Count actual UTF-8 decoding failures, not valid U+FFFD characters."""
    pieces, errors = [], 0
    while raw:
        try:
            pieces.append(raw.decode("utf-8"))
            break
        except UnicodeDecodeError as exc:
            pieces.extend((raw[:exc.start].decode("utf-8"), "\ufffd"))
            errors += 1
            raw = raw[exc.end:]
    return "".join(pieces), errors


class PLUARTReader:
    def __init__(self, config: DeploymentConfig, *, runner: CommandRunner | None = None):
        self.config = config
        self.runner = runner if runner is not None else ProcessRunner()

    def preview(self, duration_s: float, timeout_s: float) -> dict:
        uart = self.config.uart_observer
        if uart is None:
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Configure the independent UART observer.")
        duration, budget = number(duration_s), number(timeout_s)
        if duration > 60:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Capture duration must not exceed 60 seconds.")
        hard_timeout = min(budget, duration + uart.transport_margin_s)
        if hard_timeout <= duration:
            raise AgentError(ErrorCode.TIMEOUT, "Insufficient transport budget for this UART capture.")
        return {"uart_observer": asdict(uart), "duration_s": duration,
                "timeout_s": hard_timeout, "commands": [list(ssh_command(self.config) + (self._script(duration),))],
                "effects": "Reset UART RX FIFO once at the start of this approved capture to exclude stale bytes; drain only this UART channel. No bitstream loading or firmware changes.",
                "fifo_reset": {"address": uart.control_addr, "value": "0x00000002"},
                "timestamp_basis": "board_monotonic_capture_elapsed_ms"}

    def _script(self, duration_s: float) -> str:
        uart = self.config.uart_observer
        header = ["set -eu", "BB=" + shlex.quote(uart.busybox_path),
                  'test -x "$BB" || exit 72',
                  '[ "$((4294967295))" = "4294967295" ] || exit 72',
                  "test -r " + shlex.quote(uart.prog_done_path) + " || exit 73",
                  '[ "$("$BB" cat ' + shlex.quote(uart.prog_done_path) + ')" = "1" ] || exit 73']
        if self.config.observer is not None and self.config.observer.bitstream is not None:
            observer = self.config.observer
            header.extend(["test -r " + shlex.quote(observer.bitstream) + " || exit 73",
                           'image_sha=$("$BB" sha256sum < ' + shlex.quote(observer.bitstream) + ') || exit 72',
                           '[ "$image_sha" = ' + shlex.quote(observer.bitstream_sha256 + "  -") + ' ] || exit 73'])
        return ("\n".join(header) + "\n" + clock_helper(uart.monotonic_path) + REGISTER_HELPER + f'''
"$BB" usleep 0 || exit 72
clock_ms > /dev/null || exit $?
# Read old sticky health flags before clearing the old RX session.
read_reg {uart.status_addr} > /dev/null || exit $?
"$BB" devmem {uart.control_addr} 32 0x00000002 > /dev/null || exit 72
started=$(clock_ms) || exit $?
deadline=$((started + {math.ceil(duration_s * 1000)}))
count=0
overflow=0
frame=0
parity=0
limited=0
iterations=0
printf 'ZHIDIAO_UART_V1\\n'
while [ "$iterations" -lt {math.ceil(duration_s / uart.poll_interval_s) + uart.max_bytes + 2} ]; do
    iterations=$((iterations + 1))
    now=$(clock_ms) || exit $?
    [ "$now" -ge "$started" ] || exit 74
    [ "$now" -lt "$deadline" ] || break
    status=$(read_reg {uart.status_addr}) || exit $?
    [ "$((status & 32))" -eq 0 ] || overflow=1
    [ "$((status & 64))" -eq 0 ] || frame=1
    [ "$((status & 128))" -eq 0 ] || parity=1
    if [ "$((status & 1))" -eq 1 ]; then
        value=$(read_reg {uart.rx_addr}) || exit $?
        [ "$value" -le 255 ] || exit 74
        now=$(clock_ms) || exit $?
        [ "$now" -ge "$started" ] || exit 74
        # A byte drained at/after the exclusive deadline is outside this window,
        # not a capacity failure. Do not extend capture waiting for a newline.
        if [ "$now" -ge "$deadline" ]; then break; fi
        printf 'B %u %02X\\n' "$((now - started))" "$value"
        count=$((count + 1))
        if [ "$count" -ge {uart.max_bytes} ]; then limited=1; break; fi
        # Immediately drain the next byte; sleep only once RX is empty.
    else
        "$BB" usleep {interval_us(uart.poll_interval_s)} || exit 72
    fi
done
now=$(clock_ms) || exit $?
[ "$now" -ge "$started" ] || exit 74
[ "$limited" -eq 1 ] || [ "$now" -ge "$deadline" ] || exit 75
printf 'E %u %u %u %u %u %u\\n' "$((now - started))" "$count" "$overflow" "$frame" "$parity" "$limited"
''')

    def __call__(self, duration_s: float, timeout_s: float) -> dict:
        preview = self.preview(duration_s, timeout_s)
        outcome = self.runner.run(tuple(preview["commands"][0]), preview["timeout_s"])
        if outcome.returncode == 255:
            raise AgentError(ErrorCode.SSH_CONNECT_FAILED, "SSH authentication, host verification or connection failed.")
        if outcome.returncode == 75:
            raise AgentError(ErrorCode.TIMEOUT, "UART capture could not complete its monotonic observation window.")
        if outcome.returncode in (72, 73, 126, 127):
            raise AgentError(ErrorCode.UART_READ_FAILED, "UART registers, readiness, monotonic clock or BusyBox applets are unavailable.")
        if outcome.returncode != 0:
            raise AgentError(ErrorCode.INVALID_RESPONSE, "UART capture failed or returned malformed register data.")
        lines = outcome.output.splitlines()
        if len(lines) < 2 or lines[0] != "ZHIDIAO_UART_V1":
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid UART capture envelope.")
        end = re.fullmatch(r"E ([0-9]{1,8}) ([0-9]{1,4}) ([01]) ([01]) ([01]) ([01])", lines[-1])
        if end is None:
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Missing UART capture completion evidence.")
        elapsed, count, overflow, frame, parity, limited = map(int, end.groups())
        duration_ms = math.ceil(number(duration_s) * 1000)
        if (count != len(lines) - 2 or count > self.config.uart_observer.max_bytes
                or elapsed > math.ceil(preview["timeout_s"] * 1000)
                or (not limited and elapsed < duration_ms)):
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Inconsistent UART capture count or duration.")
        logs, pending = [], bytearray()
        previous, decoding_errors = 0, 0
        for line in lines[1:-1]:
            match = re.fullmatch(r"B ([0-9]{1,8}) ([0-9A-F]{2})", line)
            if match is None:
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid timestamped UART byte.")
            timestamp, value = int(match[1]), int(match[2], 16)
            if not previous <= timestamp <= min(elapsed, duration_ms):
                raise AgentError(ErrorCode.INVALID_RESPONSE, "UART timestamps are outside the capture window.")
            previous = timestamp
            if value == 10:
                text, errors = _decode(bytes(pending).removesuffix(b"\r"))
                logs.append({"timestamp_ms": timestamp, "text": text})
                decoding_errors += errors
                pending.clear()
            else:
                pending.append(value)
        if pending:
            text, errors = _decode(bytes(pending))
            logs.append({"timestamp_ms": previous, "text": text})
            decoding_errors += errors
        # Missing LF at a normal deadline is a partial observation, not dropped
        # capture evidence. Keep the tail and reserve truncated for real limits.
        # Also fail closed if an envelope omits its limit bit at the byte cap.
        limit_hit = bool(limited or count >= self.config.uart_observer.max_bytes)
        return {"logs": logs, "overflow": bool(overflow), "truncated": limit_hit,
                "partial_tail": bool(pending),
                "capture_end_reason": "capture_limit" if limit_hit else "deadline",
                "decoding_errors": decoding_errors, "frame_errors": frame, "parity_errors": parity,
                "bytes_captured": count, "capture_elapsed_ms": elapsed, "fifo_reset": True,
                "timestamp_basis": preview["timestamp_basis"]}
