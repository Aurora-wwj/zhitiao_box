"""Human-led natural-language task entry above the reviewed real orchestrator."""

import sys
import time
from dataclasses import replace
from pathlib import Path

from .agent import Agent
from .approval import ApprovalGate
from .approval_ui import human_review, _terminal
from .controller import ReviewedController
from .deployment import DeploymentConfig
from .editing import SourceEditor
from .errors import AgentError, ErrorCode
from .goals import GoalInterpreter, validate_task_gpio
from .models import OperationResult, invoke
from .observations import number
from .orchestrator import Orchestrator
from .reports import RunStore, read_report
from .provenance import describe_model
from .task_audit import TaskAudit
from .session import SessionScope
from .tools.real_backend import RealBackend


def _require(result: OperationResult) -> dict:
    if not isinstance(result, OperationResult):
        raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid workflow component result.")
    if not result.success:
        try:
            code = ErrorCode(result.error_code)
        except ValueError:
            code = ErrorCode.INTERNAL_ERROR
        raise AgentError(code, result.message, status_code=result.data.get("status_code"))
    return result.data


def _confirm(action: str, params: dict, title: str, *, audit=None) -> None:
    """Bind even task/context consent to the exact currently displayed values."""
    gate = ApprovalGate()
    preview = _require(gate.propose(action, params))
    if audit is not None:
        audit.save("AWAITING_CONTEXT_APPROVAL" if action == "share_selected_context" else "AWAITING_GOAL_APPROVAL")
    result = human_review(preview, title=title)
    if audit is not None:
        approved = result.data.get("approved") if result.success else None
        audit.record_review(action, preview, approved=approved,
                            error_code=result.error_code or ("APPROVAL_REJECTED" if approved is False else None))
    review = _require(result)
    _require(gate.decide(preview["proposal_id"], preview["fingerprint"], approved=review["approved"]))
    _require(gate.consume(preview["proposal_id"], action, params))


