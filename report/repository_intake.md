# 智调盒参赛仓库整理：资料核对与发布检查

日期：2026-11-01。目标仓库：Aurora-wwj/zhitiaohe。

## 当前进度与阻塞

已完整读取 AMD 2026 选题指南、仓库整理指导、Skill 小修正三份 PDF。
上传的代码合集 ZIP 超过当前附件工具 32 MiB 单文件传输上限，未成功下载，工作区亦无该合集副本。
后续已收到独立Agent、Project、历史smoke、FPGA四分包及Zynq_Linux_Test两分包：已迁入并核验Agent、最终STM32、运行JSON、HEX、FPGA源输入／v5位流／原始实现报告和可公开的OpenOCD源码／许可。不以旧Agent checkout代替上传版本。Linux测试包不是完整SD重建输入，原大SD包仍未在本环境直接读取；队伍已确认其原镜像材料存在，不能据此说没有原件，也不能认定完整构建配方齐全。
此文档是整理依据，不代表硬件重建或本次真机验证；当前缺件与验收范围统一见release_status.md。

后续收到最终网页导出的zhidiao-run.json和photos.zip：前者与已归档run_5d8e…仅总elapsed_s差约0.02s，使用新导出作为主来源但不重复计数；后者含4张网页原图，没有报名介绍页原图或板卡实物照片。报名信息按对话截图转录，来源与图文对应见data/report_sources.json。

## 依据与优先级

AMD 自主选题 3.3.5.1：完整源码、仿真／验证、资源／时序、上板脚本和实测对比、可复现构建。
3.3.5.2：skill/ README 需明确适用范围、用法、失效条件、验证效果与失败／观察来源；不要求原子化或固定数量。
3.3.5.3：背景创新、框图、软硬件划分、优化前后、LLM 协作与自我纠错、Skill 提炼、从零复现。
3.3.5.4：建议目录及命名约束；结构可调整，但根 README 必须映射。现有第三方工程文件及 Python 包名的兼容性应保留并解释，不能盲目改名破坏工程引用。
工具推荐 2026.1／2025.2；实际使用 2017.4 时需如实说明版本与脚本复现边界，不能声称已经用新版重建。

## 目录映射

| 合集原目录 | 目标 | 处理 |
| --- | --- | --- |
| zhidiao-agent | src/agent | 正式源码、tests、启动器及必要文档；保持 zhidiao_agent 包名；排除嵌套 .git、运行历史、本机配置、备份 |
| Project/GPIO_PL_Test | src/stm32/gpio_pl_test | 保留 ioc、Core、Drivers、Keil 工程与启动文件；主源码逐字节保持，移除中间对象 |
| Zhidiao_PL/zhidiao_measure_ax7z020 | src/fpga/zhidiao_measure | 保留最终 RTL、XDC、BD、必要 IP／工程引用；排除缓存及无用 runs |
| 最终 v5 bit | build/fpga | 校验 SHA；配套构建 Tcl、资源与时序报告 |
| 最终 HEX | build/stm32 | 与可参数化 Keil 构建入口、来源说明一起整理 |
| 最小板端脚本 | board/zynq | 目录约定、加载和检查；BOOT／Linux／OpenOCD 二进制按来源与许可处理 |
| 最终运行 JSON | data | 另建匿名副本，原件不变；保留四工具 audit、模型提案、diff、测量、freshness、健康元数据和 SHA |
| 验证与旧 smoke | sim | 正式与历史脚本区分，注明环境及预期结果 |
| 可复用经验 | skill | 主题工作流、检查与失败案例，数量不限 |
| 主报告与复现 | report | 主设计报告同版副本、LLM 记录、优化说明、证据索引、从零复现 |

## Skill 组织（按能力，不按数量）

建议以下五个主题，可按实际材料合并或拆分；每个主题均需具备适用范围、触发条件、步骤、验证方法、已验证效果、来源和失效边界。

1. Hardware debug workflow：目标解释 → 可信 Controller → 四工具 → 证据 → 人工 diff → 下一轮；明确 PASS 由物理测量判断。
2. PL observation：100 MHz 计数、freshness、新边沿、寄存器一致性及计数／窗口限制。
3. UART observation：FIFO reset、单调时间戳、正常 partial_tail 与真正截断／溢出／解码／帧／奇偶错误。
4. Deployment and flashing：非交互 SSH、host key、构建产物身份、SCP SHA、OpenOCD program／verify／reset。
5. Failure diagnosis：BusyBox、SSH、镜像、UART、transport、预算与明确停止／恢复条件。

不编造不存在的十五份 Skill、PYNQ 实现或本地模型能力。可以附可复用校验脚本，但脚本需通过实际测试。

## 取得合集后必须核对的黄金证据

以下值来自整理指导，现已分别对Agent／STM32及FPGA独立分包原件核验：

- 最终 main.c SHA：79f6deb58231d3bc2cef887154c136a74e0da9e839a26ea41fd9468e205633cd。
- v5 bit SHA：fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6。
- 两轮周期：601.7169 → 1001.08682 ms；HAL_Delay 300 → 500。
- high_ms：300.36864／500.07403；fresh_edges：2／2；最终 run_5d8e... 的四工具及 partial_tail 原始记录。
- 资源 LUT 7274、FF 12083、BRAM 20.5、DSP 0、IOB 44；WNS 0.709 ns、TNS 0；必须对应原始报告。
- desktop.py 的真实 UI timeout_s=120，以及最终 runtime 配置、LED 与 UART 地址是否一致。

先验证这些内容，再更新主 README 为最终真实通过。PDF 的陈述不能替代原始运行 JSON、源码和实现报告。

FPGA补充检查发现的边界也已公开：final报告有未约束路径等HIGH警告，正WNS不等于完整时序覆盖；原RTL启动HIGH的首次值可能含残段。位流未重建、黄金RTL未改；详情见fpga_evidence.md及src/fpga/README.md。

## 发布前检查

- 不迁移 dropbear_rsa_host_key、任何私钥、真实 API Key、.env、本机 deployment.local 或备份。
- 生成匿名报告，屏蔽个人用户名、密钥路径、本机绝对路径和私有主机信息；保留原始证据的私下副本。
- 保留第三方原许可证；原创根许可范围明确，无法确认再分发权的供应商 IP／系统镜像／二进制先提供获取和构建说明。
- 保留最终 STM32 源文件原字节和对应 SHA，不清理会改变黄金源码身份的注释。
- 提供 v5 默认示例与无 LED 降级说明；不把运行时 prog_done 当作镜像身份验证。
- 构建脚本使用参数／环境变量，无个人绝对路径；Vivado／Keil 无可用环境时明确“脚本已整理，硬件重建待验证”。
- 根 README 映射 AMD 目录、当前结果、架构、硬件接线、模拟／真实入口、证据、Skill、许可与已知限制。
- 保存最终主报告同版副本，不把整理初稿标成官网已提交版本。
- 先运行 Agent 离线测试、公开包完整性／敏感字段检查、路径引用检查，再按可用工具验证构建入口。
- 推送前检查暂存文件与历史；只向 zhitiaohe 的 main 发布整理结果，不修改旧仓库或保存的仓库选择。
