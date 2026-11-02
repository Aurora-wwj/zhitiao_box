2026.11.2更新

# 发布状态

原始材料对应位置见[材料索引](material_index.md)。当前Linux交付范围及HDF以本页和build/linux/readme.md为准。

## 已收到并整理

- 已按指南统一123份既有文件的发布路径大小写，含旧STM32工程、展开许可证及其余readme；仅保留指南示例的两份README.md。历史JSON与黄金产物不改，路径映射及边界见path_migration.md。

- Agent源码／PC UI／测试；STM32工程、黄金main.c与最终HEX，均有身份校验。
- 新增并列LED同步Keil工程src/stm32/gpio_pl_test_led，说明名GPIO_PL_Test_LED；队友说明实测目录原名仍为GPIO_PL_Test。92份源码输入及许可证、实际500 ms主源码、工程引用及原始／公开SHA已整理，旧300 ms说明和生成产物未沿用。软件验证与真机边界见data/stm32_led_verification.txt，不把原工程JSON当作LED版实测。
- 最终真实run_5d8e…两轮四接口601.7169→1001.08682 ms、模型提案、applied_edit、reviews、audit与events。公开脱敏JSON与网页原图已归档；同run不同导出不重复统计。
- 早期《第一次真实完整LLM测试记录.docx》和run_92dde…摘要已收到，本次再次核对Word终端JSON；该次明确PL-only，不算四接口。见llm_collaboration.md。
- FPGA RTL／BD／导出Tcl／wrapper／XDC／XPR、v5黄金位流、baseline／final资源及时序原报告。数据及来源见fpga_evidence.md，不再列作缺失原件。
- 四项外部IP按VLNV与37文件SHA交付，不整体再分发未知许可IP。Vivado2017.4构建入口、STM32构建入口已整理。
- Zynq测试包的OpenOCD／libusb源码及许可、887份脚本一致性、镜像组成、只读文件检查与工具构建入口已整理；独立与镜像内SSH主机私钥不公开。
- Linux按队伍确认的实际路线补齐：ALINX预构建镜像→rootfs静态网络定制→FIT重封装→SD部署。版本、原／fixed SHA、实际差异、脚本和验证方法见build/linux/readme.md及board/zynq/sd_deployment.md；不把完整PetaLinux／BSP源码工程列为当前路线新增必做项，也不声称源码级重编整套Linux。
- 当前system_wrapper.hdf已按用户新导出原字节加入，10份内部成员、v5 bit／BD一致性及寄存器契约均已核对；最终PL在Linux启动后runtime load，不要求重建BOOT.BIN。
- 私人v5部署配置已在上传包内核对，仅采用非秘密硬件字段；公开示例本来已为v5，本次修复向导仍生成v4的问题。v5＋LED为新建默认，--no-led仍保留v5及UART／PL；既有配置不自动迁移。
- 最新Linux结果与历史批次分别记录在data/test_summary.md。PC本机OpenOCD构建不作为ARM或真机结果；旧Windows438项／LED28项不冒充当前版本回归。

## 原件已存在，仍需整理或独立验证

- 历史原件的完整PetaLinux／BSP源工程、FSBL ELF／boot BIF并未提供，作为范围事实保留，不列为本实现路线必须补做。基础镜像由ALINX配套介质取得，精确历史下载包标识／直链尚待归档；已收镜像以SHA锁定。image.ub.known_good由队伍确认存在，未在已核验两分包中出现，SHA待本地单独登记。
- 原系统冷启动网络／SSH、USB Host及OpenOCD／ST-Link／SWD已验证；本次版本截图与专门冷启动日志分别记录，云端未代行新镜像上板。免密authorized_keys持久化及PL开机自动加载不由密码登录截图推定通过。未约束路径HIGH警告、启动HIGH首次残段和sticky valid边界继续保留，黄金RTL／位流未改。

没有修改主JSON、黄金STM32源码、HEX、v5位流或原始实现报告，也不公开私人配置、API Key或私钥。
