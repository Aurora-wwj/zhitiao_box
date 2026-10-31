"""Explicit CLI entry points; no network access by default."""

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .agent import Agent
from .config import NICECODE_BASE_URL, NICECODE_MODEL, NiceCodeConfig
from .controller import Controller
from .errors import AgentError, ErrorCode
from .models import invoke
from .nicecode import NiceCodeClient, OpenAIChatAdapter, OpenAIResponsesAdapter
from .tools.mock_backend import MockBackend
from .real_cli import real_operation
from .demo import run_agent_demo


def _model_client(protocol):
    if protocol is None:
        raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Explicitly select a protocol confirmed by the provider documentation.")
    if not os.environ.get("NICECODE_API_KEY"):
        raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Require NICECODE_API_KEY in the process environment.")
    config = NiceCodeConfig(
        base_url=os.environ.get("NICECODE_BASE_URL", NICECODE_BASE_URL),
        model=os.environ.get("NICECODE_MODEL", NICECODE_MODEL),
        api_key=os.environ["NICECODE_API_KEY"],
    )
    adapter = OpenAIResponsesAdapter() if protocol == "openai-responses" else OpenAIChatAdapter()
    return NiceCodeClient(config, adapter=adapter)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Zhidiao Agent (Python 3.13+)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    mock = subparsers.add_parser("mock", help="Run an offline simulated hardware workflow")
    mock.add_argument("--project", help="Absolute mock project path within the current directory")
    suggest = subparsers.add_parser("suggest", help="Request an AI suggestion without executing it")
    suggest.add_argument("task")
    suggest.add_argument("--protocol", choices=("openai-chat", "openai-responses"))
    suggest.add_argument("--allow-network", action="store_true")
    demo = subparsers.add_parser("agent-demo", help="Simulated 800ms -> reviewed source edit -> 1001ms loop")
    demo.add_argument("--allow-network", action="store_true", help="Use NiceCode for decisions; tools remain mock")
    demo.add_argument("--protocol", choices=("openai-chat", "openai-responses"))
    for name in ("real-build", "real-flash"):
        real = subparsers.add_parser(name, help="Preview and individually approve a real operation")
        real.add_argument("path", help="Absolute project or firmware path")
        real.add_argument("--config", required=True, help="Non-secret local deployment JSON")
        real.add_argument("--preview-only", action="store_true", help="Print the plan without executing")
    real_test = subparsers.add_parser("real-test", help="Preview and approve an independent real PL GPIO measurement")
    real_test.add_argument("--config", required=True)
    real_test.add_argument("--expected-period-ms", type=float, required=True)
    real_test.add_argument("--tolerance-ms", type=float, required=True)
    real_test.add_argument("--preview-only", action="store_true")
    real_log = subparsers.add_parser("real-log", help="Preview and approve real UART capture if a reader is connected")
    real_log.add_argument("--config", required=True)
    real_log.add_argument("--duration-s", type=float, default=5)
    real_log.add_argument("--preview-only", action="store_true")
    agent_run = subparsers.add_parser("agent-run", help="Review a natural-language goal and each real edit/verification cycle")
    agent_run.add_argument("task", nargs="?", help="Natural-language complete GPIO period and tolerance")
    agent_run.add_argument("--config", required=True)
    agent_run.add_argument("--project", required=True, help="Absolute trusted Keil project directory")
    agent_run.add_argument("--source", required=True, action="append", help="Explicit project-relative UTF-8 source allowlist; repeatable")
    agent_run.add_argument("--protocol", choices=("openai-chat", "openai-responses"))
    agent_run.add_argument("--allow-network", action="store_true")
    agent_run.add_argument("--pl-only", action="store_true", help="Explicitly skip UART; a PL-only PASS makes no UART claim")
    agent_run.add_argument("--max-attempts", type=int, choices=(1, 2, 3), default=3)
    agent_run.add_argument("--timeout-s", type=float, default=300)
    agent_run.add_argument("--report-dir", help="Directory for durable run snapshots")
    agent_run.add_argument("--resume-report", help="Prior report to review; old approvals are never restored")
    agent_run.add_argument("--strict-approval", action="store_true", help="Review every hardware cycle; default is session scope plus each source diff")
    setup = subparsers.add_parser("deployment-setup", help="Preview and approve a new deployment profile")
    setup.add_argument("--project", required=True)
    setup.add_argument("--keil", required=True, help="Absolute Keil executable path")
    setup.add_argument("--known-hosts", required=True)
    setup.add_argument("--identity")
    setup.add_argument("--project-file")
    setup.add_argument("--target")
    setup.add_argument("--host", default="192.168.10.2")
    setup.add_argument("--port", type=int, default=22)
    setup.add_argument("--user", default="root")
    setup.add_argument("--observed-gpio", default="PA1")
    setup.add_argument("--output", default="deployment.local.json")
    setup.add_argument("--check-remote", action="store_true")
    setup.add_argument("--preview-only", action="store_true")
    diagnostics = subparsers.add_parser("deployment-check", help="Preview and approve read-only deployment diagnostics")
    diagnostics.add_argument("--config", required=True)
    diagnostics.add_argument("--preview-only", action="store_true")
    report = subparsers.add_parser("report", help="Read a durable run report without restoring approvals")
    report.add_argument("filename")
    serve = subparsers.add_parser("serve", help="Open a local browser UI at 127.0.0.1; review every action")
    serve.add_argument("--config", required=True)
    serve.add_argument("--project", required=True)
    serve.add_argument("--source", required=True, action="append")
    serve.add_argument("--protocol", choices=("openai-chat", "openai-responses"))
    serve.add_argument("--allow-network", action="store_true")
    serve.add_argument("--pl-only", action="store_true")
    serve.add_argument("--max-attempts", type=int, choices=(1, 2, 3), default=3)
    serve.add_argument("--timeout-s", type=float, default=300)
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--report-dir")
    serve.add_argument("--strict-approval", action="store_true")
    serve.add_argument("--open-browser", action="store_true")
    ui = subparsers.add_parser("ui", help="Native PC launcher and local control panel")
    ui.add_argument("--config", default="deployment.local.json")
    ui_modes = ui.add_mutually_exclusive_group()
    ui_modes.add_argument("--demo", action="store_true")
    ui_modes.add_argument("--mock-hardware", action="store_true")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-browser", action="store_true")
    demo_ui = subparsers.add_parser("serve-demo", help="Offline browser UI with mock model and tools only")
    demo_ui.add_argument("--port", type=int, default=8765)
    demo_ui.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    if args.command in {"ui", "serve-demo"}:
        from .desktop import launch
        result = launch(config_path=getattr(args, "config", "deployment.local.json"),
                        demo=args.command == "serve-demo" or args.demo,
                        mock_hardware=getattr(args, "mock_hardware", False),
                        port=args.port, open_browser=not args.no_browser)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.success else 1

    if args.command in ("deployment-setup", "deployment-check", "report"):
        def local_operation():
            if args.command == "deployment-setup":
                from .setup_cli import run_setup
                result = run_setup(
                    project_path=args.project, keil_executable=args.keil, known_hosts=args.known_hosts,
                    identity_file=args.identity, project_file=args.project_file, target=args.target,
                    host=args.host, port=args.port, user=args.user, observed_gpio=args.observed_gpio,
                    output_path=args.output, check_remote=args.check_remote, preview_only=args.preview_only,
                )
            elif args.command == "deployment-check":
                from .setup_cli import run_diagnostics
                result = run_diagnostics(args.config, preview_only=args.preview_only)
            else:
                from .reports import read_report
                result = read_report(args.filename)
            return {"outcome": result}
        prepared = invoke(local_operation, backend="cli")
        result = prepared.data["outcome"] if prepared.success else prepared
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        failed_checks = result.data.get("decision") in {"NOT_READY", "INCOMPLETE"}
        local_checks = result.data.get("params", {}).get("local", {})
        failed_checks = failed_checks or local_checks.get("local_ready") is False
        return 0 if result.success and not failed_checks else 1

    if args.command == "serve":
        def serve_operation():
            if not args.allow_network:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "A real model request requires --allow-network.")
            if args.protocol is None:
                raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Explicitly select the documented model protocol.")
            from .web_ui import WebUIService, run_server
            service = WebUIService(
                config_path=args.config, project_path=args.project, source_files=tuple(args.source),
                client_factory=lambda: _model_client(args.protocol), include_uart=not args.pl_only,
                max_attempts=args.max_attempts, timeout_s=args.timeout_s, report_dir=args.report_dir,
                strict_approval=args.strict_approval,
            )
            return {"outcome": run_server(service, port=args.port, open_browser=args.open_browser)}
        prepared = invoke(serve_operation, backend="web_ui")
        result = prepared.data["outcome"] if prepared.success else prepared
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.success else 1

    if args.command in ("real-build", "real-flash"):
        result = real_operation(args.command, args.config, args.path, preview_only=args.preview_only)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.success else 1

    if args.command in ("real-test", "real-log"):
        result = real_operation(
            args.command, args.config, preview_only=args.preview_only,
            duration_s=args.duration_s if args.command == "real-log" else 5,
            params={"expected_period_ms": args.expected_period_ms, "tolerance_ms": args.tolerance_ms}
            if args.command == "real-test" else None,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.success and result.data.get("passed", True) else 1

    if args.command == "agent-run":
        def workflow_operation():
            if not args.allow_network:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "A real model request requires --allow-network.")
            if args.protocol is None:
                raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Explicitly select the documented model protocol.")
            from .workflow_cli import run_agent_workflow
            return {"outcome": run_agent_workflow(
                args.task, config_path=args.config, project_path=args.project,
                source_files=tuple(args.source), client_factory=lambda: _model_client(args.protocol),
                include_uart=not args.pl_only, max_attempts=args.max_attempts, timeout_s=args.timeout_s,
                report_dir=args.report_dir, resume_report_path=args.resume_report,
                strict_approval=args.strict_approval,
            )}
        prepared = invoke(workflow_operation, backend="agent_run")
        result = prepared.data["outcome"] if prepared.success else prepared
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.success and result.data.get("decision") == "PASS" else 1

    if args.command == "agent-demo":
        def demo_operation():
            if args.protocol and not args.allow_network:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "A real model request requires --allow-network.")
            client = _model_client(args.protocol) if args.allow_network else None
            return {"outcome": run_agent_demo(client)}
        prepared = invoke(demo_operation, backend="agent_demo")
        result = prepared.data["outcome"] if prepared.success else prepared
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.success and result.data.get("decision") == "PASS" else 1

    def operation() -> dict[str, Any]:
        if args.command == "mock":
            root = Path.cwd().resolve()
            result = Controller(MockBackend(), allowed_roots=(str(root),)).run(
                args.project if args.project else str(root / "mock_project"),
            )
        else:
            if not args.allow_network:
                raise AgentError(
                    ErrorCode.APPROVAL_REQUIRED,
                    "A real model request requires the explicit --allow-network flag.",
                )
            result = Agent(_model_client(args.protocol)).suggest(args.task)
        if not result.success:
            try:
                code = ErrorCode(result.error_code)
            except ValueError:
                code = ErrorCode.INTERNAL_ERROR
            raise AgentError(code, result.message, status_code=result.data.get("status_code"))
        return result.data

    result = invoke(operation, backend="cli")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.success and result.data.get("decision", "PASS") == "PASS" else 1