def run_agent_workflow(
    task: str | None, *, config_path: str, project_path: str, source_files: tuple[str, ...],
    client_factory, include_uart: bool = True, max_attempts: int = 3, timeout_s: float = 300,
    report_dir: str | None = None, resume_report_path: str | None = None,
    strict_approval: bool = True,
) -> OperationResult:
    """No model traffic or physical operation before the corresponding review.

    client_factory is deferred until local preflight and source-sharing consent.
    No --yes bypass exists; semantic chaining derives exact cycle permissions
    only from a reviewed session and each individually reviewed source diff.
    """
    audit, loop = None, None

    def operation():
        nonlocal audit, loop
        if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "max_attempts must be 1 to 3.")
        budget = number(timeout_s)
        if budget > 1800 or type(include_uart) is not bool or type(strict_approval) is not bool:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid workflow timeout or observation mode.")
        started = time.monotonic()

        def remaining():
            value = budget - (time.monotonic() - started)
            if value <= 0:
                raise AgentError(ErrorCode.TIMEOUT, "Agent workflow time budget exhausted.")
            return value
        if not source_files or len(set(source_files)) != len(source_files):
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Select distinct explicit source files.")
        config = DeploymentConfig.load(config_path)
        project = config.local_path(project_path)
        if not project.is_dir():
            raise AgentError(ErrorCode.PROJECT_NOT_FOUND, "Require an existing project directory.")
        report_path = (Path(report_dir) if report_dir is not None else Path.cwd() / ".zhidiao" / "runs").absolute()
        if any(part.casefold() in {".git", ".codex", ".agents"} for part in report_path.parts):
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Run reports must not overwrite Git or Agent metadata.")
        report_root = report_path.resolve()
        if report_root.is_relative_to(project) and not report_root.is_relative_to(project / ".zhidiao"):
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Reports inside the project must stay under .zhidiao.")
        recovery = _require(read_report(resume_report_path))["report"] if resume_report_path is not None else None
        if recovery is not None and recovery.get("report_stage") == "task_entry":
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Task-entry reports are read-only; start a new task.")
        store = RunStore(str(report_path))
        _require(store.list_runs())
        editor = SourceEditor(str(project), source_files)
        sources = _require(editor.snapshot())["sources"]
        backend = RealBackend(config)
        # These only inspect local configuration and construct plans. No SSH,
        # compiler, model request, or register access is performed by preflight.
        _require(backend.preview_build(str(project)))
        observation = _require(backend.preview_observation())
        if observation.get("period_available") is False:
            raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "PL period reader is not connected.")
        if include_uart:
            _require(backend.preview_observation("read_target_log", 5))
        observed_gpio = config.observer.observed_gpio
        if task is None and recovery is not None:
            task_text = recovery.get("metadata", {}).get("task")
        elif task is None:
            if not sys.stdin.isatty():
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Enter a task from an interactive terminal.")
            try:
                task_text = input("请输入 GPIO 完整周期目标和允许误差：").strip()
            except (EOFError, KeyboardInterrupt):
                raise AgentError(ErrorCode.CANCELLED, "Task entry cancelled.") from None
        else:
            task_text = task
        if not isinstance(task_text, str) or not task_text.strip():
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require a natural-language task.")
        try:
            if len(task_text) > 4000:
                raise ValueError()
            task_text.encode("utf-8")
        except (ValueError, UnicodeError):
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require a UTF-8 task of 1–4000 characters.") from None
        audit = TaskAudit(store, task=task_text, project_path=str(project),
            source_files={name: {"sha256": row["sha256"]} for name, row in sources.items()},
            observed_gpio=observed_gpio, include_uart=include_uart, max_attempts=max_attempts,
            timeout_s=budget, model_info=describe_model(),
            resume_from=recovery.get("run_id") if recovery is not None else None)
        validate_task_gpio(task_text, observed_gpio)
        remaining()
        _confirm("share_selected_context", {
            "task": task_text, "project_path": str(project),
            "observed_gpio": observed_gpio,
            "source_files": {name: {"sha256": row["sha256"]} for name, row in sources.items()},
            "effects": "向已配置的 NiceCode 模型发送任务、所选源码、编译日志和每轮观测证据；不把 SSH 私钥或 API Key 放入模型上下文。",
            "observation_mode": "UART + PL" if include_uart else "仅 PL；不采集 UART，不证明 UART 行为。",
        }, "确认发送范围：后续模型只能建议修改这些源码；每次源码 diff 仍需批准，随后确认任务执行范围。", audit=audit)
        audit.context_sharing_approved = True
        if sources != _require(editor.snapshot())["sources"]:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Selected source changed after sharing consent; review the context again.")
        remaining()
        audit.save("ANALYZING_GOAL")
        client = client_factory()
        audit.model_info = describe_model(client)
        audit.save("ANALYZING_GOAL")
        interpreter = GoalInterpreter(client, observed_gpio=observed_gpio)
        conversation = []
        audit.clarifications = conversation
        for turn in range(4):
            interpreted = _require(interpreter.interpret(task_text, clarifications=tuple(conversation), timeout_s=remaining()))
            audit.goal = interpreted
            remaining()
            if interpreted.get("status") != "clarification":
                break
            if turn == 3 or not sys.stdin.isatty():
                return {"decision": "NEEDS_CLARIFICATION", "question": interpreted["question"],
                        "observed_gpio": observed_gpio, "clarifications": conversation,
                        "evidence_source": "none", "attempts": 0,
                        "report": audit.save("NEEDS_CLARIFICATION")}
            audit.save("NEEDS_CLARIFICATION")
            print("需要补充：" + _terminal(interpreted["question"]), file=sys.stderr, flush=True)
            try:
                answer = input("请补充目标（输入 取消 / cancel 结束）：").strip()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            remaining()
            if not answer or answer.casefold() in {"取消", "cancel", "stop"}:
                raise AgentError(ErrorCode.CANCELLED, "Goal clarification cancelled.")
            if len(answer) > 1000:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Clarification answer is too long.")
            validate_task_gpio(answer, observed_gpio)
            conversation.append({"question": interpreted["question"], "answer": answer})
        if (interpreted.get("status") != "ready" or interpreted.get("test_id") != "gpio_period"
                or interpreted.get("observed_gpio") != observed_gpio):
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Goal interpreter did not return a supported target.")
        params = interpreted["params"]
        _require(backend.preview_observation("run_hardware_test", "gpio_period", params))
        goal_preview = {
            "task": task_text, "test_id": "gpio_period", "params": params,
            "observed_gpio": observed_gpio, "clarifications": conversation,
            "summary": interpreted["summary"], "max_attempts": max_attempts,
            "timeout_s": budget, "project_path": str(project),
            "target_host": config.host, "target_user": config.user,
            "observation_mode": "UART + PL" if include_uart else "PL-only (UART skipped explicitly)",
            "pass_rule": "abs(measured_period_ms - expected_period_ms) <= tolerance_ms，由确定性程序判定。",
        }
        if strict_approval:
            _confirm("confirm_goal", goal_preview, "确认模型理解的完整周期和误差；确认目标后尚不会自动执行硬件操作。", audit=audit)
        if sources != _require(editor.snapshot())["sources"]:
            raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Selected source changed during goal review; review the context again.")
        remaining()
        controller = ReviewedController(backend, allowed_roots=config.allowed_roots, max_attempts=max_attempts)
        resolved_task = task_text
        if conversation:
            resolved_task += "\n用户补充：\n" + "\n".join(row["answer"] for row in conversation)
        loop = Orchestrator(controller, Agent(client), editor, task=resolved_task,
                            project_path=str(project), params=params, timeout_s=remaining(),
                            include_uart=include_uart, report_store=store, recovery_report=recovery,
                            model_info=audit.model_info, run_id=audit.run_id, task_entry=audit.context())
        scope = None
        if not strict_approval:
            scope = SessionScope(loop)
            preview = _require(scope.preview())
            review = _require(human_review(preview, title="批准本次任务范围并开始：基线 build/flash/UART/PL 自动执行；每次新源码 diff 仍需人工批准。"))
            audit.record_review("session", preview, approved=review["approved"],
                                error_code=None if review["approved"] else "APPROVAL_REJECTED")
            loop.task_entry = audit.context()
            _require(scope.review_scope(preview["proposal_id"], preview["fingerprint"], approved=review["approved"]))
        while True:
            result = loop.advance()
            if not result.success:
                return {"outcome": result}
            state = result.data["decision"]
            if state == "AWAITING_APPROVAL":
                preview = result.data["pending_edit"]
                title = ("批准修改并重新验证：仅应用这个 diff，然后自动重新 build/flash/UART/PL。" if scope is not None else
                         "审批源码修改：查看理由和完整 diff；批准只应用该差异，硬件验证会另行审批。")
                review_method = scope.review_edit if scope is not None else loop.review_edit
            elif state == "AWAITING_EXECUTION_APPROVAL":
                if scope is not None:
                    allowed = scope.approve_cycle()
                    if not allowed.success:
                        loop.cancel()
                        return {"outcome": allowed}
                    continue
                preview = result.data["pending_execution"]
                title = "审批本轮真实验证：Keil 构建 → 上传与 SHA-256 核对 → 烧录/校验/复位 → 观测。"
                review_method = loop.review_execution
            else:
                return {"outcome": result}
            review = human_review(preview, title=title)
            if not review.success:
                return {"outcome": OperationResult(
                    False, review.error_code, review.message, "agent_run", data={"report": loop.report()},
                )}
            result = review_method(preview["proposal_id"], preview["fingerprint"], approved=review.data["approved"])
            if not result.success:
                return {"outcome": result}

    prepared = invoke(operation, backend="agent_run")
    result = prepared.data.get("outcome", prepared) if prepared.success else prepared
    if not result.success and audit is not None:
        audit.record_error(result)
        if loop is not None:
            loop.task_entry = audit.context()
            cleanup = invoke(lambda: {"report": _require(loop.cancel())}, backend="run_report")
        else:
            cleanup = invoke(lambda: {"report": audit.save("STOPPED", reason=result.error_code)}, backend="run_report")
        if cleanup.success:
            result = replace(result, data={**result.data, "report": cleanup.data["report"]})
        else:
            result = replace(cleanup, data={"report": loop.report() if loop is not None else audit.render("STOPPED", reason=result.error_code),
                                           "original_error_code": result.error_code})
    if loop is not None:
        loop.controller.close_status_indicator()
    return result
