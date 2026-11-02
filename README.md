# 智调盒——AI上板摆渡站

智调读 tiáo / ZHITIAO。基于 FPGA 独立物理反馈的 STM32 AI 闭环调试系统。

报名方向：**AMD-自主选题（初级）**。报名所选平台类别覆盖AMD 7 Series／Zynq-7000／UltraScale系列，实际使用ALINX AX7Z020（xc7z020clg400-2），目标板STM32G431。报名简介及已验证范围见[项目介绍](report/project_overview.md)。

面向AI辅助硬件开发的“最后一米”：通过网络连接PC Agent，以USB／SWD完成烧录与复位，以UART和PL采集真实反馈。研发调试、远程协作、FAE支持与共享实验室是应用方向，当前实证是STM32 GPIO周期调节。

智调盒并非单纯的自动下载器，而是让 AI 真正进入真实硬件调试闭环：反复构建与烧录的是 STM32 等目标 MCU 工程；Zynq/FPGA 作为长期驻留的执行与物理观测基础设施，在初始化后不随每轮任务反复烧录。

自然语言目标 → Agent → 确定性 Controller → build / flash / UART / PL → FAIL 证据 → AI diff → 人工批准 → 重建验证 → PASS。

## 当前结果与发布范围

最终真实四接口两轮 run_5d8e004954664f6c8f8ff0f85d31959b：**601.7169 ms FAIL → HAL_Delay 300 改为 500 → 1001.08682 ms PASS**，目标完整周期 1000±50 ms。两轮均有四工具、fresh_edges=2；第一轮 partial_tail=true、truncated=false，未阻止 PL。

原始最终报告、发布main.c与第二轮HEX已做SHA一致性核对。主证据现采用最后上传的网页导出JSON的脱敏副本；与此前归档是同一次run，仅导出总耗时相差约0.02秒，不是新增实测。见[公开JSON](data/final_run_sanitized.json)、[测量表](data/measurements.csv)、[证据说明](report/test_evidence.md)及[来源清单](data/report_sources.json)。这不是本次云端重新进行的板卡测试。

![真实四接口两轮实测：601.717ms FAIL到1001.087ms PASS](data/screenshots/ui_four_tool_pass.png)

原图显示三位小数，与JSON原精度一致；四张原图及场景说明见[截图索引](data/screenshots/readme.md)。其中1000.192ms单轮图明确跳过UART，单独作为PL-only参考，不计入完整四接口闭环。

**已整理Agent、STM32、网页JSON／四张实测截图／最终HEX，以及FPGA RTL／BD／XDC／工程、v5 bit和baseline/final原始实现报告。** 另已加入Zynq测试包中带许可的OpenOCD／libusb源码、构建入口及板端文件检查。含私钥的镜像和来源不完整的二进制不原样发布。FPGA四项外部IP仍按依赖交付。Linux按实际完成的“ALINX预构建镜像→rootfs网络定制→FIT重封装→SD部署”路线交付，已有[可执行复现方法](build/linux/readme.md)和[冷启动验证步骤](board/zynq/sd_deployment.md)，不声称从源码重建整套Linux，也不将完整PetaLinux源工程列为本路线新增必做项。队伍报告已完成原系统冷启动链路验证；新生成镜像的独立上板记录、Windows／Keil／Vivado新环境记录、照片选编与正式提交版仍需归档。原件与公开位置见[材料索引](report/material_index.md)及[发布状态](report/release_status.md)。

v5 SHA 与指导一致。原 final 报告 LUT 7274、FF 12083、BRAM 20.5、DSP 0、IOB 44，WNS 0.709 ns、TNS 0。报告仍含未约束路径等 HIGH 警告，不能据此声称全设计时序验收完成；[原件与比较](report/fpga_evidence.md) 保留这些限制。

## FPGA 的作用与架构

Zynq-7000 AX7Z020 的 PL 以 100 MHz 独立测量完整周期／高电平，结合边沿 freshness 与一致性检查，避免软件自报周期代替实测；AXI Uartlite 采集 UART，AXI GPIO 表示工具进度。PC 负责 LLM、审批、Keil、SSH/SCP 与界面；PS 提供寄存器访问及 OpenOCD/ST-Link 通道。

FPGA 丰富、可编程且可扩展的物理接口，使 PL 不只是通信桥，而能够独立测量 GPIO 等真实硬件信号，为 AI 提供目标程序自身之外的物理证据。

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

FPGA四分包与Zynq_Linux_Test两分包均已重组检查。后续大材料可按 [分包步骤](report/upload_parts.md) 上传，现有原包无需重复。两份SD分包已包含启动／部署材料，当前按预构建镜像rootfs定制路线复现，范围见 [板端说明](board/zynq/readme.md)。

Python 3.13，Agent 运行依赖标准库。在仓库的 src/agent 目录执行：

```powershell
cd src/agent
$env:PYTHONPATH = (Resolve-Path .\src).Path
py -3.13 -B -m unittest discover -s tests -v
.\start_demo.bat
```

start_demo.bat：离线脚本模型＋模拟硬件；start_ai_mock.bat：真实 NiceCode＋模拟硬件；start_ui.bat：真实部署。真实 API 需要进程环境中的 Key 或启动器遮罩输入，可能计费。不要提交 Key。

真实部署先阅读 [从零复现](report/reproduction.md)。在 src/agent 复制 deployment.example.json 为 deployment.local.json 并改成自己的绝对路径。默认示例和deployment-setup向导均为v5＋LED；deployment.no-led.example.json或向导--no-led使用同一v5，只关闭灯。私人deployment.local.json不提交，向导不会覆盖已有配置。位流见 [build/fpga](build/fpga/readme.md)；加载镜像、认证与寄存器身份仍须在板端确认。

