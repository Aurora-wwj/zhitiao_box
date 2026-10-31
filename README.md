# 智调盒 — AI 上板摆渡站

智调读 tiáo / ZHITIAO。基于 FPGA 独立物理反馈的 STM32 AI 闭环调试系统。

自然语言目标 → Agent → 确定性 Controller → build / flash / UART / PL → FAIL 证据 → AI diff → 人工批准 → 重建验证 → PASS。

## 当前结果与发布范围

最终真实四接口两轮 run_5d8e004954664f6c8f8ff0f85d31959b：**601.7169 ms FAIL → HAL_Delay 300 改为 500 → 1001.08682 ms PASS**，目标完整周期 1000±50 ms。两轮均有四工具、fresh_edges=2；第一轮 partial_tail=true、truncated=false，未阻止 PL。

原始最终报告、发布 main.c 与第二轮 HEX 已做 SHA 一致性核对。见 [公开 JSON](data/final_run_sanitized.json)、[测量表](data/measurements.csv)、[证据说明](report/test_evidence.md)。这不是本次云端重新进行的板卡测试。

**已整理 Agent、STM32、最终 JSON/HEX，以及 FPGA RTL／BD／XDC／工程、v5 bit 和 baseline/final 原始实现报告。** 另已接收两分包的 Zynq Linux测试材料，加入带许可的OpenOCD／libusb源码、构建入口及板端文件检查。含私钥的镜像和来源不完整的二进制不原样发布。FPGA四项外部IP仍按依赖交付，完整BOOT／Linux构建输入、实际硬件重建、现场照片与正式主报告仍待补齐；当前不是完整比赛提交包。见 [发布状态](report/release_status.md)。

v5 SHA 与指导一致。原 final 报告 LUT 7274、FF 12083、BRAM 20.5、DSP 0、IOB 44，WNS 0.709 ns、TNS 0。报告仍含未约束路径等 HIGH 警告，不能据此声称全设计时序验收完成；[原件与比较](report/fpga_evidence.md) 保留这些限制。

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

FPGA四分包与Zynq_Linux_Test两分包均已重组检查。后续大材料可按 [分包步骤](report/upload_parts.md) 上传，现有原包无需重复。Zynq测试包不等于完整SD／Linux重建工程，范围见 [板端说明](board/zynq/README.md)。

Python 3.13，Agent 运行依赖标准库。在仓库的 src/agent 目录执行：

```powershell
cd src/agent
$env:PYTHONPATH = (Resolve-Path .\src).Path
py -3.13 -B -m unittest discover -s tests -v
.\start_demo.bat
```

start_demo.bat：离线脚本模型＋模拟硬件；start_ai_mock.bat：真实 NiceCode＋模拟硬件；start_ui.bat：真实部署。真实 API 需要进程环境中的 Key 或启动器遮罩输入，可能计费。不要提交 Key。

真实部署先阅读 [从零复现](report/reproduction.md)。在 src/agent 复制 deployment.example.json 为 deployment.local.json 并改成自己的绝对路径。默认示例为 v5＋LED；deployment.no-led.example.json 使用同一 v5，只关闭灯。位流见 [build/fpga](build/fpga/README.md)；加载镜像、认证与寄存器身份仍须在板端确认。

## 硬件与连接

AX7Z020（Zynq-7000）＋STM32G431＋ST-Link/V2。PA1→M18 为周期观测；PA2/USART2_TX→M17，115200 8N1。GPIO 0x43C60000 bit0–3 为 active-low 四灯；J14/K14/J18/H18 已与最终 XDC 核对。详见 [接线](board/wiring.md)。

## AMD 推荐目录对照

| 推荐项 | 本仓库 |
| --- | --- |
| src | src/agent、src/stm32/gpio_pl_test、src/fpga/zhidiao_measure、src/third_party/openocd源码与许可 |
| sim | 软件／板端发布检查、计数核 RTL 仿真、构建控制流与匿名历史 smoke |
| build | STM32入口／HEX；FPGA Tcl／v5 bit／原报告；OpenOCD构建入口 |
| board | 接线、部署与冷启动说明 |
| data | 匿名报告、测量 CSV、校验清单 |
| skill | 按五类可复用能力组织，不要求原子化或固定数量 |
| report | 设计初稿、LLM 记录、复现与证据索引 |

除官方 README.md、LICENSE 及第三方／Keil 既有大小写名称外，新文件采用英文小写命名。保留 Core/Src、GPIO_PL_Test.uvprojx 等原名以维持第三方工程引用；Python 包名 zhidiao_agent 保持兼容。

## 已知边界

真实模型由 NiceCode API 提供，请求模型记录在报告中；未实现本地 LLM／PYNQ。一次修改一个批准的现有 UTF-8 文件；UART 115200 8N1。冷启动后的 SSH 公钥恢复和 PL 自动加载未验证持久化，需每次上电按部署说明准备。LED 表示工具状态，不等于 DUT PASS。原计数 RTL 在复位时输入已高的首次结果有启动残段边界，须等待后续稳定周期；见 [FPGA 说明](src/fpga/README.md)。云端没有 Keil/Vivado/板卡，硬件重建未在此环境执行。

## 文档与许可

[Skill 索引](skill/README.md) · [设计初稿](report/design_report.md) · [优化与失败分析](report/optimization_notes.md) · [验证总结](data/test_summary.md)。src/agent/docs 中日期文档为开发历史，不替代本页当前状态。

[Zynq测试包核对](report/zynq_intake.md) · [OpenOCD构建](build/openocd/README.md) · [PL加载与检查](board/zynq/pl_preparation.md)。已确认fixed镜像有静态IP配置，但未把配置存在当作冷启动已验收；内嵌SSH主机私钥的镜像不公开。

原创内容采用 [MIT](LICENSE)，第三方范围见 [third_party_notices.md](third_party_notices.md)。
