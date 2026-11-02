# 原始材料与公开仓库对照

依据2026-11-01队伍补充及本次已收到附件重新核对。“已有原件”“已公开整理”和“已独立复现／验收”分别记录。下列E盘位置是队伍原始目录标识，不是要求其他部署PC照抄的运行路径；私人配置、认证和含密钥镜像不公开。

| 原始材料 | 当前公开位置／状态 | 下一步 |
| --- | --- | --- |
| E:\zhidiao-agent\.zhidiao\runs\run_5d8e004954664f6c8f8ff0f85d31959b.json | Agent上传包已收到；data/final_run_sanitized.json为同run最后网页导出的脱敏副本；原始与公开SHA见data/report_sources.json | 使用model_decision、applied_edit、reviews、audit、events作主证据；不是缺少真机JSON |
| 第一次真实完整LLM测试记录.docx | 原Word已收到，终端JSON再次核对；公开摘要src/agent/docs/validation/first-real-loop-2026-10-28.md | 原件不原样公开；该run明确PL-only，不计为四接口 |
| E:\Zhidiao_PL\zhidiao_measure_ax7z020 | src/fpga/zhidiao_measure保留RTL／BD／Tcl／XDC／工程；build/fpga/zhidiao_observe_v5_led.bit已公开且SHA一致 | 合法外部IP仍按清单提供；在Vivado环境执行独立重建 |
| linux_ov5640.runs\impl_1\system_wrapper_utilization_placed.rpt、system_wrapper_timing_summary_routed.rpt；vendor_base_ax7z020对照 | build/fpga/reports中的baseline／final原报告及data/fpga_metrics.csv、data/fpga_metrics.json | 对比口径和警告见fpga_evidence.md；不是缺少资源报告，也不宣称全时序覆盖 |
| E:\Project\GPIO_PL_Test | src/stm32/gpio_pl_test；build/stm32/firmware.hex；data/stm32_sha256.json | 黄金main.c及最终HEX已与主JSON匹配，勿改字节冒充历史产物 |
| 新补充GPIO_PL_Test.zip；实测原目录同为GPIO_PL_Test，发布名GPIO_PL_Test_LED | src/stm32/gpio_pl_test_led；data/stm32_led_manifest.json | DK117E-G4八用户LED与PA1同步；源码保持500 ms延时，单独构建和验证，不借用旧JSON |
| E:\zhidiao-agent\deployment.local.json | 私人原配置已在上传包中核对，仅参考非秘密硬件字段；公开deployment.example.json与deployment.no-led.example.json在src/agent | 不复制私人配置。主示例与deployment-setup均v5＋LED；--no-led仅关闭灯，保留v5／UART／PL |
| BOOT／Linux及SD部署材料 | Zynq_Linux_Test两分包已完整重组，BOOT／image／fixed SHA和组成已核对；另有队伍确认的known_good备份 | 按ALINX预构建镜像做rootfs定制与FIT重封装；说明及脚本见build/linux，不声称源码级重建Linux，不要求补做完整PetaLinux工程；备份SHA单独登记 |
| 新导出system_wrapper.hdf | src/fpga/zhidiao_measure/system_wrapper.hdf；data/linux_platform.json | 当前交接版，bit／BD与黄金v5相同；Linux启动后runtime load，不要求重新生成BOOT.BIN |
| 照片／视频原素材 | 四张网页截图、硬件整机照 | 原素材已补充 |
| 最新Windows回归 | 历史438项与LED28项保留；最新Linux见data/test_summary.md | 代码同步后运行src/agent/scripts/test_windows.ps1，保存完整结果、skip、提交号及工作区状态 |

## 提交材料整理边界

LLM证据见[协作记录](llm_collaboration.md)，复现步骤及未完成项见[复现说明](reproduction.md)，资源对照见[FPGA证据](fpga_evidence.md)。正式技术报告按队伍的单独流程定稿，已归档。

未约束路径与启动HIGH首次测量边界仍保留。队伍报告原系统冷启动网络／SSH／USB／SWD已验；免密公钥持久化及PL开机自动加载分别记录。已提供的JSON、源码、HDF、位流和SD分包无需重复索取；补充重点是既有rootfs定制过程的公开整理和新环境验收记录。
