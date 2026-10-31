"""Human-readable view model derived from structured state and evidence."""

import math

from .tools.commands import sanitized_log


LABELS = {"IDLE": "准备就绪", "ANALYZING_GOAL": "理解用户目标", "NEEDS_CLARIFICATION": "等待补充目标",
          "AWAITING_GOAL_APPROVAL": "确认任务范围", "AWAITING_EXECUTION_APPROVAL": "等待本轮验证批准",
          "AWAITING_APPROVAL": "等待源码修改批准", "BUILDING": "编译固件", "FLASHING": "烧录 / 校验 / 复位",
          "OBSERVING": "采集 UART / PL", "ANALYZING": "AI 分析运行证据", "APPLYING_EDIT": "应用已批准的修改",
          "READY": "准备下一轮", "RUNNING": "执行中", "VERIFYING": "重新验证",
          "PASS": "目标已通过", "FAIL": "目标未通过", "STOPPED": "运行已停止", "ERROR": "工具或服务错误"}
TOOLS = {"build_firmware": "构建固件", "flash_firmware": "烧录与校验",
         "read_target_log": "UART 日志", "run_hardware_test": "PL 周期测量"}


def _workflow_steps(phase, scope, events, attempt, busy):
    definitions = [("理解目标", None, "TARGET_PARSED"),
                   ("构建固件", "build_firmware", "BUILDING"),
                   ("烧录 / 校验 / 复位", "flash_firmware", "FLASHING"),
                   ("UART 日志采集", "read_target_log", "OBSERVING"),
                   ("PL 独立物理测量", "run_hardware_test", "OBSERVING"),
                   ("AI 分析", None, "ANALYSIS_FINISHED")]
    latest = next((row for row in reversed(events) if row.get("kind") != "INDICATOR_ERROR"), {})
    rows = []
    for index, (label, tool, kind) in enumerate(definitions):
        completed = next((event for event in reversed(events)
                          if (index == 0 or event.get("attempt") == attempt)
                          and (event.get("kind") == "TOOL_FINISHED" and event.get("tool_name") == tool
                               if tool else event.get("kind") == kind)), None)
        if tool:
            active = busy and latest.get("tool_name") == tool and latest.get("kind") == kind
        elif index == 0:
            active = busy and phase == "ANALYZING_GOAL"
        else:
            active = busy and latest.get("kind") == "ANALYZING" and latest.get("attempt") == attempt
        skipped_uart = tool == "read_target_log" and not scope.get("include_uart", True)
        skipped_analysis = index == 5 and phase == "PASS" and completed is None
        skipped = skipped_uart or skipped_analysis
        state = ("skipped" if skipped else "failed" if completed and completed.get("success") is False
                 else "done" if completed else "active" if active else "pending")
        if skipped_uart:
            label = "UART（本次显式跳过）"
        elif skipped_analysis:
            label = "AI 分析（本轮已达标，无需修改）"
        elif tool == "run_hardware_test" and scope.get("evidence_source") == "mock":
            label = "PL 周期测量（模拟）"
        rows.append({"label": label, "state": state})
    return rows


