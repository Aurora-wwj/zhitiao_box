"""Small standard-library Windows launcher for the loopback PC control panel.

The native dialog selects trusted deployment paths; the browser never supplies
paths or commands. API keys stay in process memory and are never saved here.
"""

import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import NiceCodeConfig
from .deployment import DeploymentConfig
from .editing import SourceEditor
from .errors import AgentError, ErrorCode
from .models import invoke
from .nicecode import NiceCodeClient, OpenAIResponsesAdapter
from .observations import number
from .web_ui import WebUIService, run_server


@dataclass(frozen=True)
class LaunchSettings:
    config_path: str
    project_path: str
    source_files: tuple[str, ...]
    model: str = "gpt-5.6-sol"
    api_key: str = field(default="", repr=False)
    include_uart: bool = True
    strict_approval: bool = False
    timeout_s: float = 600


@dataclass(frozen=True)
class MockLaunchSettings:
    model: str = "gpt-5.6-sol"
    api_key: str = field(default="", repr=False)
    allow_network: bool = False
    timeout_s: float = 600


def build_mock_service(settings: MockLaunchSettings):
    """Configure the real API without sending it data or constructing hardware."""
    if settings.allow_network is not True:
        raise AgentError(ErrorCode.APPROVAL_REQUIRED, "请先同意本次使用 NiceCode API；请求可能计费。")
    key = settings.api_key or os.environ.get("NICECODE_API_KEY", "")
    if not key.strip():
        raise AgentError(ErrorCode.CONFIGURATION_ERROR, "请输入 NiceCode API Key，或配置 NICECODE_API_KEY。")
    config = NiceCodeConfig(base_url=os.environ.get("NICECODE_BASE_URL", "https://api.nicecode.ai/v1"),
                            model=settings.model, api_key=key, timeout_s=120)
    from .demo_ui import MockHardwareWebUIService
    return MockHardwareWebUIService(
        lambda: NiceCodeClient(config, adapter=OpenAIResponsesAdapter()),
        model_source="nicecode_api", model_name=config.model, timeout_s=settings.timeout_s)


def build_service(settings: LaunchSettings) -> WebUIService:
    key = settings.api_key or os.environ.get("NICECODE_API_KEY", "")
    if not key.strip():
        raise AgentError(ErrorCode.CONFIGURATION_ERROR, "请输入 NiceCode API Key，或在当前进程配置 NICECODE_API_KEY。")
    config = NiceCodeConfig(base_url=os.environ.get("NICECODE_BASE_URL", "https://api.nicecode.ai/v1"),
                            model=settings.model, api_key=key,timeout_s=120)
    # Construction validates settings but never sends a model request.
    service = WebUIService(settings.config_path, settings.project_path, settings.source_files,
        lambda: NiceCodeClient(config, adapter=OpenAIResponsesAdapter()),
        include_uart=settings.include_uart, strict_approval=settings.strict_approval,
        timeout_s=settings.timeout_s,
        model_info={"source": "nicecode_api", "requested_model": config.model, "protocol": "openai-responses"})
    service._scope["model"] = settings.model
    return service


def suggested_source(project: Path) -> str | None:
    """Prefer published paths while accepting an existing unmigrated project."""
    for relative in ("core/src/main.c", "Core/Src/main.c", "main.c"):
        if (project / relative).is_file():
            return relative
    return None


