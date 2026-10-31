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
