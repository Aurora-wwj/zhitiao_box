"""Trusted terminal approval for local setup and read-only pairing checks."""

from .approval_ui import human_review
from .deployment import DeploymentConfig, PLObserverConfig, StatusIndicatorConfig, UARTObserverConfig
from .models import OperationResult, invoke
from .pairing import DeploymentDiagnostics, DeploymentSetup


def _review(instance, preview, *, preview_only, title, execute):
    if not preview.success or preview_only:
        return preview
    reviewed = human_review(preview.data, title=title)
    if not reviewed.success:
        return reviewed
    decision = instance.approvals.decide(preview.data["proposal_id"], preview.data["fingerprint"],
                                         approved=reviewed.data["approved"])
    if not decision.success:
        return decision
    return execute(preview.data["proposal_id"])


def run_setup(
    *, project_path: str, keil_executable: str, known_hosts: str,
    identity_file: str | None = None, project_file: str | None = None,
    target: str | None = None, host: str = "192.168.10.2", port: int = 22,
    user: str = "root", observed_gpio: str = "PA1",
    output_path: str = "deployment.local.json", preview_only: bool = False,
    check_remote: bool = False, no_led: bool = False,
) -> OperationResult:
    def operation():
        # Native absolute paths are deliberate: the CLI runs on the deployment
        # PC; Windows paths must never be interpreted as remote Zynq paths.
        config = DeploymentConfig(
            allowed_roots=(project_path,), keil_executable=keil_executable,
            project_file=project_file, target=target, known_hosts=known_hosts,
            identity_file=identity_file, host=host, port=port, user=user,
            observer=PLObserverConfig(observed_gpio=observed_gpio, bitstream="/sd/pl/zhidiao_observe_v5_led.bit",
                bitstream_sha256="fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6"),
            uart_observer=UARTObserverConfig(),
            status_indicator=None if no_led else StatusIndicatorConfig(),
        )
        setup = DeploymentSetup(config)
        result = _review(setup, setup.preview(output_path, check_remote=check_remote),
                         preview_only=preview_only, title="审批部署配置：创建新配置，按所选范围执行只读检查；不安装密钥、不修改启动文件。",
                         execute=setup.apply)
        return {"outcome": result}
    prepared = invoke(operation, backend="setup_cli")
    return prepared.data["outcome"] if prepared.success else prepared


def run_diagnostics(config_path: str, *, preview_only: bool = False) -> OperationResult:
    def operation():
        instance = DeploymentDiagnostics(DeploymentConfig.load(config_path))
        result = _review(instance, instance.preview(), preview_only=preview_only,
                         title="审批只读部署检查：SSH、HOME、公钥文件状态、OpenOCD、USB 和已准备的 PL；不烧录、不修改板端。",
                         execute=instance.run)
        return {"outcome": result}
    prepared = invoke(operation, backend="setup_cli")
    return prepared.data["outcome"] if prepared.success else prepared