def _choose_settings(config_path: str):
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "图形启动需要 Python Tkinter 和桌面会话；也可使用 serve 命令。") from None
    try:
        root = tk.Tk()
    except tk.TclError:
        raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "图形启动需要桌面会话；也可使用 serve 命令。") from None
    root.title("智调 Agent · 启动控制台")
    root.geometry("760x535")
    root.minsize(720, 500)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    ttk.Label(frame, text="智调 AI 硬件调试控制台", font=("Microsoft YaHei", 17)).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
    ttk.Label(frame, text="选择部署范围后打开本机控制台。源码发送、任务范围及每次修改仍需在控制台确认。").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 16))
    profile = tk.StringVar(value=str(Path(config_path).absolute()))
    project, sources = tk.StringVar(), tk.StringVar(value="core/src/main.c")
    model = tk.StringVar(value=os.environ.get("NICECODE_MODEL", "gpt-5.6-sol"))
    key = tk.StringVar()
    uart, strict = tk.BooleanVar(value=True), tk.BooleanVar(value=False)
    timeout = tk.StringVar(value="600")
    result = []

    def load_defaults():
        try:
            config = DeploymentConfig.load(profile.get())
            project.set(config.allowed_roots[0])
            source = suggested_source(Path(project.get()))
            if source is not None: sources.set(source)
            uart.set(config.uart_observer is not None)
        except AgentError:
            pass

    def choose_profile():
        value = filedialog.askopenfilename(parent=root, title="选择可信部署配置", filetypes=[("JSON", "*.json")])
        if value:
            profile.set(value)
            load_defaults()

    def choose_project():
        value = filedialog.askdirectory(parent=root, title="选择 STM32 工程根目录")
        if value:
            project.set(value)
            source = suggested_source(Path(value))
            if source is not None: sources.set(source)

    def choose_sources():
        values = filedialog.askopenfilenames(parent=root, title="选择允许 AI 修改的现有 UTF-8 源码", initialdir=project.get(),
                                              filetypes=[("C / C++ / Assembly", "*.c *.h *.cpp *.hpp *.s *.S")])
        try:
            names = [Path(value).resolve().relative_to(Path(project.get()).resolve()).as_posix() for value in values]
        except ValueError:
            messagebox.showerror("源码范围", "源码必须位于所选工程内。", parent=root)
            return
        if names: sources.set(";".join(names))

    for row, label, variable, command in ((2, "部署 JSON", profile, choose_profile),
                                          (3, "STM32 工程", project, choose_project),
                                          (4, "允许修改的源码", sources, choose_sources)):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=8, padx=(0, 12))
        ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=8)
        ttk.Button(frame, text="选择…", command=command).grid(row=row, column=2, padx=(9, 0))
    for row, label, variable in ((5, "NiceCode 模型", model), (6, "API Key（不保存）", key), (7, "总预算 / 秒", timeout)):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=8, padx=(0, 12))
        entry = ttk.Entry(frame, textvariable=variable, show="*" if row == 6 else "")
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=8)
    ttk.Label(frame, text="密钥留空时使用当前进程环境变量；多份源码用分号分隔。").grid(row=8, column=0, columnspan=3, sticky="w", pady=6)
    ttk.Checkbutton(frame, text="采集 UART，执行完整四接口闭环（需要 uart_observer 配置）", variable=uart).grid(row=9, column=0, columnspan=3, sticky="w", pady=5)
    ttk.Checkbutton(frame, text="严格审批：每轮硬件验证再次确认", variable=strict).grid(row=10, column=0, columnspan=3, sticky="w", pady=5)

    def start():
        def prepare():
            config = DeploymentConfig.load(profile.get())
            path = config.local_path(str(Path(project.get()).absolute()))
            selected = tuple(name.strip() for name in sources.get().split(";") if name.strip())
            snapshot = SourceEditor(str(path), selected).snapshot()
            if not snapshot.success:
                raise AgentError(ErrorCode(snapshot.error_code), snapshot.message)
            settings = LaunchSettings(profile.get(), str(path), selected, model.get().strip(), key.get(),
                                      uart.get(), strict.get(), float(timeout.get()))
            service = build_service(settings)
            if not service._preflight.success:
                raise AgentError(ErrorCode(service._preflight.error_code), service._preflight.message)
            return {"service": service}
        prepared = invoke(prepare, backend="desktop")
        if not prepared.success:
            messagebox.showerror("启动前检查", prepared.message, parent=root)
            return
        result.append(prepared.data["service"])
        key.set("")
        root.destroy()

    ttk.Button(frame, text="打开 PC 控制台", command=start).grid(row=11, column=0, columnspan=3, sticky="ew", pady=(18, 0))
    load_defaults()
    root.mainloop()
    return result[0] if result else None


