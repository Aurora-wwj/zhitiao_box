# 智调盒 — AI 上板摆渡站

智调读 tiáo / ZHITIAO。基于 FPGA 独立物理反馈的 STM32 AI 闭环调试系统。

自然语言目标 → Agent → 确定性 Controller → build / flash / UART / PL → FAIL 证据 → AI diff → 人工批准 → 重建验证 → PASS。

## 当前结果与发布范围

最终真实四接口两轮 run_5d8e004954664f6c8f8ff0f85d31959b：**601.7169 ms FAIL → HAL_Delay 300 改为 500 → 1001.08682 ms PASS**，目标完整周期 1000±50 ms。两轮均有四工具、fresh_edges=2；第一轮 partial_tail=true、truncated=false，未阻止 PL。

原始最终报告、发布 main.c 与第二轮 HEX 已做 SHA 一致性核对。见 [公开 JSON](data/final_run_sanitized.json)、[测量表](data/measurements.csv)、[证据说明](report/test_evidence.md)。这不是本次云端重新进行的板卡测试。

**仓库正在分包整理：Agent、STM32 与最终 JSON/HEX 已收到；FPGA 源工程、v5 bit、原始实现报告、板端脚本、现场照片及正式主报告尚待补充。历史 smoke 已按只读参考整理；SD 压缩包超出附件下载上限，尚未读取。当前不是完整比赛提交包。** 缺项见 [发布状态](report/release_status.md)。

## FPGA 的作用与架构

Zynq-7000 AX7Z020 的 PL 以 100 MHz 独立测量完整周期／高电平，结合边沿 freshness 与一致性检查，避免软件自报周期代替实测；AXI Uartlite 采集 UART，AXI GPIO 表示工具进度。PC 负责 LLM、审批、Keil、SSH/SCP 与界面；PS 提供寄存器访问及 OpenOCD/ST-Link 通道。

```mermaid
flowchart LR
    U[用户目标] --> A[PC Agent]
    A --> C[Controller / 审批与预算]
    C --> K[Keil build]
    K --> Z[SSH / SCP / OpenOCD]
    Z --> M[STM32]
    M --> P[PL UART / 独立周期计数]
    P --> D[确定性 PASS / FAIL]
    D --> A
```

四个公开工具保持 contract_version=0.2；PASS 由 PL 数值与容差决定，AI 无审批权和任意命令入口。

## 快速开始

Python 3.13，Agent 运行依赖标准库。在仓库的 src/agent 目录执行：

```powershell
cd src/agent
$env:PYTHONPATH = (Resolve-Path .\src).Path
py -3.13 -B -m unittest discover -s tests -v
.\start_demo.bat
```

start_demo.bat：离线脚本模型＋模拟硬件；start_ai_mock.bat：真实 NiceCode＋模拟硬件；start_ui.bat：真实部署。真实 API 需要进程环境中的 Key 或启动器遮罩输入，可能计费。不要提交 Key。

真实部署先阅读 [从零复现](report/reproduction.md)。复制 deployment.example.json 为 deployment.local.json 并改成自己的绝对路径。默认示例为 v5＋LED；deployment.no-led.example.json 使用同一 v5，只关闭灯。当前仓库尚未收到 bitstream，不能仅凭示例配置就访问硬件。

## 硬件与连接

AX7Z020（Zynq-7000）＋STM32G431＋ST-Link/V2。PA1→M18 为周期观测；PA2/USART2_TX→M17，115200 8N1。GPIO 0x43C60000 bit0–3 为 active-low 四灯；最终管脚约束待 FPGA 包核对。详见 [接线](board/wiring.md)。

## AMD 推荐目录对照

| 推荐项 | 本仓库 |
| --- | --- |
| src | src/agent（内含原 Python src 布局）、src/stm32/gpio_pl_test；FPGA 源码待补 |
| sim | 软件测试入口、验证说明与匿名历史 smoke 文本 |
| build | STM32 构建入口与最终 HEX；FPGA 重建／报告待补 |
| board | 接线、部署与冷启动说明 |
| data | 匿名报告、测量 CSV、校验清单 |
| skill | 按五类可复用能力组织，不要求原子化或固定数量 |
| report | 设计初稿、LLM 记录、复现与证据索引 |

除官方 README.md、LICENSE 及第三方／Keil 既有大小写名称外，新文件采用英文小写命名。保留 Core/Src、GPIO_PL_Test.uvprojx 等原名以维持第三方工程引用；Python 包名 zhidiao_agent 保持兼容。

## 已知边界

真实模型由 NiceCode API 提供，请求模型记录在报告中；未实现本地 LLM／PYNQ。一次修改一个批准的现有 UTF-8 文件；UART 115200 8N1。冷启动后的 SSH 公钥恢复和 PL 自动加载未验证持久化，需每次上电按部署说明准备。LED 表示工具状态，不等于 DUT PASS。云端没有 Keil/Vivado/板卡，硬件重建未在此环境执行。

## 文档与许可

[Skill 索引](skill/README.md) · [设计初稿](report/design_report.md) · [优化与失败分析](report/optimization_notes.md) · [验证总结](data/test_summary.md)。src/agent/docs 中日期文档为开发历史，不替代本页当前状态。

原创内容采用 [MIT](LICENSE)，第三方范围见 [third_party_notices.md](third_party_notices.md)。
