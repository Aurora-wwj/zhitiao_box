# LLM 协作与自我纠错记录

Agent 系统提示模板位于 src/agent/src/zhidiao_agent/agent.py，目标提取位于 goals.py。
最终用户目标、目标审批与澄清轨迹见 data/final_run_sanitized.json 的 metadata/task_entry/reviews；模型原提案见 cycles[0].model_decision，批准差异见 reviews 和 applied_edit。
实际模型提案把单次翻转等待 HAL_Delay(300) 调整为 500；随后经 build／flash／UART／PL 验证 1001.08682 ms。不能将单次等待直接等同于完整周期。
工程自我纠错案例：BusyBox 不支持小数 sleep 改整数 usleep；UART 正常 deadline 半行从 fatal truncated 中分离；真实 UI API deadline 设为 120 s（上传包已带此补丁）。
历史失败与修复过程见 src/agent/docs/uart-window-boundary-2026-10-30.md 等日期文档。最终 JSON 保存模型 reason/edit；未提供逐条完整 HTTP 原始对话，不能声称该部分已完整收集。API Key 与认证头不公开。
