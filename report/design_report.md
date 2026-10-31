# 智调盒——AI 上板摆渡站（整理初稿）

本文件与同名 PDF 是基于已收到材料编写的设计报告初稿，不是已确认的官网提交版本。FPGA材料已补入；正式主报告尚待提供并统一版本。

## 背景与创新

嵌入式代码修改需要跨越 PC 编译、远程部署、MCU 执行和物理测量。智调盒以独立 PL 证据组织可审计的 AI 调试闭环，避免仅凭模型或串口文字判断达标。适用范围当前为已配置 GPIO 的完整周期调节，不声称任意外设自动初始化。

## 原理与软硬件划分

用户任务 → PC Agent → Controller 安全边界 → Keil rebuild → SCP/SHA → Zynq OpenOCD/ST-Link → STM32 → UART/PL → 确定性判定 → AI 建议及人工批准。
PC 处理自然语言、源文件白名单、审批、预算和报告；PS 提供 SSH／寄存器与烧录服务；PL 实现100 MHz独立周期／高电平观测、freshness、UART与LED接口；STM32执行目标固件。

## 实现与接口

build_firmware(project_path)、flash_firmware(firmware_path)、read_target_log(duration_s)、run_hardware_test(test_id,params)，contract_version=0.2。
PA1→M18，PA2→M17，UART115200 8N1；数据地址和预算见board/wiring.md与部署示例。FPGA原创RTL、BD、导出Tcl、XDC、XPR、黄金v5位流及原始实现报告均已从四分包整理。LED约束与GPIO默认0xF已核对。

## 优化与验证

最终真实run两轮四工具：601.7169 ms FAIL，经HAL_Delay(300)→500，实测1001.08682 ms PASS，目标1000±50 ms；两轮新边沿2。第一轮正常UART半行没有阻断PL。源码、提案和HEX哈希已交叉核对，数据见data/。
原baseline→final：LUT6756→7274、FF10853→12083、BRAM20.5不变、DSP0、IOB38→44；整套设计增加观测／UART／LED开销，不是同功能资源压缩。WNS1.091→0.709ns，TNS均0；报告仍有942个未约束最大延迟pin、缺输入／输出时序约束等HIGH警告，不等于全设计时序覆盖完成。原件与解析表见report/fpga_evidence.md、data/fpga_metrics.csv。

Linux已实际运行Icarus RTL仿真，覆盖周期、高电平、边沿、新周期、sticky valid、复位和32位回绕。原件存在启动HIGH时首次值可能包含残段的边界，不能仅凭valid或两个新边沿保证所有启动相位安全；已保留说明，未改黄金RTL／位流。此测试不替代全BD仿真或板卡验证。软件验证见data/test_summary.md。

## LLM协作与Skill提炼

模型理解目标并根据证据提出单文件diff；Controller控制路径、顺序、最大尝试、超时、人工审批和停止。原始模型提案保留于匿名运行JSON，提示模板在Agent源码；完整HTTP对话尚未提供。
Skill按闭环调试、可信PL、UART、部署和失败排查五类组织，各自注明来源、适用范围、使用和边界，不按固定文件数量拆分。

## 复现与限制

详见report/reproduction.md及build/fpga/README.md。实际Vivado2017.4，与指南推荐新版存在差异；已提供重建Tcl，但Vivado／Keil重建未在云端执行。四项供应商IP因完整再分发许可未附，按VLNV／37文件SHA和合法获取步骤列为外部依赖；不能称为无外部依赖的一键构建。UART有限窗口与字节上限，单文件修改且需审批，依赖第三方API的可用性。

Zynq_Linux_Test两分包已核对，带许可的OpenOCD／libusb源码及构建入口公开，887份部署脚本与源码一致。fixed FIT与原件kernel／fdt相同，ramdisk增加静态IP和主机私钥等；私钥和含密钥镜像不公开，原ARM ELF因确切静态依赖来源不齐也不直接发布。完整BOOT／Linux构建配方、实物照片与正式主报告仍待补齐，SSH authorized_keys与PL冷启动持久化待实测，不能从配置存在推断验收通过。

本轮根sim的15项检查通过，另实际完成OpenOCD Linux x86-64本机静态构建与0.12.0版本检查，构建中的libtool／Jim Tcl链接问题已修正；保留glibc NSS警告。此结果不代表ARM交叉编译、Zynq／USB／SWD或烧录已经复验，详见data/openocd_native_check.json。
