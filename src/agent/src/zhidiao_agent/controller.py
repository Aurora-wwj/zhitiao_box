"""Deterministic tool order and explicitly reviewed real execution."""

import json
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid

from .errors import AgentError, ErrorCode
from .approval import ApprovalGate
from .models import OperationResult, invoke
from .observations import gpio_result, number
from .tools.artifacts import source_digest, validate_hex
from .tools.interfaces import HardwareBackend
from .events import WorkflowEvents

TOOL_STATES = {"build_firmware": "BUILDING", "flash_firmware": "FLASHING",
               "read_target_log": "OBSERVING", "run_hardware_test": "OBSERVING"}


def _tool_result(backend, name, inputs, events, attempt):
    try:
        result = getattr(backend, name)(**inputs)
        if not isinstance(result, OperationResult):
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Backend returned an invalid result.")
        return result
    except (Exception, KeyboardInterrupt) as error:
        code = (error.code.value if isinstance(error, AgentError) else
                "CANCELLED" if isinstance(error, KeyboardInterrupt) else
                "TIMEOUT" if isinstance(error, TimeoutError) else
                "NETWORK_UNREACHABLE" if isinstance(error, OSError) else "INTERNAL_ERROR")
        events.emit("TOOL_FINISHED", attempt=attempt, tool_name=name, success=False, error_code=code)
        raise


class Controller:
    def __init__(
        self, backend: HardwareBackend, *, allowed_roots: tuple[str, ...],
        max_attempts: int = 3,
    ) -> None:
        self.backend = backend
        self.allowed_roots = allowed_roots
        self.max_attempts = max_attempts
        self.events = WorkflowEvents()

    def close_status_indicator(self):
        indicator = getattr(self, "_status_indicator", None)
        if indicator is not None:
            indicator.close()

    def _check_path(self, value: str) -> str:
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid local path.")
        path = Path(value)
        if not path.is_absolute():
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require an absolute local path.")
        resolved = path.resolve()
        for root in self.allowed_roots:
            root_path = Path(root)
            if root_path.is_absolute() and resolved.is_relative_to(root_path.resolve()):
                return str(resolved)
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Local path is outside allowed roots.")

    def run(
        self, project_path: str, *, test_id: str = "gpio_period",
        params: dict[str, Any] | None = None, duration_s: float = 5,
    ) -> OperationResult:
        def operation() -> dict[str, Any]:
            if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "max_attempts must be 1 to 3.")
            if self.backend.requires_approval is not False:
                raise AgentError(
                    ErrorCode.APPROVAL_REQUIRED,
                    "Automatic real execution is disabled; review each operation separately.",
                )
            project = self._check_path(project_path)
            actual_params = params if params is not None else {
                "expected_period_ms": 1000, "tolerance_ms": 50,
            }
            if test_id == "gpio_period":
                gpio_result(actual_params, {"period_ms": 1})
            run_id = "run_" + uuid.uuid4().hex
            audit: list[dict[str, Any]] = []

            def call(name: str, inputs: dict[str, Any], attempt: int) -> OperationResult:
                event_attempt = attempt + getattr(self, "_event_attempt_offset", 0)
                self.events.emit(TOOL_STATES[name], attempt=event_attempt, tool_name=name)
                start = datetime.now(timezone.utc).isoformat()
                result = _tool_result(self.backend, name, inputs, self.events, event_attempt)
                self.events.emit("TOOL_FINISHED", attempt=event_attempt, tool_name=name,
                                 success=result.success, error_code=result.error_code,
                                 period_ms=result.data.get("measurements", {}).get("period_ms"),
                                 passed=result.data.get("passed"),
                                 log_count=len(result.data["logs"]) if "logs" in result.data else None)
                audit.append({
                    "run_id": run_id, "attempt": attempt, "tool_name": name,
                    "input": inputs, "start_time": start,
                    "end_time": datetime.now(timezone.utc).isoformat(),
                    "result": result.to_dict(), "backend": self.backend.name,
                })
                return result

            def finish(decision: str, reason: str, attempt: int) -> dict[str, Any]:
                return {
                    "run_id": run_id, "decision": decision, "reason": reason,
                    "attempts": attempt, "audit": audit,
                }

            for attempt in range(1, self.max_attempts + 1):
                build = call("build_firmware", {"project_path": project}, attempt)
                if not build.success:
                    return finish("FAIL", "BUILD_FAILED", attempt)
                artifact = self._check_path(build.data.get("artifact_path"))
                flash = call("flash_firmware", {"firmware_path": artifact}, attempt)
                if not flash.success or flash.data.get("verified") is not True:
                    return finish("FAIL", "FLASH_NOT_VERIFIED", attempt)
                logs = call("read_target_log", {"duration_s": duration_s}, attempt)
                if not logs.success:
                    return finish("FAIL", "LOG_COLLECTION_FAILED", attempt)
                measurement = call(
                    "run_hardware_test", {"test_id": test_id, "params": actual_params}, attempt,
                )
                if not measurement.success:
                    return finish("FAIL", "MEASUREMENT_TOOL_FAILED", attempt)
                if type(measurement.data.get("passed")) is not bool:
                    raise AgentError(ErrorCode.INVALID_RESPONSE, "Missing boolean measurement result.")
                if test_id == "gpio_period":
                    assessment = gpio_result(actual_params, measurement.data.get("measurements"))
                    if assessment["passed"] is not measurement.data["passed"]:
                        raise AgentError(ErrorCode.INVALID_RESPONSE, "Measurement verdict contradicts the physical evidence.")
                if measurement.data["passed"]:
                    return finish("PASS", "ALL_CHECKS_PASSED", attempt)
            return finish("FAIL", "ATTEMPTS_EXHAUSTED", self.max_attempts)

        return invoke(operation, backend="controller")

    def run_once(self, project_path: str, **kwargs) -> OperationResult:
        """One cycle for an upper orchestrator; never repeat unchanged firmware here."""
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
            return OperationResult(False, ErrorCode.INVALID_ARGUMENT.value,
                                   "max_attempts must be 1 to 3.", "controller")
        single = Controller(self.backend, allowed_roots=self.allowed_roots, max_attempts=1)
        single.events = self.events
        single._event_attempt_offset = getattr(self, "_event_attempt_offset", 0)
        return single.run(project_path, **kwargs)


