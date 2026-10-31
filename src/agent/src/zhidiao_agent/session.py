"""Trusted semantic authorization: session scope plus every new source diff.

This adapter belongs to the human UI/CLI, never the model tool registry. It
derives single-use cycle permissions only after an exact scope approval. An
approved diff can update one expected input hash; other changes stop the run.
"""

import copy
import json
from dataclasses import asdict

from .approval import ApprovalGate
from .deployment import DeploymentConfig
from .errors import AgentError, ErrorCode
from .models import OperationResult, invoke
from .tools.artifacts import manifest_digest, source_manifest


def _require(result):
    if not isinstance(result, OperationResult):
        raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid authorization result.")
    if not result.success:
        raise AgentError(ErrorCode(result.error_code), result.message)
    return result.data


class SessionScope:
    def __init__(self, loop):
        self.loop = loop
        self.gate = ApprovalGate()
        self._preview = None
        self._expected = None
        self._inputs = None
        self._authorized = False

    def _binding(self, inputs):
        loop, controller = self.loop, self.loop.controller
        backend = controller.backend
        observations = backend.observations
        if not isinstance(backend.config, DeploymentConfig) or observations is None:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Session deployment or observations changed.")
        return {"project_path": str(loop.editor.project), "task": loop.task,
                "goal": copy.deepcopy(loop.params), "observed_gpio": loop.observed_gpio,
                "duration_s": 5, "test_id": "gpio_period",
                "source_files": list(loop.editor.allowed_files), "source_sha256": manifest_digest(inputs),
                "deployment": asdict(backend.config), "include_uart": loop.include_uart,
                "max_attempts": controller.max_attempts, "timeout_s": loop.timeout_s,
                "allowed_roots": list(controller.allowed_roots),
                "runtime_identity": [id(loop), id(controller), id(loop.editor), id(loop.agent), id(backend),
                                     id(backend.runner), id(observations), id(observations.uart_reader),
                                     id(observations.period_reader)]}

    def preview(self) -> OperationResult:
        def operation():
            if self._authorized or not self.loop._real:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Create a new reviewed real session.")
            self.loop._recover()
            self._inputs = source_manifest(self.loop.editor.project)
            self._expected = self._binding(self._inputs)
            observation = _require(self.loop.controller.backend.preview_observation(
                "read_target_log", 5)) if self.loop.include_uart else _require(
                    self.loop.controller.backend.preview_observation())
            params = {"scope": copy.deepcopy(self._expected), "observation": observation,
                      "summary": "批准此工程、目标、板卡和工具范围内的基线验证；每次新源码 diff 仍须批准。批准修改后自动重新构建、烧录和观测。",
                      "tools": ["build_firmware", "flash_firmware"]
                               + (["read_target_log"] if self.loop.include_uart else []) + ["run_hardware_test"],
                      "effects": "Build and program only this project's verified artifact; collect the selected physical evidence. If configured, update only the fixed 4-bit LED status bank at 0x43C60000. No Git, SSH configuration, boot file or Agent source changes.",
                      "approval_mode": "semantic"}
            self._preview = _require(self.gate.propose("run_session", params))
            return copy.deepcopy(self._preview)
        return invoke(operation, backend="session_scope")

    def _check(self):
        if not self._authorized:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Human session scope approval is required.")
        self.loop._time_check()
        actual = source_manifest(self.loop.editor.project)
        if actual != self._inputs or self._binding(actual) != self._expected:
            self._authorized = False
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Session inputs or target changed outside the approved diff.")

    def review_scope(self, proposal_id: str, fingerprint: str, *, approved: bool) -> OperationResult:
        def operation():
            preview = self._preview
            if preview is None or (proposal_id, fingerprint) != (preview["proposal_id"], preview["fingerprint"]):
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Session approval does not match its preview.")
            actual = source_manifest(self.loop.editor.project)
            if actual != self._inputs or self._binding(actual) != self._expected:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Session scope changed during review.")
            decision = self.gate.decide(proposal_id, fingerprint, approved=approved)
            self.loop._record_review("session", preview, approved, decision.error_code)
            _require(decision)
            _require(self.gate.consume(proposal_id, "run_session", preview["params"]))
            self._authorized = True
            self._preview = None
            self.loop.session_approval = {"proposal_id": proposal_id, "fingerprint": fingerprint, "mode": "semantic"}
            self.loop.events.emit("TASK_ACCEPTED")
            return {"approved": True}
        return invoke(operation, backend="session_scope")

    def approve_cycle(self) -> OperationResult:
        def operation():
            self._check()
            pending = self.loop.pending_execution
            if pending is None:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "No cycle is pending in this session.")
            actual = pending["params"]["binding"]
            expected = {"project_path": self._expected["project_path"],
                        "source_sha256": self._expected["source_sha256"],
                        "deployment": self._expected["deployment"], "test_id": self._expected["test_id"],
                        "test_params": self._expected["goal"], "duration_s": self._expected["duration_s"],
                        "include_uart": self._expected["include_uart"],
                        "safety_limits": {"allowed_roots": self._expected["allowed_roots"],
                                          "max_attempts": self._expected["max_attempts"]}}
            if actual != json.loads(json.dumps(expected, allow_nan=False)):
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Cycle is outside the approved session inputs.")
            return {"outcome": self.loop.review_execution(pending["proposal_id"], pending["fingerprint"], approved=True)}
        result = invoke(operation, backend="session_scope")
        return result.data["outcome"] if result.success else result

    def review_edit(self, proposal_id: str, fingerprint: str, *, approved: bool) -> OperationResult:
        def operation():
            self._check()
            pending = self.loop.pending
            if pending is None or (proposal_id, fingerprint) != (pending["proposal_id"], pending["fingerprint"]):
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Diff does not match the reviewed proposal.")
            expected = dict(self._inputs)
            name = pending["params"]["path"]
            if name not in self.loop.editor.allowed_files or expected.get(name) != pending["params"]["before_sha256"]:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Diff is outside the approved source scope.")
            expected[name] = pending["params"]["after_sha256"]
            result = self.loop.review_edit(proposal_id, fingerprint, approved=approved)
            if not approved or not result.success:
                self._authorized = False
                return {"outcome": result}
            actual = source_manifest(self.loop.editor.project)
            binding = self._binding(actual)
            target = {**self._expected, "source_sha256": manifest_digest(expected)}
            if actual != expected or binding != target:
                self._authorized = False
                self.loop.cancel()
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Inputs changed beyond the approved edit; stop and review a new session.")
            self._inputs, self._expected = expected, target
            return {"outcome": result}
        result = invoke(operation, backend="session_scope")
        return result.data["outcome"] if result.success else result
