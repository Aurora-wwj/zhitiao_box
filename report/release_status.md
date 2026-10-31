# 发布状态

2026-11-01：FPGA四分包已合并整理，仍非最终完整比赛提交包。

## 已整理并核对

- Agent正式源码／测试／PC UI；STM32重建输入、黄金main.c与最终HEX。
- 两轮真实四接口匿名JSON：601.7169→1001.08682ms，源码／提案／checkpoint及HEX身份一致，UART partial-tail、PL freshness保留。
- 最终FPGA RTL／BD／导出Tcl／wrapper／四份XDC／XPR；v5 bit的SHA与指导一致。
- baseline/final原始utilization及timing报告，指标已解析并对照指导；只匿名化主机信息。
- Vivado2017.4构建入口、四项外部IP的VLNV与37文件SHA、合法获取／检查步骤；不整体再分发未知许可IP。
- 4份匿名历史smoke参考、5项分包工具回归、6项FPGA整理回归（含实际Icarus RTL仿真及Tcl替身控制流检查）。Agent457项离线回归此前通过，生产代码本轮未改。

## 仍需补齐或验收

- Zhidiao_Linux_microSD.zip仍超过32MiB附件下载上限，无可读副本。需像FPGA一样分包上传，之后核对板端脚本、启动链、OpenOCD／Linux／BOOT来源和许可。
- 实物／接线照片与正式主报告的同版文件；现有设计报告PDF明确为整理初稿。
- 实际Vivado2017.4重建记录及Windows Keil重建／本次整理后的上板验收。云端没有这些工具和板卡；命令替身测试不证明Vivado重建成功。
- 时序覆盖审阅：原final报告有942个未约束最大延迟pin等HIGH警告，不能仅凭WNS0.709宣称全设计时序验收完成。
- 黄金RTL启动HIGH时首次值可能含残段、valid会保留旧值，须等待后续稳定周期并检查freshness；没有修改原v5来掩盖该边界。冷启动恢复仍未验收。

没有用旧Agent checkout、虚构源码或假成功日志填补缺件。分包步骤见upload_parts.md，FPGA证据详情见fpga_evidence.md。