def _choose_mock_settings():
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "图形启动需要 Python Tkinter 和桌面会话。") from None
    try:
        root = tk.Tk()
    except tk.TclError:
        raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "图形启动需要桌面会话。") from None
    root.title("智调 · NiceCode＋模拟硬件")
    root.geometry("760x470")
    root.minsize(720, 450)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    ttk.Label(frame, text="真实 NiceCode＋模拟硬件", font=("Microsoft YaHei", 17)).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
    ttk.Label(frame, text="自动创建临时 main.c，不需要部署 JSON、Keil 或开发板。\n"
                         "模型理解目标并提出修改；源码发送与每个 diff 仍在控制台确认。",
              wraplength=680).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))
    model = tk.StringVar(value=os.environ.get("NICECODE_MODEL", "gpt-5.6-sol"))
    key, timeout = tk.StringVar(), tk.StringVar(value="600")
    network = tk.BooleanVar(value=False)
    result = []
    for row, label, variable in ((2, "NiceCode 模型", model), (3, "API Key（不保存）", key),
                                  (4, "总预算 / 秒", timeout)):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=8, padx=(0, 12))
        ttk.Entry(frame, textvariable=variable, show="*" if row == 3 else "").grid(
            row=row, column=1, sticky="ew", pady=8)
    ttk.Label(frame, text="Key 留空可使用 NICECODE_API_KEY；总预算包含等待人工确认的时间。").grid(
        row=5, column=0, columnspan=2, sticky="w", pady=6)
    ttk.Checkbutton(frame, text="同意本次使用 NiceCode API（会联网，可能计费）", variable=network).grid(
        row=6, column=0, columnspan=2, sticky="w", pady=8)

    def start():
        def prepare():
            try:
                budget = number(float(timeout.get()))
            except (ValueError, AgentError):
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "请输入 0～1800 范围内的正数预算。") from None
            service = build_mock_service(MockLaunchSettings(model.get().strip(), key.get(), network.get(), budget))
            if not service._preflight.success:
                service.close()
                raise AgentError(ErrorCode(service._preflight.error_code), service._preflight.message)
            return {"service": service}
        prepared = invoke(prepare, backend="desktop")
        if not prepared.success:
            messagebox.showerror("启动前检查", prepared.message, parent=root)
            return
        result.append(prepared.data["service"])
        key.set("")
        root.destroy()

    ttk.Button(frame, text="打开 AI 联调控制台", command=start).grid(
        row=7, column=0, columnspan=2, sticky="ew", pady=(14, 0))
    root.mainloop()
    return result[0] if result else None


def launch(*, config_path="deployment.local.json", demo=False, mock_hardware=False, port=8765, open_browser=True):
    def operation():
        if type(demo) is not bool or type(mock_hardware) is not bool or demo and mock_hardware:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Choose either offline demo or API with mock hardware.")
        if demo:
            from .demo_ui import DemoWebUIService
            service = DemoWebUIService()
        elif mock_hardware:
            service = _choose_mock_settings()
        else:
            service = _choose_settings(config_path)
        if service is None:
            return {"decision": "STOPPED", "reason": "LAUNCH_CANCELLED"}
        result = run_server(service, port=port, open_browser=open_browser)
        return {"outcome": result}
    result = invoke(operation, backend="desktop")
    return result.data.get("outcome", result) if result.success else result


def main(argv=None):
    parser = argparse.ArgumentParser(description="智调（tiáo）PC 控制台")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--demo", action="store_true", help="Offline temporary source and simulated tools only")
    modes.add_argument("--mock-hardware", action="store_true", help="NiceCode API with temporary source and simulated hardware")
    parser.add_argument("--config", default="deployment.local.json")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    result = launch(config_path=args.config, demo=args.demo, mock_hardware=args.mock_hardware,
                    port=args.port, open_browser=not args.no_browser)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.success else 1