@dataclass(frozen=True)
class _CyclePlan:
    proposal_id: str
    fingerprint: str
    params: dict
    build_preview: dict
    deadline: float
    providers: tuple


class ReviewedController(Controller):
    """One human-approved build/deploy/observe cycle, with no unchanged retry.

    Only the trusted UI may call review_cycle. A cycle approval permits flashing
    the HEX produced by this exact approved build, never an arbitrary later file.
    The four public hardware method signatures remain unchanged.
    """

    def __init__(self, backend: HardwareBackend, *, allowed_roots: tuple[str, ...],
                 max_attempts: int = 3, approvals: ApprovalGate | None = None):
        super().__init__(backend, allowed_roots=allowed_roots, max_attempts=max_attempts)
        self.approvals = approvals if approvals is not None else ApprovalGate()
        self._cycle: _CyclePlan | None = None
        self._authorized: str | None = None
        self._executed_cycles = 0
        self.execution_deadline: float | None = None
        self._status_indicator = None

    def _ensure_status_indicator(self):
        config = self.backend.config
        if config.status_indicator is None or self._status_indicator is not None:
            return
        try:
            from .status_indicator import LEDStatusAdapter
            self._status_indicator = LEDStatusAdapter(config, self.events)
        except Exception:
            # Optional display setup is not part of tool or DUT validation.
            self.events.emit("INDICATOR_ERROR", attempt=self._executed_cycles,
                             error_code="STATUS_INDICATOR_UNAVAILABLE")

    @staticmethod
    def _require(result: OperationResult) -> dict:
        if not isinstance(result, OperationResult):
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Tool returned an invalid result.")
        if not result.success:
            try:
                code = ErrorCode(result.error_code)
            except (ValueError, TypeError):
                code = ErrorCode.INTERNAL_ERROR
            raise AgentError(code, result.message)
        return result.data

    def _binding(self, project_path, params, duration_s, include_uart, test_id):
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "max_attempts must be 1 to 3.")
        if self.backend.requires_approval is not True or getattr(self.backend, "config", None) is None:
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "ReviewedController requires a configured real backend.")
        project = self._check_path(project_path)
        project = str(self.backend.config.local_path(project))
        if not Path(project).is_dir():
            raise AgentError(ErrorCode.PROJECT_NOT_FOUND, "Project directory does not exist.")
        if test_id != "gpio_period":
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Only the gpio_period goal is supported.")
        gpio_result(params, {"period_ms": 1})
        self._require(self.backend.preview_observation("run_hardware_test", test_id, params))
        duration = number(duration_s)
        if duration > 60 or type(include_uart) is not bool:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid observation selection or duration.")
        return json.loads(json.dumps({
            "project_path": project, "source_sha256": source_digest(Path(project)),
            "deployment": asdict(self.backend.config), "test_id": test_id,
            "test_params": params, "duration_s": duration, "include_uart": include_uart,
            "safety_limits": {"allowed_roots": list(self.allowed_roots), "max_attempts": self.max_attempts},
        }, allow_nan=False))

    def _check_plan(self, plan: _CyclePlan):
        expected = plan.params["binding"]
        actual = self._binding(expected["project_path"], expected["test_params"],
                               expected["duration_s"], expected["include_uart"], expected["test_id"])
        if actual != expected:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Project, goal or deployment changed; preview the cycle again.")
        observation = json.loads(json.dumps(self._require(
            self.backend.preview_observation("read_target_log", expected["duration_s"])
            if expected["include_uart"] else self.backend.preview_observation()), allow_nan=False))
        if observation != plan.params["observation"]:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Observation configuration changed; preview the cycle again.")
        if any(actual is not expected for actual, expected in zip(self._providers(), plan.providers)):
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Observation reader changed; preview the cycle again.")
        deadline = plan.deadline
        if self.execution_deadline is not None:
            deadline = min(deadline, self.execution_deadline)
        if time.monotonic() >= deadline:
            raise AgentError(ErrorCode.TIMEOUT, "Approved cycle time budget exhausted.")
        return deadline

    def _providers(self):
        observations = self.backend.observations
        return (observations, getattr(observations, "uart_reader", None),
                getattr(observations, "period_reader", None))

    def _discard(self):
        plan, self._cycle = self._cycle, None
        self._authorized = None
        if plan is not None:
            self.approvals.decide(plan.proposal_id, plan.fingerprint, approved=False)
            self.approvals.consume(plan.proposal_id, "build_deploy_observe", plan.params)
            self.backend.approvals.decide(plan.build_preview["proposal_id"],
                                          plan.build_preview["fingerprint"], approved=False)

    def cancel_cycle(self) -> OperationResult:
        def operation():
            self._discard()
            return {"state": "cancelled"}
        return invoke(operation, backend="reviewed_controller")

    def preview_cycle(self, project_path: str, *, params: dict | None = None,
                      test_id: str = "gpio_period", duration_s: float = 5,
                      include_uart: bool = True, timeout_s: float = 300) -> OperationResult:
        """Pure preview. Creating a proposal must not run a process or touch hardware."""
        def operation():
            self._discard()
            budget = number(timeout_s)
            if budget > 1800 or self._executed_cycles >= self.max_attempts:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Cycle budget or attempt limit is exhausted.")
            selected = params if params is not None else {"expected_period_ms": 1000, "tolerance_ms": 50}
            binding = self._binding(project_path, selected, duration_s, include_uart, test_id)
            build = self._require(self.backend.preview_build(binding["project_path"]))
            observation = self._require(self.backend.preview_observation("read_target_log", duration_s)
                                        if include_uart else self.backend.preview_observation())
            if include_uart and not observation.get("uart_available", False):
                raise AgentError(ErrorCode.BACKEND_UNAVAILABLE,
                                 "UART is not connected; explicitly select PL-only observation to continue.")
            if not observation.get("period_available", False):
                raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "PL period reader is not connected.")
            payload = {
                "binding": binding, "build": build["params"], "observation": observation,
                "timeout_s": budget, "attempt": self._executed_cycles + 1,
                "artifact_policy": "Flash only the validated HEX returned by this approved build, with matching path and SHA-256.",
                "steps": ["build_firmware", "flash_firmware"]
                         + (["read_target_log"] if include_uart else []) + ["run_hardware_test"],
                "effects": "Rebuild this source snapshot, upload its resulting HEX, program/verify/reset STM32, and collect selected real observations. If configured, update only the fixed 4-bit LED status bank at 0x43C60000.",
                "internal_preparation": observation.get("descriptor", {}).get("preparation"),
                "observed_gpio": getattr(self.backend.config.observer, "observed_gpio", "PA1"),
                "verification_scope": "gpio_period_and_uart_capture" if include_uart else "gpio_period_only",
            }
            proposed = self._require(self.approvals.propose("build_deploy_observe", payload))
            # Keep a detached plan; editing the displayed preview cannot rewrite it.
            payload = json.loads(json.dumps(payload, allow_nan=False))
            self._cycle = _CyclePlan(proposed["proposal_id"], proposed["fingerprint"], payload,
                                     json.loads(json.dumps(build)), time.monotonic() + budget, self._providers())
            return proposed
        return invoke(operation, backend="reviewed_controller")

    def review_cycle(self, proposal_id: str, fingerprint: str, *, approved: bool) -> OperationResult:
        """Trusted UI only. This authorizes the pending cycle but executes nothing."""
        def operation():
            plan = self._cycle
            if plan is None or (proposal_id, fingerprint) != (plan.proposal_id, plan.fingerprint):
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Review does not match the pending tool cycle.")
            self._check_plan(plan)
            result = self.approvals.decide(proposal_id, fingerprint, approved=approved)
            if not result.success:
                self._discard()
            self._require(result)
            self._authorized = proposal_id
            return {"state": "approved", "proposal_id": proposal_id}
        result = invoke(operation, backend="reviewed_controller")
        if not result.success:
            self._discard()
        return result

    def run_once(self, project_path: str, *, params: dict | None = None,
                 test_id: str = "gpio_period", duration_s: float = 5,
                 include_uart: bool = True) -> OperationResult:
        audit: list[dict] = []
        run_id = "run_" + uuid.uuid4().hex

        def operation():
            plan = self._cycle
            if plan is None or self._authorized != plan.proposal_id:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Preview and approve the real cycle before executing it.")
            # A consumed or failed cycle is never replayable.
            self._cycle, self._authorized = None, None
            try:
                deadline = self._check_plan(plan)
                actual = self._binding(project_path, params if params is not None else {
                    "expected_period_ms": 1000, "tolerance_ms": 50}, duration_s, include_uart, test_id)
                if actual != plan.params["binding"] or self._executed_cycles >= self.max_attempts:
                    raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Execution does not match the approved cycle.")
                self._require(self.approvals.consume(plan.proposal_id, "build_deploy_observe", plan.params))
                self._executed_cycles += 1
                attempt = self._executed_cycles
                self._ensure_status_indicator()
                previous_deadline = getattr(self.backend, "execution_deadline", None)
                self.backend.execution_deadline = min(deadline, previous_deadline) if previous_deadline is not None else deadline

                def finish(decision, reason):
                    return {"run_id": run_id, "decision": decision, "reason": reason,
                            "attempts": 1, "cycle_number": attempt, "audit": audit,
                            "cycle_approval": {"proposal_id": plan.proposal_id, "fingerprint": plan.fingerprint},
                            "evidence_source": "real", "verification_scope": plan.params["verification_scope"],
                            "uart_observed": any(row["tool_name"] == "read_target_log" and row["result"]["success"] for row in audit),
                            "skipped_tools": [] if include_uart else [{"tool_name": "read_target_log", "reason": "PL_ONLY_EXPLICITLY_SELECTED"}]}

                def call(name, inputs):
                    self._check_plan(plan)
                    self.events.emit(TOOL_STATES[name], attempt=attempt, tool_name=name)
                    started = datetime.now(timezone.utc).isoformat()
                    result = _tool_result(self.backend, name, inputs, self.events, attempt)
                    self.events.emit("TOOL_FINISHED", attempt=attempt, tool_name=name,
                                     success=result.success, error_code=result.error_code,
                                     period_ms=result.data.get("measurements", {}).get("period_ms"),
                                     passed=result.data.get("passed"),
                                     log_count=len(result.data["logs"]) if "logs" in result.data else None)
                    audit.append({"run_id": run_id, "attempt": attempt, "tool_name": name,
                                  "input": inputs, "start_time": started,
                                  "end_time": datetime.now(timezone.utc).isoformat(),
                                  "result": result.to_dict(), "backend": self.backend.name})
                    self._check_plan(plan)
                    return result

                def authorize_child(preview):
                    self._check_plan(plan)
                    self._require(self.backend.approvals.decide(preview["proposal_id"], preview["fingerprint"], approved=True))

                try:
                    authorize_child(plan.build_preview)
                    build = call("build_firmware", {"project_path": actual["project_path"]})
                    if not build.success:
                        return finish("FAIL", "BUILD_FAILED" if build.error_code == ErrorCode.BUILD_FAILED.value else "BUILD_TOOL_FAILED")
                    artifact = self._check_path(build.data.get("artifact_path"))
                    expected_artifact = plan.build_preview["params"]["artifact_path"]
                    if artifact != expected_artifact or not Path(artifact).is_relative_to(Path(actual["project_path"])):
                        raise AgentError(ErrorCode.INVALID_RESPONSE, "Build returned an artifact outside the approved build plan.")
                    digest = validate_hex(Path(artifact))
                    if build.data.get("artifact_sha256") != digest:
                        raise AgentError(ErrorCode.INVALID_RESPONSE, "Build artifact SHA-256 does not match its evidence.")
                    flash_preview = self._require(self.backend.preview_flash(artifact))
                    if (flash_preview["params"]["artifact_path"] != artifact
                            or flash_preview["params"]["firmware_sha256"] != digest):
                        raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Firmware changed after the approved build.")
                    authorize_child(flash_preview)
                    flash = call("flash_firmware", {"firmware_path": artifact})
                    if not flash.success or flash.data.get("verified") is not True:
                        return finish("FAIL", "FLASH_NOT_VERIFIED")
                    self.backend._begin_observation_cycle()
                    if (plan.params.get("internal_preparation") or {}).get("requires_loading") is True:
                        # Derived from this exact human-approved cycle, never
                        # from a model response or a prior cycle's permission.
                        preparation_preview = self._require(self.backend._preview_preparation())
                        authorize_child(preparation_preview)
                    if include_uart:
                        uart_preview = self._require(self.backend._preview_uart_capture(duration_s))
                        if uart_preview.get("required") is not False:
                            authorize_child(uart_preview)
                        logs = call("read_target_log", {"duration_s": duration_s})
                        if not logs.success:
                            return finish("FAIL", "LOG_COLLECTION_FAILED")
                        # partial_tail at a normal deadline is auxiliary text.
                        # Never waive an actual truncation or health error,
                        # including ambiguous truncated=true from legacy readers.
                        if (logs.data.get("overflow") is True or logs.data.get("truncated") is True
                                or logs.data.get("decoding_errors", 0) > 0
                                or logs.data.get("frame_errors", 0) > 0 or logs.data.get("parity_errors", 0) > 0):
                            return finish("FAIL", "LOG_INCOMPLETE")
                    measurement = call("run_hardware_test", {"test_id": test_id, "params": actual["test_params"]})
                    if not measurement.success:
                        return finish("FAIL", "MEASUREMENT_TOOL_FAILED")
                    assessment = gpio_result(actual["test_params"], measurement.data.get("measurements"))
                    if type(measurement.data.get("passed")) is not bool or assessment["passed"] is not measurement.data["passed"]:
                        raise AgentError(ErrorCode.INVALID_RESPONSE, "Measurement verdict contradicts the physical evidence.")
                    return finish("PASS", "ALL_SELECTED_CHECKS_PASSED") if assessment["passed"] else finish("FAIL", "ATTEMPTS_EXHAUSTED")
                finally:
                    self.backend.execution_deadline = previous_deadline
                    # Revoke any derived approval left unused after an error.
                    self.backend.approvals.consume(plan.build_preview["proposal_id"], "build_firmware", plan.build_preview["params"])
                    if "flash_preview" in locals():
                        self.backend.approvals.consume(flash_preview["proposal_id"], "flash_firmware", flash_preview["params"])
                    if "preparation_preview" in locals():
                        self.backend.approvals.consume(preparation_preview["proposal_id"], "prepare_observation", preparation_preview["params"])
                    if "uart_preview" in locals() and "proposal_id" in uart_preview:
                        self.backend.approvals.consume(uart_preview["proposal_id"], "capture_uart", uart_preview["params"])
            finally:
                self.approvals.consume(plan.proposal_id, "build_deploy_observe", plan.params)

        result = invoke(operation, backend="reviewed_controller")
        return result if result.success else replace(result, data={**result.data, "run_id": run_id, "audit": audit, "evidence_source": "real"})
