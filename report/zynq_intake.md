# Zynq Linux测试包核对

两份分包已校验索引、块SHA、原件长度及整体SHA，恢复Zynq_Linux_Test.zip，含927条目、展开48026310字节。原件未改，不把分包或整个现场备份推入Git。详细源文件／许可证、保留与排除清单见data/zynq_linux_manifest.json。

## 实际发现

OpenOCD部署目录的ARM ELF为32位、ARM EABI5 hard-float、静态链接，原SHA记录于清单。未执行该上传程序。887份部署脚本与openocd-0.12.0源码中的tcl文件逐字节相同，包括stlink.cfg与stm32g4x.cfg。

两份源码包主许可分别为GPL-2.0-or-later和LGPL-2.1-or-later，各文件额外条款按原包保留；原始tar包及许可副本进入src/third_party/openocd。原二进制的精确编译器、选项及全部静态依赖源码未齐，因此不发布原ELF；另提供可审查构建配方，不能说它重现了原件每个字节。

image.ub和image_fixed.ub是FIT容器。只读解析确认两者kernel与fdt载荷的SHA完全相同，变化在ramdisk。解包rootfs索引可见：fixed增加Dropbear主机私钥、将eth0从DHCP改为静态192.168.10.2/24，并改变vt200／vt220条目。只记录相关路径与大小，不公开私钥、shadow等凭据内容。

包根目录也有独立dropbear_rsa_host_key。两处密钥都不发布；含内嵌密钥的整个fixed镜像排除，不因改个文件名就当作安全公开版本。BOOT／Linux镜像同时缺少完整重建来源及许可说明，因此公开SHA／组成证据和所缺输入，不提供原始镜像下载。

GPIO1.hex的SHA与最终运行产物不同，作为早期件记录，不覆盖黄金firmware.hex。arm_hello缺对应源文件，同样只保留元数据。包内没有独立自定义启动脚本；UART／PL脚本由现有Agent tools模块在受控计划内生成，不复制另一套硬件API。

## 构建与检查

build/openocd/build.py校验原tar SHA，在新目录构建并检查最终ELF、安装脚本身份。PC --native只验证源码／配方和新生成本机程序的版本，不能作为ARM／USB／SWD通过证据；ARM交叉及板卡测试仍需实际运行。构建结果与回归见data/test_summary.md。

board/zynq/check_files.sh是只读文件检查；PL加载复用已受审批约束的PLPreparation，没有增加第五个公开工具。现有生产Agent、黄金STM32和v5位流未改。

仍缺完整SD／BOOT／Linux重建工程、原工具链与编译记录、实物照片及正式主报告；镜像内存在静态IP或主机密钥不证明冷启动恢复、authorized_keys或PL加载已经验收。
