"""Evidence/decision/edit loop above a deterministic Controller.

Mock cycles run directly; real cycles require a separate, bound human approval.
"""

import json
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from .agent import Agent
from .controller import Controller, ReviewedController
from .editing import SourceEditor
from .errors import AgentError, ErrorCode
from .models import OperationResult, invoke
from .observations import gpio_result, number
from .reports import RunStore, RUN_ID
from .provenance import describe_model, validate_model_info
from .tools.artifacts import source_digest

TERMINAL = {"PASS", "FAIL", "STOPPED"}


class Orchestrator:
    def __init__(
        self, controller: Controller, agent: Agent, editor: SourceEditor, *, task: str,
        project_path: str, params: dict, timeout_s: float = 300, clock=None,
        include_uart: bool = True,
        report_store: RunStore | None = None, recovery_report: dict | None = None,
        model_info: dict | None = None,
        run_id: str | None = None, task_entry: dict | None = None,
    ):
        self.controller, self.agent, self.editor = controller, agent, editor
        self.events = controller.events
        self.session_approval = None
        self.model_info = validate_model_info(model_info) if model_info is not None else describe_model(agent.client)
        self.task_entry = json.loads(json.dumps(task_entry, allow_nan=False)) if task_entry is not None else None
        self.reviews = []
        self.task, self.project_path = task, project_path
        try:
            self.params = json.loads(json.dumps(params, allow_nan=False))
        except (TypeError, ValueError):
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Goal parameters must be finite JSON data.") from None
        self.timeout_s = timeout_s
        self.include_uart = include_uart
        self._real = isinstance(controller, ReviewedController)
        self.clock = clock if clock is not None else time.monotonic
        self.started = self.clock()
        self.wall_started_at = time.time()
        self._elapsed_offset = 0.0
        if run_id is not None and (not isinstance(run_id, str) or RUN_ID.fullmatch(run_id) is None):
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid task run identity.")
        self.run_id = run_id or "run_" + uuid.uuid4().hex
        self.state, self.reason = "READY", "NOT_STARTED"
        self.attempts = 0
        self.cycles: list[dict] = []
        self.pending: dict | None = None
        self.pending_execution: dict | None = None
        self._execution_authorized = False
        self.report_store = report_store
        self.parent_run_id: str | None = None
        self.report_path: str | None = None
        self._checkpoint: dict | None = None
        self._in_flight: str | None = None
        self._recovery_report = recovery_report
        config = self.controller.backend.config if self._real else None
        self.observed_gpio = config.observer.observed_gpio if config is not None and config.observer is not None else "PA1"

    def _metadata(self):
        return {
            "project_path": str(self.editor.project), "task": self.task, "goal": self.params,
            "allowed_sources": list(self.editor.allowed_files), "include_uart": self.include_uart,
            "deployment": asdict(self.controller.backend.config) if self._real else None,
            "timeout_s": self.timeout_s,
            **({"model_info": self.model_info} if self.model_info is not None else {}),
        }

    def _persist(self) -> dict:
        if self.report_store is None:
            return {}
        project = self.editor.project
        report_root = self.report_store.root.resolve()
        if report_root.is_relative_to(project) and not report_root.is_relative_to(project / ".zhidiao"):
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Reports inside the project must stay in .zhidiao.")
        sources = self._require(self.editor.snapshot())["sources"]
        self._checkpoint = {"source_sha256": source_digest(project),
                            "source_hashes": {name: row["sha256"] for name, row in sources.items()}}
        self.report_path = str(self.report_store.root / (self.run_id + ".json"))
        return self._require(self.report_store.save(self.report()))

    def _recover(self):
        if self._recovery_report is None:
            return
        saved, self._recovery_report = self._recovery_report, None
        try:
            saved = json.loads(json.dumps(saved, allow_nan=False))
        except (TypeError, ValueError):
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Recovery report must contain finite JSON data.") from None
        expected = json.loads(json.dumps(self._metadata(), allow_nan=False))
        # Frontends spend different amounts of their overall budget interpreting
        # and confirming the goal on each launch. Bind the goal and deployment
        # exactly, then cap the new budget to the old budget rather than require
        # equality between two measured floating-point remainders.
        current_budget = number(expected.pop("timeout_s"))
        saved_metadata = saved.get("metadata") if isinstance(saved, dict) else None
        previous_metadata = dict(saved_metadata) if isinstance(saved_metadata, dict) else {}
        previous_budget = previous_metadata.pop("timeout_s", None)
        if (not isinstance(saved, dict) or saved.get("report_schema") != "1.0"
                or previous_metadata != expected or saved.get("observed_gpio") != self.observed_gpio
                or saved.get("evidence_source") != ("real" if self._real else "mock")
                or saved.get("max_attempts") != self.controller.max_attempts
                or type(saved.get("attempts")) is not int or not 0 <= saved["attempts"] <= self.controller.max_attempts
                or not isinstance(saved.get("cycles"), list) or len(saved["cycles"]) != saved["attempts"]
                or saved.get("in_flight") is not None):
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Recovery binding is invalid or an operation may still be in flight.")
        self.timeout_s = min(current_budget, number(previous_budget))
        sources = self._require(self.editor.snapshot())["sources"]
        checkpoint = {"source_sha256": source_digest(self.editor.project),
                      "source_hashes": {name: row["sha256"] for name, row in sources.items()}}
        if saved.get("checkpoint") != checkpoint:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Source changed since the saved checkpoint; start a reviewed new run.")
        # The old JSON is evidence only. Never re-create approval state from it.
        from .reports import RUN_ID
        if not isinstance(saved.get("run_id"), str) or RUN_ID.fullmatch(saved["run_id"]) is None:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid recovery run identity.")
        elapsed = number(saved.get("elapsed_s"), zero=True)
        started = number(saved.get("wall_started_at"))
        self._elapsed_offset = max(elapsed, max(0, time.time() - started))
        self.wall_started_at = started
        self.parent_run_id = saved["run_id"]
        self.attempts, self.cycles = saved["attempts"], saved["cycles"]
        self._checkpoint = checkpoint
        if saved.get("decision") in TERMINAL:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED,
                             "Completed reports are historical evidence; open the report or start a newly reviewed run.")
        self._time_check()
        if self._real:
            self.controller._executed_cycles = self.attempts
        if saved.get("decision") == "AWAITING_APPROVAL":
            try:
                decision = self.cycles[-1]["model_decision"]
                edit = decision["edit"]
                if decision["action"] != "edit":
                    raise ValueError()
            except (KeyError, IndexError, TypeError, ValueError):
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Saved edit has no reviewed evidence proposal.") from None
            self.pending = self._require(self.editor.preview(edit))
            self.pending["reason"] = decision.get("reason", "Recovered proposal; review the complete diff again.")
            self.state, self.reason = "AWAITING_APPROVAL", "RECOVERED_EDIT_REQUIRES_FRESH_HUMAN_REVIEW"
        elif saved.get("decision") in {"READY", "AWAITING_EXECUTION_APPROVAL"}:
            self.state, self.reason = "READY", "RECOVERED_REQUIRES_FRESH_EXECUTION_REVIEW"
        else:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Saved state cannot safely continue; inspect its report first.")

    def _time_check(self):
        budget = number(self.timeout_s)
        if budget > 1800 or self.clock() - self.started + self._elapsed_offset >= budget:
            raise AgentError(ErrorCode.TIMEOUT, "Orchestrator time budget exhausted.")

    def _record_review(self, kind, preview, approved, error_code=None):
        # Evidence only: this list cannot recreate an ApprovalGate permission.
        row = {"kind": kind, "attempt": self.attempts,
               "proposal_id": preview["proposal_id"], "fingerprint": preview["fingerprint"],
               "approved": approved if type(approved) is bool else None,
               "error_code": error_code, "params": preview["params"]}
        if preview.get("reason"):
            row["reason"] = preview["reason"]
        self.reviews.append(json.loads(json.dumps(row, allow_nan=False)))
        self.reviews = self.reviews[-16:]

    def _finish(self, state: str, reason: str):
        if self.pending is not None:
            self.editor.approvals.decide(self.pending["proposal_id"], self.pending["fingerprint"], approved=False)
        self.pending = None
        if self._real:
            self.controller.cancel_cycle()
        self.pending_execution = None
        self._execution_authorized = False
        self.state, self.reason = state, reason
        self.events.emit(state, attempt=self.attempts)

    def report(self) -> dict:
        uncertain = False
        if self._real:
            observer = self.controller.backend.config.observer
            for cycle in self.cycles:
                for entry in cycle.get("execution", {}).get("audit", []):
                    result = entry.get("result", {})
                    interrupted = result.get("error_code") in {
                        "TIMEOUT", "CANCELLED", "SSH_CONNECT_FAILED", "NETWORK_UNREACHABLE", "BACKEND_UNAVAILABLE",
                    }
                    if interrupted and ((entry.get("tool_name") == "flash_firmware"
                                         and result.get("upload_verified") is True)
                                        or (entry.get("tool_name") in {"read_target_log", "run_hardware_test"}
                                            and observer is not None and observer.prepare_policy == "load_verified")):
                        uncertain = True
        return json.loads(json.dumps({
            "run_id": self.run_id, "decision": self.state, "reason": self.reason,
            "report_schema": "1.0", "parent_run_id": self.parent_run_id,
            "report_stage": "execution", "task_entry": self.task_entry,
            "metadata": self._metadata(), "observed_gpio": self.observed_gpio,
            "checkpoint": self._checkpoint, "in_flight": self._in_flight,
            "hardware_state_uncertain": uncertain,
            "wall_started_at": self.wall_started_at,
            "elapsed_s": max(0, self.clock() - self.started + self._elapsed_offset),
            "report_path": self.report_path,
            "attempts": self.attempts, "max_attempts": self.controller.max_attempts,
            "evidence_source": "real" if self._real else "mock",
            "verification_scope": "gpio_period_and_uart_capture" if self.include_uart else "gpio_period_only",
            "cycles": self.cycles, "pending_edit": self.pending,
            "pending_execution": self.pending_execution,
            "events": self.events.snapshot(), "session_approval": self.session_approval,
            "reviews": self.reviews,
            **({"model_info": self.model_info} if self.model_info is not None else {}),
        }, allow_nan=False))

    def _guard(self, operation) -> OperationResult:
        result = invoke(operation, backend="orchestrator")
        if not result.success:
            self.events.emit("ERROR", attempt=self.attempts, error_code=result.error_code)
            if self.state not in TERMINAL:
                self._finish("STOPPED", result.error_code)
            self._in_flight = None
            invoke(self._persist, backend="run_report")
            return OperationResult(False, result.error_code, result.message, "orchestrator",
                                   result.duration_ms, data={"report": self.report()})
        persisted = invoke(self._persist, backend="run_report")
        if not persisted.success:
            self._finish("STOPPED", persisted.error_code)
            return OperationResult(False, persisted.error_code, persisted.message, "orchestrator",
                                   result.duration_ms, data={"report": self.report()})
        return OperationResult(True, None, result.message, "orchestrator", result.duration_ms, data=self.report())

    @staticmethod
    def _require(result: OperationResult):
        if not result.success:
            try:
                code = ErrorCode(result.error_code)
            except ValueError:
                code = ErrorCode.INTERNAL_ERROR
            raise AgentError(code, result.message)
        return result.data

    def advance(self) -> OperationResult:
        """Run at most one cycle. A pending edit cannot advance without review."""
        def operation():
            self._recover()
            if self.state in TERMINAL:
                return self.report()
            self._time_check()
            if self.pending is not None:
                return self.report()
            if self.pending_execution is not None and not self._execution_authorized:
                return self.report()
            limit = self.controller.max_attempts
            if type(limit) is not int or not 1 <= limit <= 3:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Controller must bound attempts to 1–3.")
            if self.controller.backend.requires_approval is not False and not self._real:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Automatic real loops remain disabled.")
            if type(self.include_uart) is not bool:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require an explicit UART observation selection.")
            if not isinstance(self.task, str) or not self.task.strip():
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require a user task.")
            project = self.controller._check_path(self.project_path)
            if Path(project) != self.editor.project:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Editor and Controller must use the same project.")
            gpio_result(self.params, {"period_ms": 1})
            if self.attempts >= limit:
                self._finish("FAIL", "ATTEMPTS_EXHAUSTED")
                return self.report()
            sources = self._require(self.editor.snapshot())["sources"]
            if self._real and self.pending_execution is None:
                remaining = number(self.timeout_s) - (self.clock() - self.started + self._elapsed_offset)
                self.pending_execution = self._require(self.controller.preview_cycle(
                    project, params=self.params, include_uart=self.include_uart, timeout_s=remaining,
                ))
                self.state, self.reason = "AWAITING_EXECUTION_APPROVAL", "REAL_CYCLE_REQUIRES_HUMAN"
                self.events.emit("WAITING_APPROVAL", attempt=self.attempts + 1)
                return self.report()
            self.attempts += 1
            self._in_flight = "tool_cycle"
            self._persist()
            if self._real:
                remaining = number(self.timeout_s) - (self.clock() - self.started + self._elapsed_offset)
                previous_deadline = self.controller.execution_deadline
                self.controller.execution_deadline = time.monotonic() + remaining
                try:
                    outcome = self.controller.run_once(project, params=self.params, include_uart=self.include_uart)
                finally:
                    self.controller.execution_deadline = previous_deadline
                self.pending_execution = None
                self._execution_authorized = False
            else:
                self.controller._event_attempt_offset = self.attempts - 1
                outcome = self.controller.run_once(project, params=self.params)
            self._in_flight = None
            try:
                execution = json.loads(json.dumps(outcome.to_dict(), allow_nan=False))
            except (TypeError, ValueError):
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Tool evidence must be finite JSON data.") from None
            self.cycles.append({"attempt": self.attempts, "execution": execution})
            self._require(outcome)
            self._time_check()
            if outcome.data.get("decision") == "PASS":
                self._finish("PASS", "SELECTED_PHYSICAL_CHECKS_PASSED" if self._real else "PHYSICAL_CHECKS_PASSED_IN_MOCK")
                return self.report()
            if outcome.data.get("reason") not in ("BUILD_FAILED", "ATTEMPTS_EXHAUSTED"):
                self._finish("FAIL", outcome.data.get("reason", "TOOL_CHAIN_FAILED"))
                return self.report()
            if self.attempts >= limit:
                self._finish("FAIL", "ATTEMPTS_EXHAUSTED")
                return self.report()
            if sources != self._require(self.editor.snapshot())["sources"]:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Source changed during the tool cycle.")
            self.events.emit("ANALYZING", attempt=self.attempts)
            proposal = self.agent.decide(self.task, {
                "goal": self.params, "attempt": self.attempts,
                "observed_gpio": self.observed_gpio,
                "evidence_source": "real" if self._real else "mock",
                "verification_scope": "gpio_period_and_uart_capture" if self.include_uart else "gpio_period_only",
                "execution": outcome.to_dict(),
            }, sources, timeout_s=number(self.timeout_s) - (self.clock() - self.started + self._elapsed_offset))
            decision = self._require(proposal)["decision"]
            self.cycles[-1]["model_decision"] = decision
            self.events.emit("ANALYSIS_FINISHED", attempt=self.attempts)
            self._time_check()
            if decision["action"] == "stop":
                self._finish("STOPPED", "MODEL_REQUESTED_STOP")
                return self.report()
            self.pending = self._require(self.editor.preview(decision["edit"]))
            self.pending["reason"] = decision["reason"]
            self.state, self.reason = "AWAITING_APPROVAL", "SOURCE_EDIT_REQUIRES_HUMAN"
            self.events.emit("WAITING_APPROVAL", attempt=self.attempts)
            return self.report()
        return self._guard(operation)

    def review_execution(self, proposal_id: str, fingerprint: str, *, approved: bool) -> OperationResult:
        """Trusted human UI only. No hardware operation runs during this call."""
        def operation():
            self._time_check()
            if not self._real or self.state != "AWAITING_EXECUTION_APPROVAL" or self.pending_execution is None:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "No real cycle is awaiting review.")
            expected = self.pending_execution
            if (proposal_id, fingerprint) != (expected["proposal_id"], expected["fingerprint"]):
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Review does not match the pending real cycle.")
            reviewed = self.controller.review_cycle(proposal_id, fingerprint, approved=approved)
            self._record_review("cycle", expected, approved, reviewed.error_code)
            self._require(reviewed)
            self._execution_authorized = True
            self.state, self.reason = "READY", "REAL_CYCLE_APPROVED"
            return self.report()
        return self._guard(operation)

    def review_edit(self, proposal_id: str, fingerprint: str, *, approved: bool) -> OperationResult:
        """Trusted human UI only; never register this method as a model tool."""
        def operation():
            self._time_check()
            if self.state != "AWAITING_APPROVAL" or self.pending is None:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "No source edit is awaiting review.")
            if proposal_id != self.pending["proposal_id"] or fingerprint != self.pending["fingerprint"]:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Review does not match the current edit.")
            decision = self.editor.approvals.decide(proposal_id, fingerprint, approved=approved)
            self._record_review("source_diff", self.pending, approved, decision.error_code)
            self._require(decision)
            self._in_flight = "source_edit"
            self._persist()
            self.events.emit("APPLYING_EDIT", attempt=self.attempts)
            applied = self._require(self.editor.apply(proposal_id))
            self._in_flight = None
            self.cycles[-1]["applied_edit"] = applied
            self.pending = None
            self.state, self.reason = "READY", "APPROVED_SOURCE_CHANGED"
            self.events.emit("EDIT_APPLIED", attempt=self.attempts)
            return self.report()
        return self._guard(operation)

    def cancel(self) -> OperationResult:
        def operation():
            if self.state not in TERMINAL:
                self._finish("STOPPED", "HUMAN_CANCELLED")
            return self.report()
        return self._guard(operation)