**当前部署在初始化阶段加载 v5 PL，加载完成后再启动 Agent 和 LED；Agent 使用 `check_only`，保持现有四接口执行顺序。** 现有 `E:\zhidiao-agent\src` 的 `PYTHONPATH` 设置、三步SSH公钥恢复（最后输出`ZHIDIAO_SSH_KEY_OK`）、v5位流文件SHA校验与手动加载统一见 [板端初始化说明](board/zynq/pl_preparation.md)。

## Linux平台与硬件交接

目标系统为PetaLinux2017.4、Linux4.9.0-xilinx、armv7l／ARM32、BusyBox1.24.1；内核工具链为Linaro GCC6.2.1（2016.11），内核构建日期2019-10-18。版本依据队伍本次终端截图及原ramdisk的/etc/issue，详见[平台清单](data/linux_platform.json)。

新导出的[system_wrapper.hdf](src/fpga/zhidiao_measure/system_wrapper.hdf)作为当前交接文件，内含bit与现有v5黄金位流、BD Tcl均逐字节一致。v5在Linux启动后通过`/sd/pl/zhidiao_observe_v5_led.bit → /dev/xdevcfg`加载，复现当前PL功能不要求重新生成BOOT.BIN。原镜像／修改镜像SHA及rootfs差异见[Linux定制说明](build/linux/readme.md)。

## 硬件与连接

AX7Z020（Zynq-7000）＋STM32G431＋ST-Link/V2。PA1→M18 为周期观测；PA2/USART2_TX→M17，115200 8N1。GPIO 0x43C60000 bit0–3 为 active-low 四灯；J14/K14/J18/H18 已与最终 XDC 核对。详见 [接线](board/wiring.md)。

## 测试代码（Keil工程）

原合集`Project`目录映射到本仓库`src/stm32`，两份工程并列保留：

| 说明／合集名称 | 仓库位置 | 用途 |
| --- | --- | --- |
| GPIO_PL_Test | [原工程](src/stm32/gpio_pl_test) | 已有两轮四接口JSON及黄金HEX对应的工程 |
| GPIO_PL_Test_LED | [LED同步工程](src/stm32/gpio_pl_test_led/readme.md) | DK117E-G4板上八个用户LED随PA1方波同步亮灭，无需新增外接显示器件 |

**LED工程实测验证时，文件夹原名也是`GPIO_PL_Test`。** 为符合AMD指南的新增路径英文小写要求，发布目录使用`gpio_pl_test_led`，内部Keil Target仍为`GPIO_PL_Test`。本次上传的实际源码保持`HAL_Delay(500)`；旧说明中的300 ms基线未沿用。原工程和实测证据不变，新变体单独构建、记录验证结果；完整来源见[LED文件清单](data/stm32_led_manifest.json)。

## AMD 推荐目录对照

| 推荐项 | 本仓库 |
| --- | --- |
| src | src/agent、src/stm32下原版与LED同步版Keil工程、src/fpga/zhidiao_measure、src/third_party/openocd源码与许可 |
| sim | 软件／板端发布检查、计数核 RTL 仿真、构建控制流与匿名历史 smoke |
| build | STM32入口／HEX；FPGA Tcl／v5 bit／原报告；OpenOCD构建入口 |
| board | 接线、部署与冷启动说明 |
| data | 匿名报告、测量 CSV、校验清单 |
| skill | 按五类可复用能力组织，不要求原子化或固定数量 |
| report | 设计初稿、LLM 记录、复现与证据索引 |

按指南3.3.5.4，发布路径统一使用英文小写、数字、下划线或连字符（扩展名使用点号）；仅保留指南目录示例明确列出的根`README.md`与`skill/README.md`。其他说明文件为`readme.md`，根许可证为`license`。原STM32工程已同步改为`core/src/main.c`、`mdk-arm/gpio_pl_test.uvprojx`，内部Keil Target仍为`GPIO_PL_Test`。第三方许可证正文不变；历史JSON／diff中的原路径保留，映射与校验见[路径迁移说明](report/path_migration.md)。Python包名`zhidiao_agent`保持兼容。

## 已知边界

真实模型由 NiceCode API 提供，请求模型记录在报告中；未实现本地 LLM／PYNQ。一次修改一个批准的现有 UTF-8 文件；UART 115200 8N1。队伍报告原系统冷启动网络／SSH、USB及SWD链路已验证；独立冷启动日志待归档，免密公钥持久化和PL开机自动加载未由本次版本截图证明，仍按每次上电的手动初始化步骤准备。LED 表示工具状态，不等于 DUT PASS。原计数 RTL 在复位时输入已高的首次结果有启动残段边界，须等待后续稳定周期；见 [FPGA 说明](src/fpga/readme.md)。云端没有 Keil/Vivado/板卡，硬件重建未在此环境执行。

## 文档与许可

[Skill 索引](skill/README.md) · [设计初稿](report/design_report.md) · [设计初稿PDF](report/design_report.pdf) · [优化与失败分析](report/optimization_notes.md) · [验证总结](data/test_summary.md)。src/agent/docs 中日期文档为开发历史，不替代本页当前状态。

[Zynq测试包核对](report/zynq_intake.md) · [OpenOCD构建](build/openocd/readme.md) · [PL加载与检查](board/zynq/pl_preparation.md)。已确认fixed镜像有静态IP配置，但未把配置存在当作冷启动已验收；内嵌SSH主机私钥的镜像不公开。

原创内容采用 [MIT](license)，第三方范围见 [third_party_notices.md](third_party_notices.md)。
