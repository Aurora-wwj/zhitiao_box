# 软件与发布检查

以下按资料接收批次保留历史记录；当前结果与实现范围以末尾最近一节为准，不把历史测试数或硬件运行重复统计。

上传最终运行报告：真实两轮四接口 PASS，周期／freshness／UART健康与源码及HEX身份已由 sim/check_release.py 独立核对。
本次整理后 Linux Python 3.13 离线全量：457 tests in 24.324s，OK；sim/check_release.py 检查通过。未调用在线 API。Windows已有438项全量反馈和LED28项截图是历史证据，不能代替本次整理后执行。
本地不包含Keil、Vivado、板卡；未重编译固件／FPGA或重跑真机。当前缺件与后续FPGA接收状态见report/release_status.md。

发布检查反向验证：在临时副本篡改 main.c 后检查失败，黄金源码身份校验确实生效。CLI 与源码启动器 --help 可运行。生成的测试运行报告移出发布树，未打包公开。

STM32/CMSIS 原文件含上游 CRLF 与空格，按要求逐字节保留，不为消除格式警告而修改黄金源码。Git 暂存 main.c SHA 已核对；原创整理文档／脚本单独执行 whitespace 检查。

从Git暂存区导出的干净发布副本：457 tests in 24.420s，OK；导出副本的证据检查也通过，验证Git行尾处理没有改变黄金源文件和HEX。

历史smoke补充：4份文本通过AST语法、匿名化和双SHA清单验证，未运行其硬件调用。Agent源码与固件未改动，沿用本次整理已通过的457项测试；SD包因附件大小限制尚未检视。

归档检查新增反向验证：修改历史文本后的副本被SHA检查拒绝；正式证据／固件／Keil输入检查继续通过。

加入分包工具时，FPGA／SD附件均超过下载限制，尚未验证内容。新增大文件分包／重组工具的5项离线测试通过，含损坏／缺块／重复／混组拒绝；不改变原件。Agent代码与既有457项测试结果未改。

## FPGA四分包补充，2026-11-01

已重组原FPGA ZIP并核对整体SHA；14项公开源输入／位流／报告的原始与公开SHA已登记。v5 bit SHA与整理指导一致。四项外部IP的VLNV与37文件SHA已对原件执行检查通过，不执行或再分发未知许可文件。

Python3.13 + Icarus Verilog12.0实际运行根sim的11项回归，全部通过（6项FPGA+5项分包），含黄金位流篡改拒绝、报告数值与CSV一致性、IP哈希／VLNV正反例、Tcl语法及8种构建控制流情形、原RTL六组行为。日志见fpga_simulation.txt。Tcl为命令替身，不验证Vivado API、IP生成或布线。

RTL仿真确认sticky valid与startup HIGH首次残段的边界；原final报告的未约束路径／I/O等HIGH警告原样保留。不将本次检查说成硬件重建、所有启动相位正确或全设计时序闭合。黄金RTL、STM32 main.c、HEX和v5 bit均未改功能／字节；Agent生产代码本轮未改，不将既有457项测试冒充本轮重跑。SD仍待分包。

Git暂存区14项FPGA文件SHA全部匹配；从暂存树导出的干净副本运行sim/check_release.py通过，包含STM32／HEX／FPGA／报告和历史归档检查，确认Git行尾处理未破坏黄金字节。新增文件未发现私钥块、原个人路径或主机名；原创整理文件whitespace检查通过。

## Zynq Linux测试两分包，2026-11-01

原ZIP37273220字节及整体SHA已核对；只读检查确认887份部署OpenOCD脚本与提供源码相同。20份公开源码／许可文件逐项SHA核验；独立及rootfs内主机私钥、凭据内容和原镜像未进入公开树。fixed与原FIT的kernel／fdt相同，rootfs变化及静态IP仅作为配置存在证据，不声称冷启动通过。

Python3.13根sim现有15项回归全部通过（6 FPGA、5分包、4 Zynq），含实际Icarus12.0 RTL仿真、源码损坏／目录覆盖拒绝、ELF静态／ARM ABI解析、板端只读文件检查及坏SHA／缺工具拒绝。日志见zynq_release_tests.txt。文件检查不执行OpenOCD、MMIO或PL加载。Agent生产代码、黄金STM32／HEX／v5 bit本轮未改，既有457项Agent测试沿用已记录结果。

