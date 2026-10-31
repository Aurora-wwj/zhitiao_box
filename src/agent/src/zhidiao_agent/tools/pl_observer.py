"""One-SSH, read-only period reader with fresh physical evidence.

The remote script checks deployment readiness, waits for at least two new
edges, and brackets the register snapshot with the edge counter. No shell text
comes from the model. Counter wrap uses unsigned 32-bit modular arithmetic.
"""

import math
import re
import shlex
from dataclasses import asdict

from ..deployment import DeploymentConfig
from ..errors import AgentError, ErrorCode
from ..observations import gpio_result, number
from .commands import CommandRunner, ProcessRunner
from .ssh import ssh_command
from .remote import REGISTER_HELPER, clock_helper, interval_us


class PLPeriodReader:
    def validate_goal(self, params: dict, timeout_s: float) -> dict:
        """Pure capability check for this native uint32 PL acquisition path.

        Reserve one complete period for initial phase/coherent-read slack in
        addition to min_new_edges. Check the whole accepted tolerance band.
        A wrong or missing physical signal can still time out at runtime.
        """
        observer = self.config.observer
        if observer is None:
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Configure a PL observer deployment profile.")
        expected = gpio_result(params, {"period_ms": 1})["expected"]
        budget = min(number(timeout_s), number(observer.timeout_s))
        counter_max = 0xffffffff / observer.pl_clock_hz * 1000
        window_max = max(0, budget - observer.poll_interval_s) * 1000 / (observer.min_new_edges + 1)
        maximum = min(counter_max, window_max)
        if expected["period_ms"] + expected["tolerance_ms"] > maximum:
            raise AgentError(ErrorCode.INVALID_ARGUMENT,
                f"目标周期与容差上界超出当前 PL 观测能力：须不超过 {maximum:.3f} ms "
                f"（观测窗口 {budget:g} s）。请调整目标或部署配置后重新确认。")
        return {"max_period_ms": maximum, "observation_timeout_s": budget}

    def __init__(self, config: DeploymentConfig, *, runner: CommandRunner | None = None):
        self.config = config
        self.runner = runner if runner is not None else ProcessRunner()

    def _script(self, timeout_s: float) -> str:
        observer = self.config.observer
        if observer is None:
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Configure a PL observer deployment profile.")
        timeout = number(timeout_s)
        if timeout > 120:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "PL observation timeout must not exceed 120 seconds.")
        # The PC also applies a subprocess deadline. This finite board-side loop
        # prevents an abandoned SSH session from polling the registers forever.
        polls = max(1, math.ceil(timeout / observer.poll_interval_s))
        header = [
            "set -eu",
            "BB=" + shlex.quote(observer.busybox_path),
            "test -x \"$BB\" || exit 72",
            # Fail safely on a BusyBox build without the arithmetic width needed
            # for uint32 counters rather than accepting a bad wrap calculation.
            '[ "$((4294967295))" = "4294967295" ] || exit 72',
            "test -r " + shlex.quote(observer.prog_done_path) + " || exit 73",
            '[ "$("$BB" cat ' + shlex.quote(observer.prog_done_path) + ')" = "1" ] || exit 73',
        ]
        if observer.bitstream is not None:
            header.extend([
                "test -r " + shlex.quote(observer.bitstream) + " || exit 73",
                'image_sha=$("$BB" sha256sum < ' + shlex.quote(observer.bitstream) + ") || exit 73",
                "[ \"$image_sha\" = " + shlex.quote(observer.bitstream_sha256 + "  -") + " ] || exit 73",
            ])
        return ("\n".join(header) + "\n" + clock_helper(observer.monotonic_path)
                + REGISTER_HELPER + f'''
"$BB" usleep 0 || exit 72
started=$(clock_ms) || exit $?
deadline=$((started + {math.ceil(timeout * 1000)}))
edge_start=$(read_reg {observer.edge_addr}) || exit $?
i=0
while [ "$i" -lt {polls} ]; do
    now=$(clock_ms) || exit $?
    [ "$now" -ge "$started" ] || exit 74
    [ "$now" -lt "$deadline" ] || exit 75
    edge_before=$(read_reg {observer.edge_addr}) || exit $?
    delta=$(( (edge_before - edge_start) & 4294967295 ))
    valid=$(read_reg {observer.valid_addr}) || exit $?
    if [ "$delta" -ge {observer.min_new_edges} ] && [ "$delta" -lt 2147483648 ] && [ "$valid" -eq 1 ]; then
        period=$(read_reg {observer.period_addr}) || exit $?
        high=$(read_reg {observer.high_addr}) || exit $?
        valid_after=$(read_reg {observer.valid_addr}) || exit $?
        edge_after=$(read_reg {observer.edge_addr}) || exit $?
        if [ "$edge_before" -eq "$edge_after" ] && [ "$valid_after" -eq 1 ]; then
            now=$(clock_ms) || exit $?
            [ "$now" -lt "$deadline" ] || exit 75
            printf 'ZHIDIAO_PL_V1 %u %u %u %u %u %u\\n' "$edge_start" "$edge_before" "$edge_after" "$valid_after" "$period" "$high"
            exit 0
        fi
    fi
    i=$((i + 1))
    if [ "$i" -lt {polls} ]; then "$BB" usleep {interval_us(observer.poll_interval_s)} || exit 72; fi
done
exit 75''')

    def preview(self, timeout_s: float) -> dict:
        script = self._script(timeout_s)
        return {
            "observer": asdict(self.config.observer),
            "commands": [list(ssh_command(self.config) + (script,))],
            "observation_timeout_s": number(timeout_s),
            "timeout_s": number(timeout_s) + self.config.observer.transport_margin_s,
            "effects": "Read-only PL readiness and fresh period/high register observation over SSH; no bitstream loading.",
            "image_identity": "Deployment must prepare the configured observation image; prog_done and SD file hash do not identify the running image.",
        }

    def __call__(self, timeout_s: float) -> dict:
        preview = self.preview(timeout_s)
        outcome = self.runner.run(tuple(preview["commands"][0]), preview["timeout_s"])
        if outcome.returncode == 255:
            raise AgentError(ErrorCode.SSH_CONNECT_FAILED, "SSH authentication, host verification or connection failed.")
        if outcome.returncode == 75:
            raise AgentError(ErrorCode.TIMEOUT, "No fresh valid PL measurement within the observation budget.")
        if outcome.returncode in (72, 73, 126, 127):
            raise AgentError(ErrorCode.PL_TEST_UNAVAILABLE, "PL deployment, register tool or prepared observation image is unavailable.")
        if outcome.returncode != 0:
            raise AgentError(ErrorCode.INVALID_RESPONSE, "PL observer command failed or returned invalid register data.")
        match = re.fullmatch(r"ZHIDIAO_PL_V1 ([0-9]{1,10}) ([0-9]{1,10}) ([0-9]{1,10}) ([0-9]{1,10}) ([0-9]{1,10}) ([0-9]{1,10})", outcome.output.strip())
        if match is None:
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Cannot parse the PL register snapshot.")
        start, edge, edge_after, valid, period, high = (int(value) for value in match.groups())
        observer = self.config.observer
        fresh = (edge - start) & 0xFFFFFFFF
        if (any(value > 0xFFFFFFFF for value in (start, edge, edge_after, period, high)) or valid != 1
                or edge != edge_after or not observer.min_new_edges <= fresh < 0x80000000
                or period == 0 or high > period):
            raise AgentError(ErrorCode.INVALID_RESPONSE, "PL snapshot is stale, inconsistent or outside the valid measurement range.")
        return {
            "period_ms": period * 1000 / observer.pl_clock_hz,
            "high_ms": high * 1000 / observer.pl_clock_hz,
            "duty_cycle": high / period,
            "period_ticks": period, "high_ticks": high,
            "edge_start": start, "edge_end": edge, "fresh_edges": fresh,
            "valid": valid, "pl_clock_hz": observer.pl_clock_hz,
            "freshness_verified": True, "evidence_source": "real_pl",
        }
