# 可复用硬件调试 Skill 包

按能力组织，不要求原子化或固定文件数量。每个模块含适用范围、步骤、验证、来源和失效边界，供其他团队替换板卡／路径／寄存器后复用。

总闭环 → 可信证据层 / 可靠部署层 / 故障诊断层

| 层级 | 模块 | 内容 |
| --- | --- | --- |
| 总闭环 | [hardware-debug-workflow](hardware-debug-workflow.md) | AI与确定性执行边界、四工具闭环 |
| 可信证据层 | [pl-observation](pl-observation.md) | 独立测量、freshness与一致性 |
| 可信证据层 | [uart-observation](uart-observation.md) | FIFO、窗口边界、健康状态 |
| 可靠部署层 | [deployment-and-flashing](deployment-and-flashing.md) | 产物身份、SSH/SCP、烧录验证 |
| 故障诊断层 | [failure-diagnosis](failure-diagnosis.md) | 常见故障的定位与停止／恢复 |

这些是工程经验与检查流程，不向模型开放shell或自动审批；硬件命令仍须部署者按目标环境审阅。
软件可复用检查入口：../sim/check_release.py；原生deployment-check在../src/agent内。当前没有PYNQ Skill或本地LLM，不声称相关加分能力。