额外实际完成OpenOCD／libusb的Linux x86-64本机构建与安装到临时package目录，执行新生成程序的--version返回Open On-Chip Debugger0.12.0；ELF无动态段，ST-Link HLA与libusb宏均启用。证据见openocd_native_check.json。首次尝试暴露libtool -static仍可能动态链接；全局-all-static又会传入Jim Tcl的gcc，最终通过AM_LDFLAGS限定链接阶段修复，再从新目录完整构建通过。保留glibc NSS相关链接警告，不能从静态ELF推出所有运行路径无外部依赖。

未执行上传ARM ELF、ARM交叉构建、Windows／Keil／Vivado重建或本轮板卡测试。没有把PC编译成功等同Zynq OpenOCD／USB／SWD通过；Linux／BOOT完整构建配方和冷启动验收仍缺。

暂存区20份Zynq源码／许可SHA匹配；逐项检查Git暂存树未包含排除清单中的原ELF／镜像／HEX／整个ZIP或私钥文件名／私钥块。从Git暂存树导出的干净副本再次运行sim/check_release.py通过，原STM32／HEX／FPGA身份及本轮源码归档都保持一致。

## 最终网页导出与原图补充（本轮）

网页zhidiao-run.json与此前原件逐字段比较，仅总elapsed_s约差0.0199669s，仍为同一run_5d8e…；公开JSON沿用原路径脱敏并更新该值。4张原PNG逐字节复制、记录SHA；报名页原图未包含在ZIP，报名信息按对话截图转录。完整diff连同无关注释变动保留，截图原精度与网页三位小数对应，PL-only图独立标注。

Linux Python3.13.5 Agent全量：459 tests in 24.442s，OK，无skip；含2项新增JavaScript回归，实际执行内联前端脚本，确认当前／历史ID、轮次与JSON互不混淆、选择历史不发起执行请求。根sim：18 tests in 0.598s，OK，无skip，含Icarus12.0实际RTL仿真及3项新增证据回归；坏图片／CSV、错误PL-only归类和不完整diff均拒绝。命令与结果摘录见final_evidence_verification.txt。

sim/check_release.py通过。设计初稿Markdown／PDF同步更新为5页，表格和4张原图已实际渲染检查。Agent执行／审批逻辑、黄金STM32 main.c／HEX与v5位流未改；这不是新一次Windows／Keil／Vivado或真机测试。没有调用在线模型或板端工具。

暂存区4张PNG与原图SHA一致，STM32清单和14项FPGA文件SHA均保持。Git暂存树导出的干净副本通过sim/check_release.py及2项前端JavaScript测试，确认行尾归一化没有破坏证据或报告标识行为。

## 当前v5配置与材料状态同步，2026-11-01

修复deployment-setup仍生成v4路径／SHA的问题，统一当前v5＋LED，新增--no-led仍保留相同v5、UART与PL，仅关闭灯。公开两份示例本已为v5，未改其内容。新增3项端到端回归实际经过CLI解析、人工审批模拟、本地配置创建和load，另验证预览／拒绝不写配置且不连接板端；现有配置不会自动迁移或覆盖。

本轮Linux Python3.13.5 Agent全量462项，24.211s，OK，无skip；根sim18项，0.598s，OK，无skip，含已提供Icarus12.0的实际RTL仿真。初次未指定模拟器路径的一次运行跳过RTL，随后明确工具路径重跑全部18项，最终记录为全执行。sim/check_release.py和改动Markdown的本地链接检查通过。具体命令、基线提交与实测源码SHA见configuration_sync_verification.txt；此时工作区尚未提交，不虚构新提交号。

最终主JSON、黄金STM32 main.c／HEX、v5 bit、原实现报告及正式技术文档未改；只同步配置入口、材料索引、LLM证据说明与复现／验收边界。早期Word原件已重新核对，其PL-only结果不冒充完整四接口。私人配置／密钥未公开。本轮没有Windows／Keil／Vivado／在线模型或新上板执行；最新Windows由队伍同步代码后补跑并留提交号。

## STM32 LED同步补充工程

本次GPIO_PL_Test.zip的92份源码／工程／许可输入整理为src/stm32/gpio_pl_test_led，与原工程并列；说明名GPIO_PL_Test_LED，实测原目录名按队友说明记录为GPIO_PL_Test。实际main.c保持HAL_Delay(500)及原字节；附件旧300 ms说明与旧manifest不沿用，来源、双SHA及排除项见stm32_led_manifest.json。

