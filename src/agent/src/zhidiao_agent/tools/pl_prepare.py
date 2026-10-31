"""Internal observation preparation, invoked only under a reviewed tool plan.

This is deliberately not a fifth HardwareBackend tool. ``load_verified`` has
hardware effects: the trusted caller must bind and approve ``preview()`` before
calling this provider. The provider cannot authorize its own execution.
"""

import math
import re
import shlex
from dataclasses import asdict
from pathlib import PurePosixPath

from ..deployment import DeploymentConfig
from ..errors import AgentError, ErrorCode
from ..observations import number
from .commands import CommandRunner, ProcessRunner
from .ssh import ssh_command
from .remote import interval_us


class PLPreparation:
    def __init__(self, config: DeploymentConfig, *, runner: CommandRunner | None = None):
        self.config = config
        self.runner = runner if runner is not None else ProcessRunner()

    @property
    def requires_loading(self) -> bool:
        if self.config.observer is None:
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Configure an observation deployment profile.")
        return self.config.observer.prepare_policy == "load_verified"

    def _script(self, timeout_s: float) -> str:
        observer = self.config.observer
        if observer is None:
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Configure an observation deployment profile.")
        timeout = number(timeout_s)
        if timeout > 120:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "PL preparation timeout must not exceed 120 seconds.")
        if observer.prepare_policy not in {"check_only", "load_verified"}:
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Unsupported PL preparation policy.")
        # Keep device writes narrowly scoped even if a trusted caller substitutes
        # a custom observer object rather than constructing PLObserverConfig.
        if observer.bitstream_device != "/dev/xdevcfg":
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Only the configured Zynq xdevcfg loader is supported.")
        image = observer.bitstream
        if image is not None:
            image_path = PurePosixPath(image)
            if (not image_path.is_relative_to(PurePosixPath(self.config.mount_root))
                    or image_path.suffix.lower() != ".bit" or ".." in image_path.parts):
                raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Observation image must be a .bit file under the SD deployment root.")
        if self.requires_loading and (image is None or observer.bitstream_sha256 is None):
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Loading requires an explicit approved bitstream and SHA-256.")
        lines = [
            "set -eu",
            "BB=" + shlex.quote(observer.busybox_path),
            "DONE=" + shlex.quote(observer.prog_done_path),
            'test -x "$BB" || exit 72',
            'test -r "$DONE" || exit 73',
        ]
        if image is not None:
            lines.extend([
                "IMAGE=" + shlex.quote(image),
                'test -f "$IMAGE" && test -r "$IMAGE" && ! test -L "$IMAGE" || exit 73',
                'image_sha=$("$BB" sha256sum < "$IMAGE") || exit 72',
                '[ "$image_sha" = ' + shlex.quote(observer.bitstream_sha256 + "  -") + ' ] || exit 76',
            ])
        if self.requires_loading:
            # BusyBox timeout encloses the shell that opens the FPGA device, so
            # both opening/writing are covered by its board-side process budget.
            # Unsupported BusyBox builds fail closed rather than doing an
            # unbounded write. No password, boot-image or register writes occur.
            polls = max(1, math.ceil(timeout / observer.poll_interval_s))
            lines.extend([
                '"$BB" usleep 0 >/dev/null 2>&1 || exit 72',
                '"$BB" timeout --help > /dev/null 2>&1 || exit 72',
                'started=$("$BB" date +%s) || exit 72',
                'case "$started" in ""|*[!0123456789]*) exit 72 ;; esac',
                "deadline=$((started + " + str(math.ceil(timeout)) + "))",
                "DEVICE=" + shlex.quote(observer.bitstream_device),
                'test -c "$DEVICE" && test -w "$DEVICE" || exit 73',
                # Recheck immediately before writing, after all preflight work.
                'image_sha=$("$BB" sha256sum < "$IMAGE") || exit 72',
                '[ "$image_sha" = ' + shlex.quote(observer.bitstream_sha256 + "  -") + ' ] || exit 76',
                'now=$("$BB" date +%s) || exit 72',
                'case "$now" in ""|*[!0123456789]*) exit 72 ;; esac',
                'remaining=$((deadline - now))',
                '[ "$remaining" -gt 0 ] || exit 75',
                'status=0',
                '''"$BB" timeout -s KILL "$remaining" "$BB" sh -c '"$1" cat "$2" > "$3"' sh "$BB" "$IMAGE" "$DEVICE" || status=$?''',
                'case "$status" in 0) ;; 124|137|143) exit 75 ;; *) exit 77 ;; esac',
                "i=0",
                'while [ "$i" -lt ' + str(polls) + ' ]; do',
                '    done_value=$("$BB" cat "$DONE") || exit 73',
                '    if [ "$done_value" = "1" ]; then',
                "        printf 'ZHIDIAO_PREP_V1 LOADED " + observer.bitstream_sha256 + " 1\\n'",
                "        exit 0",
                "    fi",
                '    [ "$done_value" = "0" ] || exit 74',
                '    now=$("$BB" date +%s) || exit 72',
                '    case "$now" in ""|*[!0123456789]*) exit 72 ;; esac',
                '    [ "$now" -lt "$deadline" ] || exit 75',
                "    i=$((i + 1))",
                '    if [ "$i" -lt ' + str(polls) + ' ]; then "$BB" usleep ' + str(interval_us(observer.poll_interval_s)) + ' || exit 72; fi',
                "done",
                "exit 75",
            ])
        else:
            lines.extend([
                'done_value=$("$BB" cat "$DONE") || exit 73',
                '[ "$done_value" = "1" ] || exit 73',
                "printf 'ZHIDIAO_PREP_V1 CHECKED " + (observer.bitstream_sha256 or "-") + " 1\\n'",
            ])
        return "\n".join(lines)

    def preview(self, timeout_s: float) -> dict:
        script = self._script(timeout_s)
        return {
            "observer": asdict(self.config.observer),
            "policy": self.config.observer.prepare_policy,
            "requires_loading": self.requires_loading,
            "commands": [list(ssh_command(self.config) + (script,))],
            "timeout_s": number(timeout_s),
            "effects": (
                "Verify the approved SD image SHA-256, replace the running FPGA configuration through /dev/xdevcfg, "
                "then require prog_done=1 before UART/PL observation. This resets the observation subsystem."
                if self.requires_loading else
                "Read-only check of prepared PL readiness and optional SD image SHA-256; no image loading."
            ),
            "image_identity": (
                "The approved file is loaded in this operation; prog_done confirms configuration completion, not hardware attestation."
                if self.requires_loading else
                "External deployment must prepare the configured observation image; prog_done and SD file hash do not identify the running image."
            ),
        }

    def __call__(self, timeout_s: float) -> dict:
        preview = self.preview(timeout_s)
        outcome = self.runner.run(tuple(preview["commands"][0]), preview["timeout_s"])
        codes = {
            255: (ErrorCode.SSH_CONNECT_FAILED, "SSH authentication, host verification or connection failed."),
            75: (ErrorCode.TIMEOUT, "PL preparation exceeded its time budget."),
            72: (ErrorCode.PL_TEST_UNAVAILABLE, "Required PL preparation tools are unavailable."),
            73: (ErrorCode.PL_TEST_UNAVAILABLE, "PL image, loader device or readiness path is unavailable."),
            76: (ErrorCode.PL_TEST_UNAVAILABLE, "Observation image SHA-256 does not match the approved deployment image."),
            77: (ErrorCode.PL_TEST_UNAVAILABLE, "Observation FPGA loading did not complete successfully."),
            126: (ErrorCode.PL_TEST_UNAVAILABLE, "Required PL preparation executable is unavailable."),
            127: (ErrorCode.PL_TEST_UNAVAILABLE, "Required PL preparation executable is unavailable."),
        }
        if outcome.returncode in codes:
            code, message = codes[outcome.returncode]
            raise AgentError(code, message)
        if outcome.returncode != 0:
            raise AgentError(ErrorCode.INVALID_RESPONSE, "PL preparation returned invalid readiness data.")
        match = re.fullmatch(r"ZHIDIAO_PREP_V1 (CHECKED|LOADED) ([0-9a-f]{64}|-) 1", outcome.output.strip())
        expected_mode = "LOADED" if self.requires_loading else "CHECKED"
        expected_sha = self.config.observer.bitstream_sha256 or "-"
        if match is None or match.group(1) != expected_mode or match.group(2) != expected_sha:
            raise AgentError(ErrorCode.INVALID_RESPONSE, "PL preparation evidence does not match the reviewed policy and image.")
        return {"prepared": True, "loaded": self.requires_loading, "policy": preview["policy"],
                "image_sha256": self.config.observer.bitstream_sha256, "prog_done": 1,
                "running_image_identity": "approved_file_loaded" if self.requires_loading else "not_verified"}
