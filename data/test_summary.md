# 软件与发布检查

上传最终运行报告：真实两轮四接口 PASS，周期／freshness／UART健康与源码及HEX身份已由 sim/check_release.py 独立核对。
本次整理后 Linux Python 3.13 离线全量：457 tests in 24.324s，OK；sim/check_release.py 检查通过。未调用在线 API。Windows已有438项全量反馈和LED28项截图是历史证据，不能代替本次整理后执行。
本地不包含Keil、Vivado、板卡；未重编译固件／FPGA或重跑真机。FPGA/资源/照片缺件见report/release_status.md。

发布检查反向验证：在临时副本篡改 main.c 后检查失败，黄金源码身份校验确实生效。CLI 与源码启动器 --help 可运行。生成的测试运行报告移出发布树，未打包公开。

STM32/CMSIS 原文件含上游 CRLF 与空格，按要求逐字节保留，不为消除格式警告而修改黄金源码。Git 暂存 main.c SHA 已核对；原创整理文档／脚本单独执行 whitespace 检查。

从Git暂存区导出的干净发布副本：457 tests in 24.420s，OK；导出副本的证据检查也通过，验证Git行尾处理没有改变黄金源文件和HEX。

历史smoke补充：4份文本通过AST语法、匿名化和双SHA清单验证，未运行其硬件调用。Agent源码与固件未改动，沿用本次整理已通过的457项测试；SD包因附件大小限制尚未检视。

归档检查新增反向验证：修改历史文本后的副本被SHA检查拒绝；正式证据／固件／Keil输入检查继续通过。