根sim全量22项，0.772s，OK，无skip，含4项新增LED回归、GCC主机HAL替身及原Icarus RTL仿真。新工程由既有Agent API识别，八次翻转／八灯低有效跟随、500 ms延时调用和两次UART发送均通过主机检查。完整命令与边界见stm32_led_verification.txt；该检查不是Keil／ARM构建或真机电气／周期验收。

Agent生产代码与测试未改，沿用既有462项记录，不冒称本轮重跑。原黄金STM32源码／HEX、v5位流、原资源报告和主JSON保持原样，新LED工程不借用旧JSON作为新实测。全新工程的Keil构建与上板记录须单独保留。

## 提交路径规范同步，2026-11-01

以57693cb为基线，123份既有文件的发布路径统一小写，仅保留官方示例根README.md与skill/README.md。同步旧Keil／CubeMX／Legacy include路径、构建入口、两份公开部署示例、当前操作说明及校验器。旧JSON、完整diff、黄金main.c／HEX、位流、FPGA原报告及原PNG保持原字节；双路径／双SHA与24份不变证据见repository_path_map.json。

启动器优先识别core/src/main.c，并兼容原Core/Src/main.c与平铺main.c；选择新工程时会更新源码建议，不改变四接口、审批或PASS规则。新增3项Agent回归覆盖这三种布局及不存在源码的情况。

本轮Linux Python3.13.5 Agent全量465项，23.968s，OK，无skip；根sim全量26项，2.016s，OK，无skip。包含Icarus真实RTL仿真、原LED主机HAL替身，以及4项新增路径规范回归。GCC对两份Keil工程的42个C翻译单元实际完成预处理；现有Agent API可识别两工程的小写入口／输出并取得main源码快照。102份Python文件通过AST，110处Markdown本地链接目标存在。

sim/check_release.py通过；主机预处理不等于ARM编译／Keil链接，原HAL替身不等于LED真机验收。本轮没有执行Keil／Vivado／Windows或新上板，也没有调用在线模型、SSH或MMIO。命令与范围见path_migration_verification.txt；正式技术报告Word／PDF未纳入仓库，本次仅同步仓库设计初稿的失效路径引用。


## ALINX预构建Linux的rootfs定制与当前HDF，2026-11-01

按队伍确认的实现路线整理：ALINX配套预构建镜像→rootfs网络定制→FIT重封装→SD部署和冷启动验证。不将完整PetaLinux/BSP、kernel／U-Boot／DT源码工程或FSBL／boot BIF列为本路线新增必做任务，也不声称从源码重建整套Linux。系统版本由本次用户终端截图及原ramdisk的/etc/issue交叉确认，见linux_platform.json。

新system_wrapper.hdf按原字节交付，808369字节，SHA ff24021b…fd3198；内部10份成员／CRC、Vivado2017.4／xc7z020clg400-2、UART／LED地址均通过检查。内含bit与黄金v5、BD Tcl与现有导出文件逐字节相同。HDF作为当前交接版，Linux启动后继续runtime load v5，无需重新生成BOOT.BIN。

对收到的原image.ub实际离线重封装两次，输出9537626字节且逐字节相同，SHA 28ca54d6…daaa45。独立dumpimage提取结果与解析器一致；kernel／FDT未变，964份CPIO成员中仅etc/network/interfaces改变，其他文件／设备节点／链接／uid／gid／权限和记录保持。新产物不复制历史设备私钥或无关terminfo变动，因此不冒充历史fixed的相同SHA。完整结果见linux_repack_check.json，命令及工具版本见linux_customization_verification.txt。

根sim全量32项，2.066s，OK，无skip，含6项新增Linux／HDF回归、真实mkimage重封装、既有Icarus RTL及LED HAL替身。105份Python AST、142处Markdown本地链接目标检查通过；sim/check_release.py通过。Agent生产代码／测试未改，沿用已记录465项结果，不冒称本轮重跑。

未执行Windows／Keil／Vivado、Linux源码构建、BOOT打包、新镜像上板、SSH或MMIO。队伍报告原系统冷启动网络／SSH／USB／OpenOCD／SWD已验证，版本截图与专门冷启动日志分别登记；免密公钥持久化和PL开机自动加载不据此推定。image.ub.known_good为队伍确认的现有备份，未出现在已核验两分包中，SHA保留待本地登记，不要求重复上传整包。原始镜像／现场私钥及新生成镜像均未进入公开树。
