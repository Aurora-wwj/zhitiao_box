"""Trusted terminal review; internal fingerprints never need to be typed."""

import json
import sys
import unicodedata

from .errors import ErrorCode
from .models import OperationResult


def _terminal(text) -> str:
    """Show terminal controls literally so a source/log cannot redraw the UI."""
    return "".join(
        char if char in "\n\t" or (ord(char) >= 32 and not 127 <= ord(char) <= 159
                                  and unicodedata.category(char) != "Cf")
        else "\\u" + format(ord(char), "04x")
        for char in str(text)
    )


def show_preview(preview: dict, *, title: str) -> None:
    """Keep a structured preview on stdout and a readable diff on stderr."""
    print(json.dumps({"review": title, "preview": preview}, ensure_ascii=False, indent=2), flush=True)
    print(_terminal(title), file=sys.stderr)
    params = preview.get("params", {})
    binding = params.get("binding") or params.get("scope", {})
    reason = preview.get("reason")
    if reason:
        print("修改理由：" + _terminal(reason), file=sys.stderr)
    source = params.get("path") or params.get("project_path") or binding.get("project_path")
    if source:
        print("文件 / 工程：" + _terminal(source), file=sys.stderr)
    if isinstance(params.get("source_files"), dict):
        print("允许发送和修改的源码：" + _terminal(", ".join(params["source_files"])), file=sys.stderr)
    elif isinstance(binding.get("source_files"), list):
        print("允许发送和修改的源码：" + _terminal(", ".join(binding["source_files"])), file=sys.stderr)
    deployment = binding.get("deployment", {})
    host = params.get("target_host") or deployment.get("host")
    if host:
        print("目标板：" + _terminal(host), file=sys.stderr)
    observed_gpio = params.get("observed_gpio") or binding.get("observed_gpio")
    if not observed_gpio and isinstance(deployment.get("observer"), dict):
        observed_gpio = deployment["observer"].get("observed_gpio")
    if observed_gpio:
        print("物理观测引脚：STM32 " + _terminal(observed_gpio), file=sys.stderr)
    goal = params.get("params") or binding.get("test_params") or binding.get("goal")
    if not goal and isinstance(params.get("arguments"), list):
        goal = next((item for item in params["arguments"] if isinstance(item, dict)), None)
    if isinstance(goal, dict) and "expected_period_ms" in goal and "tolerance_ms" in goal:
        print("确定性目标：GPIO 完整周期 " + _terminal(goal["expected_period_ms"]) + " ± "
              + _terminal(goal["tolerance_ms"]) + " ms。", file=sys.stderr)
    steps = params.get("steps") or params.get("tools")
    if steps:
        labels = {"build_firmware": "构建固件", "flash_firmware": "上传 / 烧录 / 校验 / 复位",
                  "read_target_log": "采集 UART", "run_hardware_test": "PL 实测并判定"}
        print("本轮步骤：" + _terminal(" → ".join(labels.get(item, item) for item in steps)), file=sys.stderr)
    scope = params.get("observation_mode") or params.get("verification_scope")
    if scope:
        print("验证范围：" + _terminal(scope), file=sys.stderr)
    if params.get("timeout_s"):
        print("本项时间预算：" + _terminal(params["timeout_s"]) + " s。", file=sys.stderr)
    elif binding.get("timeout_s"):
        print("会话总预算：" + _terminal(binding["timeout_s"]) + " s；最多 "
              + _terminal(binding.get("max_attempts")) + " 轮。", file=sys.stderr)
    observation_effects = params.get("observation", {}).get("descriptor", {}).get("effects")
    if observation_effects:
        print("观测效果：" + _terminal(observation_effects), file=sys.stderr)
    effects = params.get("effects")
    if effects:
        print("执行内容：" + _terminal(effects), file=sys.stderr)
    diff = preview.get("params", {}).get("diff")
    if isinstance(diff, str) and diff:
        print(_terminal(diff), file=sys.stderr, flush=True)


def human_review(preview: dict, *, title: str, show: bool = True) -> OperationResult:
    """Return a human decision only. This function cannot authorize an action.

    A caller must use the exact displayed proposal ID/fingerprint with its
    ApprovalGate. Piped input is never treated as a human approval.
    """
    if show:
        show_preview(preview, title=title)
    if not sys.stdin.isatty():
        return OperationResult(False, ErrorCode.APPROVAL_REQUIRED.value,
                               "Interactive human review is required; nothing was approved.", "approval_ui")
    while True:
        try:
            answer = input("输入 批准 / approve / y 批准本项；diff 查看完整差异；其他输入取消：").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        normalized = answer.casefold()
        if normalized in {"diff", "d", "查看差异"}:
            diff = preview.get("params", {}).get("diff")
            if isinstance(diff, str) and diff:
                print(_terminal(diff), file=sys.stderr, flush=True)
            else:
                show_preview(preview, title=title)
            continue
        # Retain compatibility with earlier development instructions while
        # offering a short confirmation for the exact currently displayed plan.
        legacy = "APPROVE " + str(preview.get("fingerprint", ""))
        approved = normalized in {"批准", "approve", "y", "yes"} or answer == legacy
        return OperationResult(True, None, "Human review completed.", "approval_ui", data={"approved": approved})
