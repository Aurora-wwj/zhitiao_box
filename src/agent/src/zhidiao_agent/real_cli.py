"""Human-facing, single-operation approval UI. No yes/auto-approve switch."""

from .approval_ui import human_review
from .deployment import DeploymentConfig
from .errors import AgentError, ErrorCode
from .models import OperationResult, invoke
from .tools.real_backend import RealBackend


def _real_operation(
    command: str, config_path: str, path: str | None, *, preview_only: bool,
    duration_s: float = 5, params: dict | None = None,
) -> OperationResult:
    def prepare():
        backend = RealBackend(DeploymentConfig.load(config_path))
        if command in {"real-build", "real-flash"}:
            preview_method = backend.preview_build if command == "real-build" else backend.preview_flash
            preview = preview_method(path)
            return {"instance": backend, "preview": preview, "observation": None}
        if command not in {"real-log", "real-test"}:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Unsupported real operation.")
        method = "read_target_log" if command == "real-log" else "run_hardware_test"
        arguments = (duration_s,) if command == "real-log" else ("gpio_period", params)
        observation = backend.preview_observation(method, *arguments)
        if not observation.success:
            return {"instance": backend, "preview": observation, "observation": None}
        plan = {"method": method, "arguments": list(arguments), "observation": observation.data}
        preview = backend.approvals.propose(method, plan)
        return {"instance": backend, "preview": preview, "observation": plan}

    # Keep runtime objects internal rather than serializing them through invoke().
    prepared = invoke(prepare, backend="real_cli")
    if not prepared.success:
        return prepared
    backend, preview = prepared.data["instance"], prepared.data["preview"]
    if not preview.success:
        return preview
    if preview_only:
        return preview
    review = human_review(preview.data, title={
        "real-build": "审批真实固件构建：Keil 将写入构建产物和编译日志。",
        "real-flash": "审批真实烧录：上传固件、核对 SHA-256，然后 program / verify / reset。",
        "real-test": "审批真实 PL 测量：检查新边沿和 valid，再按目标确定性判定。",
        "real-log": "审批真实 UART 日志采集：采集成功不代表固件行为正确。",
    }[command])
    if not review.success:
        return review
    fingerprint = preview.data["fingerprint"]
    decision = backend.approvals.decide(preview.data["proposal_id"], fingerprint, approved=review.data["approved"])
    if not decision.success:
        return decision
    observation = prepared.data["observation"]
    if observation is not None:
        method, arguments = observation["method"], observation["arguments"]
        current = backend.preview_observation(method, *arguments)
        if not current.success:
            return current
        if current.data != observation["observation"]:
            return OperationResult(False, ErrorCode.APPROVAL_REQUIRED.value,
                                   "Observation configuration changed after preview; review again.", "real_cli")
        permission = backend.approvals.consume(preview.data["proposal_id"], method, observation)
        if not permission.success:
            return permission
        preparation = observation["observation"].get("descriptor", {}).get("preparation", {})
        backend._begin_observation_cycle()
        if preparation.get("requires_loading") is True:
            child = backend._preview_preparation()
            if not child.success:
                return child
            child_decision = backend.approvals.decide(child.data["proposal_id"], child.data["fingerprint"], approved=True)
            if not child_decision.success:
                return child_decision
        if method == "read_target_log":
            child = backend._preview_uart_capture(arguments[0])
            if not child.success:
                return child
            if child.data.get("required") is not False:
                granted = backend.approvals.decide(child.data["proposal_id"], child.data["fingerprint"], approved=True)
                if not granted.success:
                    return granted
        return getattr(backend, method)(*arguments)
    execute = backend.build_firmware if command == "real-build" else backend.flash_firmware
    return execute(path)


def real_operation(
    command: str, config_path: str, path: str | None = None, *, preview_only: bool,
    duration_s: float = 5, params: dict | None = None,
) -> OperationResult:
    result = invoke(lambda: {"outcome": _real_operation(
        command, config_path, path, preview_only=preview_only, duration_s=duration_s, params=params,
    )}, backend="real_cli")
    return result.data["outcome"] if result.success else result
