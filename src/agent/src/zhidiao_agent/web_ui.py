"""Loopback browser UI for a single, explicitly reviewed hardware run.

Browser requests never supply deployment paths, commands, or approval payloads.
The operator selects those when starting the server. Only this trusted UI owns
the human review methods; no HTTP endpoint is registered as an LLM tool.
"""

import hmac
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .agent import Agent
from .approval import ApprovalGate
from .controller import ReviewedController
from .deployment import DeploymentConfig
from .editing import SourceEditor
from .errors import AgentError, ErrorCode
from .goals import GoalInterpreter, validate_task_gpio
from .models import OperationResult, invoke
from .observations import number
from .orchestrator import Orchestrator, TERMINAL
from .reports import RunStore
from .provenance import describe_model
from .task_audit import TaskAudit
from .events import WorkflowEvents
from .presentation import view_model
from .session import SessionScope
from .tools.commands import ProcessRunner
from .tools.real_backend import RealBackend


from .ui_page import HTML


def _require(result: OperationResult) -> dict:
    if not isinstance(result, OperationResult):
        raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid UI component result.")
    if not result.success:
        try:
            code = ErrorCode(result.error_code)
        except (ValueError, TypeError):
            code = ErrorCode.INTERNAL_ERROR
        raise AgentError(code, result.message, status_code=result.data.get("status_code"))
    return result.data


def _clone(value):
    return json.loads(json.dumps(value, allow_nan=False))


def _text(value, maximum: int, message: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise AgentError(ErrorCode.INVALID_ARGUMENT, message)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "User text must be valid Unicode.") from None
    return value


class _CancellableRunner:
    """Cancel owned local process trees and stop before subsequent commands."""

    def __init__(self, check, cancel_event):
        self._check = check
        self._runner = ProcessRunner(cancel_event=cancel_event)

    def run(self, argv, timeout_s):
        remaining = self._check()
        outcome = self._runner.run(argv, min(timeout_s, remaining))
        self._check()
        return outcome


