"""Approved Keil/SSH operations and separately injected physical observations."""

import re
import copy
import shlex
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from ..approval import ApprovalGate
from ..deployment import DeploymentConfig
from ..errors import AgentError, ErrorCode
from ..models import OperationResult, invoke
from ..observations import ObservationBackend, gpio_result, number
from .artifacts import file_digest, keil_target, source_digest, validate_hex
from .commands import CommandRunner, ProcessRunner, sanitized_log
from .ssh import ssh_options
from .pl_observer import PLPeriodReader
from .pl_prepare import PLPreparation
from .pl_uart import PLUARTReader


@dataclass(frozen=True)
class _Plan:
    proposal_id: str
    action: str
    path: str
    params: dict[str, Any]
    commands: tuple[tuple[str, ...], ...]


class RealBackend:
    requires_approval = True

    def __init__(
        self, config: DeploymentConfig | None = None, *,
        runner: CommandRunner | None = None, approvals: ApprovalGate | None = None,
        observations: ObservationBackend | None = None,
    ):
        self.config = config
        # One backend instance belongs to one deployment. Reusing an instance
        # after replacing its config must never flash one board and measure a
        # reader that still points at another board. Construct a new backend to
        # select a new deployment and obtain new previews/approvals.
        self._initial_config = config
        self.observations = observations
        self.runner = runner if runner is not None else ProcessRunner()
        if self.observations is None and config is not None and (config.observer is not None or config.uart_observer is not None):
            self.observations = ObservationBackend(
                period_reader=PLPeriodReader(config, runner=self.runner) if config.observer is not None else None,
                uart_reader=PLUARTReader(config, runner=self.runner) if config.uart_observer is not None else None,
                timeout_s=config.observer.timeout_s if config.observer is not None else 15,
            )
        self.approvals = approvals if approvals is not None else ApprovalGate()
        self.name = "real_keil_zynq" if config else "real_unconfigured"
        self._plans: dict[tuple[str, str], _Plan] = {}
        # Set only by the deterministic reviewed Controller during one cycle.
        self.execution_deadline: float | None = None
        self._preparation_plan: tuple[dict, dict] | None = None
        self._preparation_result: dict | None = None
        self._uart_capture_plan: tuple[dict, dict] | None = None

    def _budget(self, maximum: float) -> float:
        budget = number(maximum)
        if self.execution_deadline is not None:
            budget = min(budget, self.execution_deadline - time.monotonic())
        if budget <= 0:
            raise AgentError(ErrorCode.TIMEOUT, "Reviewed execution time budget exhausted.")
        return budget

    def _configured(self) -> DeploymentConfig:
        if self.config != self._initial_config:
            raise AgentError(
                ErrorCode.APPROVAL_REQUIRED,
                "Deployment changed; create a new backend and review its operations.",
            )
        if self.config is None:
            raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "Real hardware backend has not been configured.")
        if self.observations is not None:
            for reader in (self.observations.period_reader, self.observations.uart_reader):
                if isinstance(reader, (PLPeriodReader, PLUARTReader)) and (
                    reader.config != self.config or reader.runner is not self.runner
                ):
                    raise AgentError(ErrorCode.APPROVAL_REQUIRED,
                                     "Observation reader does not match the selected deployment and transport; create a new backend.")
        return self.config

    def _save(self, action: str, path: Path, params: dict, commands: tuple) -> dict:
        params = {**params, "deployment": asdict(self._configured())}
        preview = self.approvals.propose(action, params)
        if not preview.success:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Cannot prepare approval preview.")
        self._plans[(action, str(path))] = _Plan(
            preview.data["proposal_id"], action, str(path), params, commands,
        )
        return preview.data

    def preview_build(self, project_path: str) -> OperationResult:
        def operation():
            config = self._configured()
            project = config.local_path(project_path)
            if not config.keil_executable or not Path(config.keil_executable).is_file():
                raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Configure an existing Keil executable.")
            project_file, target, artifact = keil_target(project, config)
            log = project / ("keil_build_" + uuid.uuid4().hex + ".log")
            command = (config.keil_executable, "-r", str(project_file), "-t", target, "-o", str(log))
            params = {
                "project_path": str(project), "project_file": str(project_file),
                "target": target, "artifact_path": str(artifact), "log_path": str(log),
                "source_sha256": source_digest(project),
                "commands": [list(command)], "timeout_s": config.build_timeout_s,
                "effects": "Rebuild the trusted Keil project; write compiler outputs and a build log.",
            }
            return self._save("build_firmware", project, params, (command,))
        return invoke(operation, backend=self.name)

    def _take(self, action: str, value: str) -> _Plan:
        path = self._configured().local_path(value)
        plan = self._plans.pop((action, str(path)), None)
        if plan is None:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Preview and approve this operation first.")
        if plan.params["deployment"] != asdict(self._configured()):
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Deployment changed; create and approve a new preview.")
        digest = source_digest(path) if action == "build_firmware" else validate_hex(path)
        expected = plan.params["source_sha256" if action == "build_firmware" else "firmware_sha256"]
        if digest != expected:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Inputs changed; create and approve a new preview.")
        permission = self.approvals.consume(plan.proposal_id, action, plan.params)
        if not permission.success:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Explicit human approval is required.")
        return plan

    def build_firmware(self, project_path: str) -> OperationResult:
        details: dict[str, Any] = {}

        def operation():
            config = self._configured()
            plan = self._take("build_firmware", project_path)
            artifact = Path(plan.params["artifact_path"])
            log_path = Path(plan.params["log_path"])
            if log_path.exists() or log_path.is_symlink():
                raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Build log path is already occupied; preview again.")
            before = ((artifact.stat().st_mtime_ns, file_digest(artifact)) if artifact.is_file() else None)
            result = self.runner.run(plan.commands[0], self._budget(plan.params["timeout_s"]))
            self._budget(plan.params["timeout_s"])
            if log_path.is_symlink() or not log_path.is_file() or log_path.stat().st_size > 8 * 1024 * 1024:
                raise AgentError(ErrorCode.BUILD_FAILED, "Keil did not produce a readable build log.")
            raw = log_path.read_bytes()
            try:
                log = raw.decode("utf-8-sig")
            except UnicodeError:
                log = raw.decode("gb18030", errors="replace")
            details["compiler_log"] = sanitized_log(log)
            summaries = re.findall(r"(\d+)\s+Error\(s\)", log, re.I)
            if result.returncode not in (0, 1) or not summaries or any(int(n) for n in summaries):
                raise AgentError(ErrorCode.BUILD_FAILED, "Keil reported compilation errors or an invalid exit status.")
            if not artifact.is_file():
                raise AgentError(ErrorCode.ARTIFACT_NOT_FOUND, "Keil did not generate the configured HEX artifact.")
            resolved = config.local_path(str(artifact))
            if not resolved.is_relative_to(Path(plan.path)):
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Build artifact escaped the selected project.")
            digest = validate_hex(artifact)
            if before == (artifact.stat().st_mtime_ns, digest):
                raise AgentError(ErrorCode.ARTIFACT_NOT_FOUND, "HEX artifact was not refreshed by this build.")
            return {"artifact_path": str(artifact), "artifact_sha256": digest, **details}

        result = invoke(operation, backend=self.name)
        return replace(result, data={**result.data, **details})

    def _ssh_options(self, config: DeploymentConfig) -> tuple[str, ...]:
        return ssh_options(config)

    def preview_flash(self, firmware_path: str) -> OperationResult:
        def operation():
            config = self._configured()
            firmware = config.local_path(firmware_path)
            digest = validate_hex(firmware)
            options = self._ssh_options(config)
            run_id = "run_" + uuid.uuid4().hex
            remote = config.board.firmware_path(run_id)
            destination = config.user + "@" + config.host
            ssh = ("ssh", *options, "-p", str(config.port), destination)
            scp = ("scp", *(("-O",) if config.legacy_scp else ()), *options, "-P", str(config.port))
            board = config.board
            preflight = " && ".join([
                "command -v sha256sum > /dev/null",
                shlex.join(("test", "-x", str(board.openocd_bin))),
                shlex.join(("test", "-r", str(board.openocd_scripts / "interface/stlink.cfg"))),
                shlex.join(("test", "-r", str(board.openocd_scripts / "target/stm32g4x.cfg"))),
                shlex.join(("mkdir", str(remote.parent))),
            ])
            check = shlex.join(("test", "-s", str(remote))) + " && wc -c < " + shlex.quote(str(remote))
            checksum = "sha256sum < " + shlex.quote(str(remote))
            openocd = shlex.join((
                str(board.openocd_bin), "-s", str(board.openocd_scripts),
                "-f", "interface/stlink.cfg", "-f", "target/stm32g4x.cfg",
                "-c", f"program {remote} verify reset exit",
            ))
            commands = (ssh + (preflight,), scp + (str(firmware), destination + ":" + str(remote)),
                        ssh + (check,), ssh + (checksum,), ssh + (openocd,))
            params = {
                "artifact_path": str(firmware), "firmware_sha256": digest,
                "firmware_bytes": firmware.stat().st_size, "run_id": run_id,
                "remote_path": str(remote), "target": "STM32G431RBT6",
                "commands": [list(command) for command in commands],
                "timeout_s": config.flash_timeout_s,
                "effects": "Upload firmware, verify remote SHA-256, then program/verify/reset STM32; do not modify Zynq boot files.",
            }
            return self._save("flash_firmware", firmware, params, commands)
        return invoke(operation, backend=self.name)

    def flash_firmware(self, firmware_path: str) -> OperationResult:
        details: dict[str, Any] = {}

        def operation():
            config = self._configured()
            plan = self._take("flash_firmware", firmware_path)
            details.update({key: plan.params[key] for key in ("artifact_path", "remote_path", "run_id", "target")})
            details["verified"] = False
            details["upload_verified"] = False
            details["artifact_sha256"] = plan.params["firmware_sha256"]
            deadline = time.monotonic() + plan.params["timeout_s"]
            if self.execution_deadline is not None:
                deadline = min(deadline, self.execution_deadline)
            logs: list[str] = []
            for index, command in enumerate(plan.commands):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AgentError(ErrorCode.TIMEOUT, "Flash operation exceeded its total time budget.")
                if validate_hex(Path(plan.path)) != plan.params["firmware_sha256"]:
                    raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Firmware changed; flashing stopped.")
                result = self.runner.run(command, remaining)
                if time.monotonic() >= deadline:
                    raise AgentError(ErrorCode.TIMEOUT, "Flash operation exceeded its total time budget.")
                log = sanitized_log(result.output)
                logs.append(log)
                details["tool_log"] = sanitized_log("\n".join(logs))
                if result.returncode == 255:
                    raise AgentError(ErrorCode.SSH_CONNECT_FAILED, "SSH authentication, host verification or connection failed.")
                if index < 4:
                    if result.returncode != 0:
                        raise AgentError(ErrorCode.UPLOAD_FAILED, "Remote preflight, upload or upload check failed.")
                    if index == 2 and log.strip() != str(plan.params["firmware_bytes"]):
                        raise AgentError(ErrorCode.UPLOAD_FAILED, "Remote firmware size does not match the local artifact.")
                    if index == 3:
                        # Read from stdin so GNU/BusyBox output names the input '-'.
                        # Reject extra lines, wrong filenames, and non-SHA256 digests.
                        match = re.fullmatch(r"([0-9a-fA-F]{64})[ \t]+\*?-", log.strip())
                        if match is None:
                            raise AgentError(ErrorCode.UPLOAD_FAILED, "Cannot parse the remote firmware SHA-256.")
                        details["remote_sha256"] = match.group(1).lower()
                        if details["remote_sha256"] != plan.params["firmware_sha256"]:
                            raise AgentError(ErrorCode.UPLOAD_FAILED, "Remote firmware SHA-256 does not match the approved artifact.")
                        details["upload_verified"] = True
                    continue
                if result.returncode != 0 or "Programming Finished" not in log:
                    raise AgentError(ErrorCode.FLASH_PROGRAM_FAILED, "OpenOCD programming did not complete successfully.")
                if "Verified OK" not in log:
                    raise AgentError(ErrorCode.FLASH_VERIFY_FAILED, "OpenOCD did not confirm firmware verification.")
                if "Resetting Target" not in log:
                    raise AgentError(ErrorCode.TARGET_RESET_FAILED, "OpenOCD did not confirm target reset.")
                details["verified"] = True
            return details

        result = invoke(operation, backend=self.name)
        return replace(result, data={**result.data, **details})

    def read_target_log(self, duration_s: float) -> OperationResult:
        return self._observe("read_target_log", duration_s)

    def run_hardware_test(self, test_id: str, params: dict[str, Any]) -> OperationResult:
        return self._observe("run_hardware_test", test_id, params)

    def _begin_observation_cycle(self):
        """Reset internal preparation only at a trusted, newly approved cycle."""
        if self._preparation_plan is not None:
            preview, params = self._preparation_plan
            self.approvals.decide(preview["proposal_id"], preview["fingerprint"], approved=False)
            self.approvals.consume(preview["proposal_id"], "prepare_observation", params)
        self._preparation_plan = None
        self._preparation_result = None
        if self._uart_capture_plan is not None:
            preview, params = self._uart_capture_plan
            self.approvals.decide(preview["proposal_id"], preview["fingerprint"], approved=False)
            self.approvals.consume(preview["proposal_id"], "capture_uart", params)
        self._uart_capture_plan = None

    def _uart_capture_params(self, duration_s):
        config = self._configured()
        return {"deployment": asdict(config),
                "capture": self.observations.uart_reader.preview(
                    duration_s, duration_s + number(self.observations.timeout_s))}

    def _preview_uart_capture(self, duration_s: float) -> OperationResult:
        """Internal single-use permission for the declared FIFO-reset effect."""
        def operation():
            self._configured()
            if self.observations is None or not isinstance(self.observations.uart_reader, PLUARTReader):
                return {"required": False}
            params = self._uart_capture_params(duration_s)
            preview = self.approvals.propose("capture_uart", params)
            if not preview.success:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Cannot preview UART capture authorization.")
            if self._uart_capture_plan is not None:
                old, old_params = self._uart_capture_plan
                self.approvals.decide(old["proposal_id"], old["fingerprint"], approved=False)
                self.approvals.consume(old["proposal_id"], "capture_uart", old_params)
            self._uart_capture_plan = (copy.deepcopy(preview.data), copy.deepcopy(params))
            return preview.data
        return invoke(operation, backend=self.name)

    def _consume_uart_capture(self, duration_s):
        if not isinstance(self.observations.uart_reader, PLUARTReader):
            return
        plan, self._uart_capture_plan = self._uart_capture_plan, None
        if plan is None:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "UART FIFO reset requires a reviewed capture session.")
        preview, expected = plan
        if self._uart_capture_params(duration_s) != expected:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "UART capture changed after review.")
        result = self.approvals.consume(preview["proposal_id"], "capture_uart", expected)
        if not result.success:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "UART capture requires human authorization.")

    def _preview_preparation(self) -> OperationResult:
        """Internal child authorization; never expose as a model tool."""
        def operation():
            config = self._configured()
            if config.observer is None or config.observer.prepare_policy != "load_verified":
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "No FPGA loading is selected.")
            if self.observations is None:
                raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "Observation is not configured.")
            self._begin_observation_cycle()
            params = {"deployment": asdict(config),
                      "preparation": PLPreparation(config, runner=self.runner).preview(self.observations.timeout_s)}
            preview = self.approvals.propose("prepare_observation", params)
            if not preview.success:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Cannot prepare FPGA loading approval.")
            self._preparation_plan = (copy.deepcopy(preview.data), copy.deepcopy(params))
            return preview.data
        return invoke(operation, backend=self.name)

    def _prepare_observation(self) -> dict | None:
        config = self._configured()
        if config.observer is None or config.observer.prepare_policy != "load_verified":
            return None
        if self._preparation_result is not None:
            return self._preparation_result
        plan, self._preparation_plan = self._preparation_plan, None
        if plan is None:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "FPGA loading requires a reviewed observation plan.")
        preview, expected = plan
        current = {"deployment": asdict(config),
                   "preparation": PLPreparation(config, runner=self.runner).preview(self.observations.timeout_s)}
        if expected != current:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "FPGA preparation changed after review.")
        consumed = self.approvals.consume(preview["proposal_id"], "prepare_observation", expected)
        if not consumed.success:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "FPGA loading requires explicit human authorization.")
        result = PLPreparation(config, runner=self.runner)(self._budget(self.observations.timeout_s))
        self._budget(1800)
        self._preparation_result = result
        return result

    def preview_observation(self, method: str | None = None, *args) -> OperationResult:
        """Describe configured observation providers without connecting to hardware."""
        def operation():
            config = self._configured()
            observations = self.observations
            uart_available = observations is not None and observations.uart_reader is not None
            period_available = observations is not None and observations.period_reader is not None
            timeout = number(observations.timeout_s) if observations is not None else 15
            descriptor = {"deployment": asdict(config), "timeout_s": timeout,
                          "effects": "Read selected physical observations; no firmware changes."}
            if config.observer is not None:
                descriptor["observed_gpio"] = config.observer.observed_gpio
                if config.observer.prepare_policy == "load_verified":
                    descriptor["preparation"] = PLPreparation(config, runner=self.runner).preview(timeout)
                    descriptor["effects"] = descriptor["preparation"]["effects"]
            if period_available:
                reader = observations.period_reader
                descriptor["period"] = (reader.preview(timeout) if isinstance(reader, PLPeriodReader)
                                        else {"provider": type(reader).__qualname__, "timeout_s": timeout})
            if uart_available:
                reader = observations.uart_reader
                duration = number(args[0]) if method == "read_target_log" and len(args) == 1 else 5
                descriptor["uart"] = (reader.preview(duration, duration + timeout)
                                      if isinstance(reader, PLUARTReader) and method == "read_target_log"
                                      else {"provider": type(reader).__qualname__})
                if isinstance(reader, PLUARTReader) and method == "read_target_log":
                    descriptor["effects"] += " UART capture resets its RX FIFO to exclude stale bytes before reading."
            if method == "run_hardware_test":
                if len(args) != 2 or args[0] != "gpio_period":
                    raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require a GPIO period test and parameters.")
                gpio_result(args[1], {"period_ms": 1})
                if not period_available:
                    raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "PL period reader is not connected.")
                if isinstance(observations.period_reader, PLPeriodReader):
                    descriptor["goal_capability"] = observations.period_reader.validate_goal(args[1], timeout)
                descriptor["test_id"], descriptor["params"] = args
            elif method == "read_target_log":
                if len(args) != 1 or number(args[0]) > 60:
                    raise AgentError(ErrorCode.INVALID_ARGUMENT, "Capture duration must be in (0, 60] seconds.")
                if not uart_available:
                    raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "UART reader is not connected.")
                descriptor["duration_s"] = args[0]
            elif method is not None or args:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Unknown observation operation.")
            return {"uart_available": uart_available, "period_available": period_available,
                    "descriptor": descriptor}
        return invoke(operation, backend=self.name)

    def _observe(self, method: str, *args) -> OperationResult:
        def operation():
            config = self._configured()
            if self.observations is None:
                raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "PL observation backend is not yet connected.")
            # Validate the requested provider and goal before any FPGA effect.
            preview = self.preview_observation(method, *args)
            if not preview.success:
                raise AgentError(ErrorCode(preview.error_code), preview.message)
            if method == "read_target_log":
                self._consume_uart_capture(args[0])
            preparation = self._prepare_observation()
            observations = self.observations
            if self.execution_deadline is not None:
                remaining = self._budget(1800)
                duration = number(args[0]) if method == "read_target_log" else 0
                margin = (config.observer.transport_margin_s if method == "run_hardware_test"
                          and isinstance(observations.period_reader, PLPeriodReader) else 0)
                if remaining <= duration + margin:
                    raise AgentError(ErrorCode.TIMEOUT, "Insufficient time remaining for observation.")
                observations = copy.copy(observations)
                observations.timeout_s = min(number(observations.timeout_s), remaining - duration - margin)
            if method == "run_hardware_test" and isinstance(observations.period_reader, PLPeriodReader):
                try:
                    observations.period_reader.validate_goal(args[1], observations.timeout_s)
                except AgentError as exc:
                    if exc.code == ErrorCode.INVALID_ARGUMENT and observations.timeout_s < self.observations.timeout_s:
                        raise AgentError(ErrorCode.TIMEOUT,
                            "Insufficient remaining time for the approved goal observation window.") from None
                    raise
            outcome = getattr(observations, method)(*args)
            self._budget(1800)
            if not isinstance(outcome, OperationResult):
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Observation provider returned an invalid result.")
            details = {}
            if method == "run_hardware_test" and config.observer is not None:
                details["observed_gpio"] = config.observer.observed_gpio
            if method == "read_target_log" and isinstance(observations.uart_reader, PLUARTReader):
                details.update({"uart_tx_gpio": config.uart_observer.stm32_tx_gpio,
                                "pl_rx_pin": config.uart_observer.pl_rx_pin,
                                "log_source": "pl_uart", "evidence_source": "real_pl_uart"})
            if preparation is not None:
                details["preparation"] = preparation
            if details:
                outcome = replace(outcome, data={**outcome.data, **details})
            return {"outcome": outcome}
        result = invoke(operation, backend=self.name)
        return result.data["outcome"] if result.success else result
