# 软件与发布检查

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
