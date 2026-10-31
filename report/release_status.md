# 发布状态

2026-11-01：FPGA四分包、Zynq Linux测试两分包均已合并整理，仍非最终完整比赛提交包。

## 已整理并核对

- Agent正式源码／测试／PC UI；STM32重建输入、黄金main.c与最终HEX。
- 两轮真实四接口匿名JSON：601.7169→1001.08682ms，源码／提案／checkpoint及HEX身份一致，UART partial-tail、PL freshness保留。
- 最终FPGA RTL／BD／导出Tcl／wrapper／四份XDC／XPR；v5 bit的SHA与指导一致。
- baseline/final原始utilization及timing报告，指标已解析并对照指导；只匿名化主机信息。
- Vivado2017.4构建入口、四项外部IP的VLNV与37文件SHA、合法获取／检查步骤；不整体再分发未知许可IP。
- 4份匿名历史smoke参考、5项分包工具回归、6项FPGA整理回归（含实际Icarus RTL仿真及Tcl替身控制流检查）。最初Agent457项回归已记录；本轮只调整网页报告标识，不改Controller／工具／审批执行逻辑。
- Zynq_Linux_Test的OpenOCD0.12.0／libusb1.0.30源码与完整许可、887份部署脚本与源码一致性、FIT组成／rootfs差异分析、只读文件检查和OpenOCD构建配方。独立及镜像内SSH主机私钥均排除；原ELF、BOOT／Linux镜像与历史HEX不原样公开。
- 最新Linux Python3.13 Agent全量459项、根sim18项回归均通过；新增当前／历史报告ID的JavaScript回归及图文证据校验。此前额外完成OpenOCD Linux x86-64本机静态ELF构建与--version检查，不作为ARM／真机结果。日志与边界见data/test_summary.md。
- 最终网页JSON与photos.zip的4张原图已归档：同一run_5d8e…的两轮四接口主案例、另一个仅有截图的PL-only基线场景分别说明。报名信息按对话截图转录，作品名称统一；完整diff包括一处注释变动。界面增加当前／历史报告ID说明，不改变执行和审批逻辑。

## 仍需补齐或验收

- 完整BOOT／Linux／DT／rootfs重建输入、SDK／静态库来源及原OpenOCD精确编译记录仍缺。已收到的Zynq_Linux_Test不等于完整SD；原Zhidiao_Linux_microSD.zip仍未取得可读副本，但已有测试包无需重复上传。
- 网页实测截图已补齐；板卡实物／接线照片和正式主报告的同版文件仍缺，现有设计报告PDF明确为整理初稿。
- 实际Vivado2017.4重建记录及Windows Keil重建／本次整理后的上板验收。云端没有这些工具和板卡；命令替身测试不证明Vivado重建成功。
- 时序覆盖审阅：原final报告有942个未约束最大延迟pin等HIGH警告，不能仅凭WNS0.709宣称全设计时序验收完成。
- 黄金RTL启动HIGH时首次值可能含残段、valid会保留旧值，须等待后续稳定周期并检查freshness；没有修改原v5来掩盖该边界。冷启动恢复仍未验收。

没有用旧Agent checkout、虚构源码或假成功日志填补缺件。分包步骤见upload_parts.md，FPGA证据详情见fpga_evidence.md。