def view_model(*, phase, scope, report, pending, events, goal=None, last_result=None, busy=False):
    report = report or {}
    points, tools, reason, uart_logs = [], [], "", []
    uart_attempt, uart_success, uart_error = 0, False, None
    uart_partial_tail = False
    uart_issues = []
    for cycle in report.get("cycles", []):
        for entry in cycle.get("execution", {}).get("audit", []):
            result = entry.get("result", {})
            if entry.get("tool_name") == "read_target_log":
                uart_logs = [row["text"] for row in result.get("logs", []) if isinstance(row.get("text"), str)]
                uart_attempt, uart_success = cycle.get("attempt", 0), result.get("success") is True
                uart_error = result.get("error_code")
                uart_issues = [label for name, label in (("truncated", "截断"), ("overflow", "溢出"))
                               if result.get(name) is True]
                uart_issues += [label for name, label in (("decoding_errors", "解码错误"),
                    ("frame_errors", "帧错误"), ("parity_errors", "奇偶错误"))
                    if type(result.get(name)) is int and result[name] > 0]
                uart_partial_tail = (result.get("partial_tail") is True
                    and result.get("capture_end_reason") == "deadline"
                    and result.get("truncated") is False and result.get("overflow") is False
                    and not uart_issues)
        reason = cycle.get("model_decision", {}).get("reason", reason)
    for event in events:
        if event.get("kind") == "TOOL_FINISHED":
            tools.append({"attempt": event["attempt"], "tool_name": event.get("tool_name"),
                          "label": TOOLS.get(event.get("tool_name"), "工具"),
                          "success": event.get("success"), "log_count": event.get("log_count"),
                          "error_code": event.get("error_code")})
            value = event.get("period_ms")
            if type(value) in (int, float) and math.isfinite(value) and value > 0:
                points.append({"attempt": event["attempt"], "period_ms": value, "passed": event.get("passed")})
    # Historical reports may predate events. Their structured audit is enough.
    if not points:
        for cycle in report.get("cycles", []):
            for entry in cycle.get("execution", {}).get("audit", []):
                result = entry.get("result", {})
                value = result.get("measurements", {}).get("period_ms")
                if type(value) in (int, float) and math.isfinite(value) and value > 0:
                    points.append({"attempt": cycle.get("attempt", 0), "period_ms": value,
                                   "passed": result.get("passed")})
    if pending is not None:
        reason = pending.get("reason", reason)
    if not reason and report.get("reason") == "LOG_INCOMPLETE":
        reason = "UART 证据不完整，已停止后续 PL 测量；请检查采集截断和硬件健康标记。"
    descriptor = (pending or {}).get("params", {}).get("observation", {}).get("descriptor", {})
    params = (goal or {}).get("params") or report.get("metadata", {}).get("goal")
    latest_uart = next((row for row in reversed(tools) if row["tool_name"] == "read_target_log"), None)
    newest_uart = latest_uart if latest_uart and latest_uart["attempt"] >= uart_attempt else None
    uart_failed = newest_uart["success"] is False if newest_uart else bool(uart_attempt and not uart_success)
    if uart_failed:
        code = (newest_uart or {}).get("error_code") or uart_error or "UART_READ_FAILED"
        uart_text = "本轮 UART 采集失败（" + sanitized_log(str(code)) + "），请查看工具错误与报告。"
    elif latest_uart and latest_uart["attempt"] > uart_attempt:
        uart_text = "本轮采集已结束，正在整理证据与报告。"
    elif uart_success and uart_issues:
        uart_text = "本轮 UART 证据不完整（" + "、".join(uart_issues) + "），请检查采集结果与报告。"
        if uart_logs:
            uart_text += "\n" + "\n".join(sanitized_log(text) for text in uart_logs[-20:])
    elif uart_logs:
        uart_text = "\n".join(sanitized_log(text) for text in uart_logs[-20:])
        if uart_success and uart_partial_tail:
            uart_text += "\n（采集窗口正常结束，末行未闭合，已保留作参考；周期由 PL 独立测量判定。）"
    elif uart_success:
        uart_text = "本轮采集成功，没有收到日志。"
    else:
        uart_text = "尚未完成本轮日志采集。" if scope.get("include_uart", True) else "PL-only 模式：本次没有采集 UART。"
    status, error_code = phase, (last_result or {}).get("error_code")
    if error_code and error_code not in {"CANCELLED", "APPROVAL_REJECTED"}:
        status = "ERROR"
    elif phase == "FAIL" and report.get("reason") not in {"ATTEMPTS_EXHAUSTED", "PHYSICAL_CHECK_FAILED"}:
        status = "ERROR"
    current = next((row for row in reversed(events) if row.get("kind") != "INDICATOR_ERROR"), {})
    if busy and current.get("kind") in LABELS and phase not in {"AWAITING_GOAL_APPROVAL", "NEEDS_CLARIFICATION"}:
        stage = current["kind"]
    else:
        stage = status
    if busy and current.get("kind") == "TOOL_FINISHED":
        stage_label = TOOLS.get(current.get("tool_name"), "工具") + "完成"
    else:
        stage_label = LABELS.get(stage, "正在处理")
    attempt = max([event.get("attempt", 0) for event in events] + [report.get("attempts", 0)])
    return {"status": status, "status_label": LABELS.get(status, status), "stage_label": stage_label,
            "attempt": attempt, "steps": _workflow_steps(phase, scope, events, attempt, busy),
            "max_attempts": scope.get("max_attempts", report.get("max_attempts", 3)),
            "goal": params, "measurements": points, "before": points[0] if points else None,
            "after": points[-1] if len(points) > 1 else None,
            "reason": sanitized_log(reason) if isinstance(reason, str) else "",
            "tools": tools, "uart_logs": [sanitized_log(text) for text in uart_logs[-20:]],
            "uart_attempt": uart_attempt, "uart_success": uart_success, "latest_uart": latest_uart,
            "uart_partial_tail": uart_partial_tail,
            "uart_text": uart_text,
            "evidence_source": report.get("evidence_source", scope.get("evidence_source", "real")),
            "verification_scope": report.get("verification_scope", "gpio_period_and_uart_capture"
                                              if scope.get("include_uart", True) else "gpio_period_only"),
            "fifo_reset_planned": bool(descriptor.get("uart", {}).get("fifo_reset")),
            "fpga_reload_planned": descriptor.get("preparation", {}).get("requires_loading") is True,
            "hardware_state_uncertain": report.get("hardware_state_uncertain", False)}
