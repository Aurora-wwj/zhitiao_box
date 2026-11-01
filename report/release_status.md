# 发布状态

2026-11-01材料澄清：大部分原始材料已存在，待补的是公开整理或新环境验证，不把原件存在误写成“已独立复现”。对应位置见[材料索引](material_index.md)。本轮调整部署配置与材料索引；正式技术报告另行处理。

## 已收到并整理

- Agent源码／PC UI／测试；STM32工程、黄金main.c与最终HEX，均有身份校验。
- 最终真实run_5d8e…两轮四接口601.7169→1001.08682 ms、模型提案、applied_edit、reviews、audit与events。公开脱敏JSON与网页原图已归档；同run不同导出不重复统计。
- 早期《第一次真实完整LLM测试记录.docx》和run_92dde…摘要已收到，本次再次核对Word终端JSON；该次明确PL-only，不算四接口。见llm_collaboration.md。
- FPGA RTL／BD／导出Tcl／wrapper／XDC／XPR、v5黄金位流、baseline／final资源及时序原报告。数据及来源见fpga_evidence.md，不再列作缺失原件。
- 四项外部IP按VLNV与37文件SHA交付，不整体再分发未知许可IP。Vivado2017.4构建入口、STM32构建入口已整理。
- Zynq测试包的OpenOCD／libusb源码及许可、887份脚本一致性、镜像组成、只读文件检查与工具构建入口已整理；独立与镜像内SSH主机私钥不公开。
- 私人v5部署配置已在上传包内核对，仅采用非秘密硬件字段；公开示例本来已为v5，本次修复向导仍生成v4的问题。v5＋LED为新建默认，--no-led仍保留v5及UART／PL；既有配置不自动迁移。
- 最新Linux结果与历史批次分别记录在data/test_summary.md。PC本机OpenOCD构建不作为ARM或真机结果；旧Windows438项／LED28项不冒充当前版本回归。

## 原件已存在，仍需整理或独立验证

- 队伍确认BOOT／Linux镜像及Vivado工程原件存在；当前公开仓库仍不具备完整BOOT／Linux／DT／rootfs从零构建说明、SDK／静态库来源及原OpenOCD精确编译记录。测试包不等于完整SD重建工程，含密钥镜像不直接发布。
- 照片／视频原素材待队伍选取整机、接线与四灯状态帧；当前仅四张网页原图。正式报告按单独流程定稿，本次不导入或修改报告Word／PDF。
- 实际Vivado2017.4与Windows Keil的新环境重建和日志；代码同步后的Windows全量回归须留提交号与工作区状态。云端软件／替身测试不证明这些环境已通过。
- 未约束路径等HIGH时序警告、复位输入HIGH首次测量残段、valid保留旧结果，以及SSH／PL冷启动恢复仍是未解决或待验收边界。本次不修改黄金RTL／位流来改变历史结果。

没有修改主JSON、黄金STM32源码、HEX、v5位流或原始实现报告，也不公开私人配置、API Key或私钥。