class WebUIService:
    """A single-session service; network/model work uses one worker thread.

    Cancellation stops local subprocesses and prevents the next model/tool stage.
    Shutdown waits for the worker to finish cleanup and persist its final state.
    It does not claim to abort a remote OpenOCD already running on the board.
    """

    def __init__(self, config_path: str, project_path: str, source_files: tuple[str, ...],
                 client_factory, *, include_uart: bool = True, max_attempts: int = 3,
                 timeout_s: float = 300, report_dir: str | None = None, strict_approval: bool = True,
                 model_info: dict | None = None):
        self.config_path, self.project_path = config_path, project_path
        self.source_files, self.client_factory = source_files, client_factory
        self.include_uart, self.max_attempts, self.timeout_s = include_uart, max_attempts, timeout_s
        self.strict_approval = strict_approval
        self._events = WorkflowEvents()
        self._session = None
        self._model_info = describe_model(hint=model_info)
        self._entry = None
        self.report_dir = report_dir if report_dir is not None else ".zhidiao/runs"
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._closing = False
        self._cleanup_failure = None
        self._worker = None
        self._busy, self._phase = False, "IDLE"
        self._pending, self._question, self._report, self._last_result = None, None, {}, None
        self._scope = {"project_path": project_path, "source_files": list(source_files),
                       "observation_mode": "UART + PL" if include_uart else "PL-only (UART skipped)",
                       "include_uart": include_uart, "max_attempts": max_attempts, "evidence_source": "real",
                       "timeout_s": timeout_s,
                       "approval_mode": "strict" if strict_approval else "semantic"}
        self._started = None
        self._loop = None
        self._gate = ApprovalGate()
        self._client = None
        self._clarifications = []
        self._task = ""
        self._goal = None
        self._recovery_report = None
        self._preflight = invoke(self._prepare, backend="web_ui")

    def _prepare(self):
        budget = number(self.timeout_s)
        if budget > 1800 or type(self.include_uart) is not bool or type(self.strict_approval) is not bool:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid workflow timeout or mode.")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "max_attempts must be 1 to 3.")
        if not self.source_files or len(set(self.source_files)) != len(self.source_files):
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Select distinct source files.")
        self._config = DeploymentConfig.load(self.config_path)
        project = self._config.local_path(self.project_path)
        if not project.is_dir():
            raise AgentError(ErrorCode.PROJECT_NOT_FOUND, "Require an existing project directory.")
        self._editor = SourceEditor(str(project), self.source_files)
        report_root = Path(self.report_dir).absolute()
        resolved_report_root = report_root.resolve()
        if resolved_report_root.is_relative_to(project) and not resolved_report_root.is_relative_to(project / ".zhidiao"):
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Reports inside the project must stay in .zhidiao.")
        self._report_store = RunStore(str(report_root))
        _require(self._report_store.list_runs())
        self._sources = _require(self._editor.snapshot())["sources"]
        self._backend = RealBackend(self._config, runner=_CancellableRunner(self._check, self._cancel))
        _require(self._backend.preview_build(str(project)))
        observation = _require(self._backend.preview_observation())
        if observation.get("period_available") is False:
            raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "PL period reader is not connected.")
        if self.include_uart:
            _require(self._backend.preview_observation("read_target_log", 5))
        pin = self._config.observer.observed_gpio if self._config.observer is not None else "PA1"
        self._scope.update({"project_path": str(project), "target_host": self._config.host,
                            "target": self._config.target,
                            "observed_gpio": pin,
                            "source_files": {name: {"sha256": row["sha256"]}
                                             for name, row in self._sources.items()}})
        if self._config.uart_observer is not None:
            self._scope["uart_channel"] = self._config.uart_observer.stm32_tx_gpio + " → " + self._config.uart_observer.pl_rx_pin
        return {"ready": True}

    def _check(self):
        if self._cancel.is_set():
            raise AgentError(ErrorCode.CANCELLED, "Human requested the run to stop.")
        remaining = number(self.timeout_s) if self._started is None else (
            number(self.timeout_s) - (time.monotonic() - self._started))
        if remaining <= 0:
            raise AgentError(ErrorCode.TIMEOUT, "User workflow time budget exhausted.")
        return remaining

    def _set(self, *, phase, pending=None, question=None, report=None):
        with self._lock:
            self._phase, self._pending, self._question = phase, _clone(pending), question
            if report is not None:
                self._report = _clone(report)

    def _start_entry(self, *, resume_from=None):
        self._entry = TaskAudit(self._report_store, task=self._task,
            project_path=self._scope["project_path"], source_files=self._scope["source_files"],
            observed_gpio=self._scope["observed_gpio"], include_uart=self.include_uart,
            max_attempts=self.max_attempts, timeout_s=self.timeout_s,
            model_info=self._model_info, resume_from=resume_from, context_sharing_approved=True)

    def _save_entry(self, phase):
        if self._entry is not None:
            self._entry.goal = _clone(self._goal)
            self._entry.clarifications = _clone(self._clarifications)
            report = self._entry.save(phase, events=self._events.snapshot())
            if self._loop is None:
                with self._lock:
                    self._report = report

    def _create_client(self):
        self._client = self.client_factory()
        self._model_info = describe_model(self._client, hint=self._model_info
                                         if self._model_info["source"] != "uninitialized" else None)
        self._scope["model_info"] = _clone(self._model_info)
        self._scope["model"] = self._model_info["requested_model"]
        if self._entry is not None:
            self._entry.model_info = dict(self._model_info)

    def snapshot(self) -> OperationResult:
        def operation():
            with self._lock:
                events = self._events.snapshot()
                return {"state": _clone({
                    "phase": self._phase, "busy": self._busy, "scope": self._scope,
                    "task": self._task, "pending": self._pending, "question": self._question,
                    "report": self._report, "last_result": self._last_result,
                    "cancel_requested": self._cancel.is_set(),
                    "closing": self._closing,
                    "preflight": self._preflight.to_dict(),
                    "events": events,
                    "view": view_model(phase=self._phase, scope=self._scope, report=self._report,
                                       pending=self._pending, events=events, goal=self._goal,
                                       last_result=self._last_result, busy=self._busy),
                })}
        return invoke(operation, backend="web_ui")

    def _schedule(self, operation, *, phases=None, reset_cancel=False) -> OperationResult:
        def enqueue():
            with self._lock:
                if self._closing:
                    raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "Local UI is closing; new operations are disabled.")
                if self._busy:
                    raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Another UI operation is in progress.")
                if phases is not None and self._phase not in phases:
                    raise AgentError(ErrorCode.APPROVAL_REQUIRED, "This action is not available in the current UI state.")
                if reset_cancel:
                    # Clear only before publishing the worker. A concurrent stop
                    # must never be erased later by start()/resume() inside it.
                    self._cancel.clear()
                    self._cleanup_failure = None
                self._busy = True
                def work():
                    prior_phase, prior_entry = self._phase, self._entry
                    result = invoke(operation, backend="web_ui")
                    try:
                        if result.success and self._cancel.is_set() and self._phase not in TERMINAL:
                            result = invoke(self._check, backend="web_ui")
                        if not result.success:
                            if prior_phase in TERMINAL and self._entry is prior_entry:
                                # A rejected new request must not rewrite a
                                # completed run's evidence or failure reason.
                                return
                            report = {"decision": "STOPPED", "reason": result.error_code,
                                      "attempts": 0, "evidence_source": "none"}
                            if self._entry is not None:
                                self._entry.record_error(result)
                                self._entry.goal = _clone(self._goal)
                                self._entry.clarifications = _clone(self._clarifications)
                            if self._pending is not None and self._phase == "AWAITING_GOAL_APPROVAL":
                                self._gate.decide(self._pending["proposal_id"], self._pending["fingerprint"], approved=False)
                            if self._loop is not None:
                                if self._entry is not None:
                                    self._loop.task_entry = self._entry.context()
                                cleanup = invoke(lambda: {"report": _require(self._loop.cancel())}, backend="web_ui")
                                if cleanup.success:
                                    report = cleanup.data["report"]
                                else:
                                    report = self._loop.report()
                                    result = cleanup
                                    self._cleanup_failure = cleanup
                            elif self._entry is not None:
                                code = result.error_code
                                cleanup = invoke(lambda: {"report": self._entry.save(
                                    "STOPPED", reason=code, events=self._events.snapshot())}, backend="run_report")
                                report = (cleanup.data["report"] if cleanup.success else self._entry.render(
                                    "STOPPED", reason=code, events=self._events.snapshot()))
                                if not cleanup.success:
                                    result = cleanup
                                    self._cleanup_failure = cleanup
                            self._set(phase=report.get("decision") if report.get("decision") in TERMINAL else "STOPPED",
                                      report=report)
                    finally:
                        with self._lock:
                            self._last_result = result.to_dict()
                            self._busy = False
                self._worker = threading.Thread(target=work, name="zhidiao-web-run", daemon=False)
                self._worker.start()
            return {"accepted": True}
        return invoke(enqueue, backend="web_ui")

    def start(self, task: str, *, share_context: bool) -> OperationResult:
        def operation():
            _require(self._preflight)
            _text(task, 4000, "Require a task of 1–4000 characters.")
            if share_context is not True:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Explicit source-sharing consent is required.")
            with self._lock:
                if self._phase not in {"IDLE", *TERMINAL}:
                    raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Finish or cancel the current run first.")
                if self._loop is not None:
                    self._loop.controller.close_status_indicator()
                self._started = time.monotonic()
                self._loop, self._client = None, None
                self._session, self._events = None, WorkflowEvents()
                self._recovery_report = None
                self._gate, self._clarifications = ApprovalGate(), []
                self._task, self._goal = task, None
                self._start_entry()
                self._set(phase="ANALYZING_GOAL", report={"decision": "ANALYZING_GOAL", "attempts": 0})
                self._events.emit("TASK_ACCEPTED")
            self._save_entry("ANALYZING_GOAL")
            self._check()
            validate_task_gpio(task, self._scope["observed_gpio"])
            if self._sources != _require(self._editor.snapshot())["sources"]:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Source changed; restart the UI to review the new sharing scope.")
            self._create_client()
            self._save_entry("ANALYZING_GOAL")
            return self._interpret()
        return self._schedule(operation, phases={"IDLE", *TERMINAL}, reset_cancel=True)

    def _interpret(self):
        goal = _require(GoalInterpreter(self._client, observed_gpio=self._scope["observed_gpio"],
                                       evidence_source=self._scope["evidence_source"]).interpret(
            self._task, clarifications=tuple(self._clarifications), timeout_s=self._check()))
        self._check()
        if goal.get("status") == "clarification":
            if len(self._clarifications) >= 3:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Clarification limit reached; start a new precise task.")
            self._set(phase="NEEDS_CLARIFICATION", question=goal["question"])
            self._save_entry("NEEDS_CLARIFICATION")
            return {"decision": "NEEDS_CLARIFICATION"}
        if goal.get("status") != "ready" or goal.get("observed_gpio") != self._scope["observed_gpio"]:
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Goal does not match the physical observation pin.")
        self._goal = _clone(goal)
        self._events.emit("TARGET_PARSED")
        return self._propose_goal()

    def _new_loop(self):
        controller = ReviewedController(self._backend, allowed_roots=self._config.allowed_roots,
                                        max_attempts=self.max_attempts)
        controller.events = self._events
        return Orchestrator(controller, Agent(self._client), self._editor,
            task=self._task, project_path=self._scope["project_path"], params=self._goal["params"],
            include_uart=self.include_uart,
            timeout_s=(self._recovery_report["metadata"]["timeout_s"] if self._recovery_report is not None else self._check()),
            report_store=self._report_store, recovery_report=self._recovery_report,
            model_info=self._model_info, run_id=self._entry.run_id if self._entry is not None else None,
            task_entry=self._entry.context() if self._entry is not None else None)

    def _validate_goal(self):
        _require(self._backend.preview_observation("run_hardware_test", "gpio_period", self._goal["params"]))

    def _propose_goal(self):
        self._validate_goal()
        self._save_entry("AWAITING_GOAL_APPROVAL")
        if not self.strict_approval:
            self._loop = self._new_loop()
            self._session = SessionScope(self._loop)
            pending = _require(self._session.preview())
            self._set(phase="AWAITING_GOAL_APPROVAL", pending=pending)
            return {"decision": "AWAITING_GOAL_APPROVAL"}
        goal = self._goal
        pending = _require(self._gate.propose("confirm_goal", {
            "task": self._task, "clarifications": self._clarifications,
            "observed_gpio": self._scope["observed_gpio"], "params": goal["params"],
            "summary": goal["summary"], "scope": self._scope,
            "max_attempts": self.max_attempts, "timeout_s": self.timeout_s,
            "pass_rule": "abs(measured_period_ms - expected_period_ms) <= tolerance_ms",
            "resume_from": self._recovery_report["run_id"] if self._recovery_report is not None else None,
        }))
        self._set(phase="AWAITING_GOAL_APPROVAL", pending=pending)
        return {"decision": "AWAITING_GOAL_APPROVAL"}

    def list_runs(self) -> OperationResult:
        if not self._preflight.success:
            return self._preflight
        return self._report_store.list_runs()

    def stored_report(self, run_id: str) -> OperationResult:
        if not self._preflight.success:
            return self._preflight
        return self._report_store.load(run_id)

    def resume(self, run_id: str, *, share_context: bool) -> OperationResult:
        """Load evidence only, then require a new goal and operation review."""
        def operation():
            _require(self._preflight)
            if share_context is not True:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Explicit context-sharing consent is required.")
            with self._lock:
                if self._phase not in {"IDLE", *TERMINAL}:
                    raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Finish or cancel the current run first.")
            saved = _require(self._report_store.load(run_id))["report"]
            if saved.get("report_stage") == "task_entry":
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Task-entry reports are read-only; start a new task.")
            if saved.get("decision") in TERMINAL:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Terminal reports are read-only; start a new reviewed task.")
            metadata = saved.get("metadata", {})
            if (metadata.get("project_path") != self._scope["project_path"]
                    or metadata.get("allowed_sources") != list(self.source_files)
                    or saved.get("observed_gpio") != self._scope["observed_gpio"]
                    or metadata.get("include_uart") is not self.include_uart
                    or saved.get("max_attempts") != self.max_attempts):
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Saved run does not match the fixed UI deployment scope.")
            if not isinstance(metadata.get("task"), str) or not isinstance(metadata.get("goal"), dict):
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Saved run has no supported goal.")
            validate_task_gpio(metadata["task"], self._scope["observed_gpio"])
            with self._lock:
                if self._loop is not None:
                    self._loop.controller.close_status_indicator()
                self._started = time.monotonic()
                self._loop = None
                self._session, self._events = None, WorkflowEvents()
                self._gate, self._clarifications = ApprovalGate(), []
                self._task = metadata["task"]
                self._goal = {"status": "ready", "test_id": "gpio_period", "params": metadata["goal"],
                              "observed_gpio": self._scope["observed_gpio"],
                              "summary": "恢复保存的目标；所有操作必须重新审阅。"}
                self._recovery_report = saved
                self._sources = _require(self._editor.snapshot())["sources"]
                self._scope["source_files"] = {name: {"sha256": row["sha256"]} for name, row in self._sources.items()}
                self._start_entry(resume_from=run_id)
                self._save_entry("AWAITING_GOAL_APPROVAL")
                self._check()
                self._create_client()
            return self._propose_goal()
        return self._schedule(operation, phases={"IDLE", *TERMINAL}, reset_cancel=True)

    def clarify(self, answer: str) -> OperationResult:
        def operation():
            self._check()
            if self._phase != "NEEDS_CLARIFICATION" or not self._question:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "No clarification is awaiting an answer.")
            _text(answer, 1000, "Require a clarification of 1–1000 characters.")
            validate_task_gpio(answer, self._scope["observed_gpio"])
            self._clarifications.append({"question": self._question, "answer": answer})
            self._set(phase="ANALYZING_GOAL")
            self._save_entry("ANALYZING_GOAL")
            return self._interpret()
        return self._schedule(operation, phases={"NEEDS_CLARIFICATION"})

    def _capture_loop(self, result):
        self._check()
        if not result.success:
            self._report = _clone(result.data.get("report", self._loop.report()))
            _require(result)
        report = result.data
        pending = report.get("pending_edit") or report.get("pending_execution")
        self._set(phase=report["decision"], pending=pending, report=report)
        if report["decision"] in TERMINAL:
            sources = _require(self._editor.snapshot())["sources"]
            with self._lock:
                self._sources = sources
                self._scope["source_files"] = {name: {"sha256": row["sha256"]} for name, row in sources.items()}
        return {"decision": report["decision"]}

    def _advance_loop(self):
        # A driver turn executes at most one physical cycle. Semantic mode
        # derives its exact one-time permission from the reviewed session.
        for _ in range(3):
            self._check()
            result = self._loop.advance()
            if (result.success and result.data["decision"] == "AWAITING_EXECUTION_APPROVAL"
                    and self._session is not None):
                _require(self._session.approve_cycle())
                continue
            return self._capture_loop(result)
        raise AgentError(ErrorCode.INTERNAL_ERROR, "Unexpected workflow transition loop.")

    def review(self, proposal_id: str, fingerprint: str, *, approved: bool) -> OperationResult:
        def operation():
            self._check()
            if type(approved) is not bool or not isinstance(proposal_id, str) or not isinstance(fingerprint, str):
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require a review identity and boolean decision.")
            pending = self._pending
            if pending is None or (proposal_id, fingerprint) != (pending["proposal_id"], pending["fingerprint"]):
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Review does not match the displayed proposal.")
            if self._phase == "AWAITING_GOAL_APPROVAL":
                if self._entry is not None:
                    self._entry.record_review("goal", pending, approved=approved,
                        error_code=None if approved else ErrorCode.APPROVAL_REJECTED.value)
                    self._save_entry("AWAITING_GOAL_APPROVAL")
                    if self._loop is not None:
                        self._loop.task_entry = self._entry.context()
                if self._session is not None:
                    _require(self._session.review_scope(proposal_id, fingerprint, approved=approved))
                else:
                    _require(self._gate.decide(proposal_id, fingerprint, approved=approved))
                    _require(self._gate.consume(proposal_id, "confirm_goal", pending["params"]))
                if self._sources != _require(self._editor.snapshot())["sources"]:
                    raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Source changed during goal review; restart the UI.")
                if self._loop is None:
                    self._loop = self._new_loop()
                self._set(phase="RUNNING")
                return self._advance_loop()
            if self._phase == "AWAITING_APPROVAL":
                result = (self._session.review_edit(proposal_id, fingerprint, approved=approved)
                          if self._session is not None else self._loop.review_edit(proposal_id, fingerprint, approved=approved))
            elif self._phase == "AWAITING_EXECUTION_APPROVAL":
                result = self._loop.review_execution(proposal_id, fingerprint, approved=approved)
            else:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "No operation is awaiting review.")
            _require(result)
            self._check()
            self._set(phase="RUNNING")
            return self._advance_loop()
        return self._schedule(operation, phases={"AWAITING_GOAL_APPROVAL", "AWAITING_APPROVAL", "AWAITING_EXECUTION_APPROVAL"})

    def _cancel_idle(self):
        """Finalize only when no worker can concurrently mutate the loop."""
        if self._phase in TERMINAL:
            return {"decision": self._phase}
        if self._pending is not None and self._phase == "AWAITING_GOAL_APPROVAL":
            self._gate.decide(self._pending["proposal_id"], self._pending["fingerprint"], approved=False)
        if self._loop is not None:
            report = _require(self._loop.cancel())
        elif self._entry is not None:
            report = self._entry.save("STOPPED", reason="HUMAN_CANCELLED", events=self._events.snapshot())
        else:
            report = {"decision": "STOPPED", "reason": "HUMAN_CANCELLED", "attempts": 0, "evidence_source": "none"}
        self._set(phase=report["decision"], report=report)
        return {"decision": report["decision"]}

    def cancel(self) -> OperationResult:
        with self._lock:
            self._cancel.set()
            if self._busy or self._closing:
                return OperationResult(True, None, "Stop requested; wait for local cleanup and any bounded model request.",
                                       "web_ui", data={"accepted": True})
            return self._schedule(self._cancel_idle)

    def close(self) -> OperationResult:
        def operation():
            with self._lock:
                self._closing = True
                self._cancel.set()
                worker = self._worker
            if worker is not None:
                # Native commands poll cancellation; native model I/O retains
                # its timeout. Do not abandon the worker while it saves state.
                worker.join()
            try:
                result = self._cancel_idle()
                if self._cleanup_failure is not None:
                    _require(self._cleanup_failure)
                return result
            finally:
                if self._loop is not None:
                    self._loop.controller.close_status_indicator()
        result = invoke(operation, backend="web_ui")
        if not result.success:
            with self._lock:
                self._last_result = result.to_dict()
        return result


def create_server(service: WebUIService, *, port: int = 8765) -> ThreadingHTTPServer:
    """Create a loopback server; the caller owns serve_forever/shutdown."""
    if type(port) is not int or not 0 <= port <= 65535:
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid local UI port.")
    csrf, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, format, *args):
            # Do not place user tasks, model replies, or filesystem paths in logs.
            return

        def _send(self, status, body, content_type="application/json; charset=utf-8", *, attachment=False):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'nonce-" + nonce
                             + "'; style-src 'nonce-" + nonce + "'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            if attachment:
                self.send_header("Content-Disposition", 'attachment; filename="zhidiao-run.json"')
            self.end_headers()
            self.wfile.write(body)

        def _host(self):
            port = self.server.server_address[1]
            host = self.headers.get("Host", "")
            return host if host in {"127.0.0.1:" + str(port), "localhost:" + str(port)} else None

        def _deny(self, code=403, message="Local UI request validation failed."):
            result = OperationResult(False, ErrorCode.APPROVAL_REQUIRED.value, message, "web_ui")
            self._send(code, result.to_dict())

        def do_GET(self):
            if self._host() is None:
                self._deny()
                return
            path = urlsplit(self.path)
            if path.query or path.fragment:
                self._deny(400)
            elif path.path == "/":
                page = HTML.replace("__CSRF__", csrf).replace("__NONCE__", nonce).encode("utf-8")
                self._send(200, page, "text/html; charset=utf-8")
            elif path.path == "/api/state":
                self._send(200, service.snapshot().to_dict())
            elif path.path == "/api/report":
                state = service.snapshot()
                self._send(200, state.data.get("state", {}).get("report", {}), attachment=True)
            elif path.path == "/api/runs":
                result = service.list_runs()
                self._send(200 if result.success else 400, result.to_dict())
            elif path.path.startswith("/api/report/"):
                result = service.stored_report(path.path[len("/api/report/"):])
                self._send(200 if result.success else 400,
                           result.data["report"] if result.success else result.to_dict(), attachment=result.success)
            else:
                self._deny(404, "Unknown local UI route.")

        def do_POST(self):
            host = self._host()
            supplied = self.headers.get("X-CSRF-Token", "")
            if (host is None or self.headers.get("Origin") != "http://" + host
                    or not hmac.compare_digest(supplied.encode("utf-8"), csrf.encode("ascii"))):
                self._deny()
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self._deny(415, "Require an application/json request.")
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    raise ValueError()
                def pairs(items):
                    document = {}
                    for key, value in items:
                        if key in document:
                            raise ValueError()
                        document[key] = value
                    return document
                document = json.loads(self.rfile.read(size), object_pairs_hook=pairs)
                json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8")
                if not isinstance(document, dict):
                    raise ValueError()
            except (ValueError, UnicodeError):
                self._deny(400, "Invalid or oversized local UI JSON.")
                return
            path = urlsplit(self.path)
            fields = {"/api/start": {"task", "share_context"}, "/api/clarify": {"answer"},
                      "/api/review": {"proposal_id", "fingerprint", "approved"}, "/api/cancel": set(),
                      "/api/resume": {"run_id", "share_context"}}
            if path.query or path.fragment or path.path not in fields or set(document) != fields[path.path]:
                self._deny(400, "Unsupported UI action or request fields.")
                return
            if path.path == "/api/start":
                result = service.start(document["task"], share_context=document["share_context"])
            elif path.path == "/api/clarify":
                result = service.clarify(document["answer"])
            elif path.path == "/api/review":
                result = service.review(document["proposal_id"], document["fingerprint"], approved=document["approved"])
            elif path.path == "/api/resume":
                result = service.resume(document["run_id"], share_context=document["share_context"])
            else:
                result = service.cancel()
            self._send(202 if result.success else 409, result.to_dict())

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def run_server(service: WebUIService, *, port: int = 8765, open_browser: bool = False) -> OperationResult:
    def operation():
        server = None
        try:
            server = create_server(service, port=port)
            print("智调 Agent 本地界面：http://127.0.0.1:" + str(server.server_address[1]), flush=True)
            if open_browser:
                try:
                    webbrowser.open("http://127.0.0.1:" + str(server.server_address[1]), new=1)
                except (OSError, webbrowser.Error):
                    print("浏览器未能自动打开，请手动访问上面的本机地址。", flush=True)
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                print("正在停止本地运行并保存最终状态，请等待终端退出。", flush=True)
                _require(service.close())
            finally:
                if server is not None:
                    server.server_close()
        return {"decision": "STOPPED", "reason": "LOCAL_UI_CLOSED"}
    return invoke(operation, backend="web_ui")
