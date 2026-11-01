# Zynq Linux测试包核对

两份分包已校验索引、块SHA、原件长度及整体SHA，恢复Zynq_Linux_Test.zip，含927条目、展开48026310字节。原件未改，不把分包或整个现场备份推入Git。详细源文件／许可证、保留与排除清单见data/zynq_linux_manifest.json。

## 实际发现

OpenOCD部署目录的ARM ELF为32位、ARM EABI5 hard-float、静态链接，原SHA记录于清单。未执行该上传程序。887份部署脚本与openocd-0.12.0源码中的tcl文件逐字节相同，包括stlink.cfg与stm32g4x.cfg。

两份源码包主许可分别为GPL-2.0-or-later和LGPL-2.1-or-later，各文件额外条款按原包保留；原始tar包及许可副本进入src/third_party/openocd。原二进制的精确编译器、选项及全部静态依赖源码未齐，因此不发布原ELF；另提供可审查构建配方，不能说它重现了原件每个字节。

image.ub和image_fixed.ub是FIT容器。只读解析确认两者kernel与fdt载荷的SHA完全相同，变化在ramdisk。解包rootfs索引可见：fixed增加Dropbear主机私钥、将eth0从DHCP改为静态192.168.10.2/24，并改变vt200／vt220条目。只记录相关路径与大小，不公开私钥、shadow等凭据内容。

包根目录也有独立dropbear_rsa_host_key。两处密钥都不发布；历史fixed、基础账号数据库及供应商整镜像再分发边界分别记录，不把原镜像直接推入Git。Linux实际路线是ALINX配套预构建镜像的rootfs定制与部署，公开来源／版本、SHA、修改及可执行重封装方法，不将完整源码级重建工程列为必须另做的任务。

GPIO1.hex的SHA与最终运行产物不同，作为早期件记录，不覆盖黄金firmware.hex。arm_hello缺对应源文件，同样只保留元数据。包内没有独立自定义启动脚本；UART／PL脚本由现有Agent tools模块在受控计划内生成，不复制另一套硬件API。

## 构建与检查

build/openocd/build.py校验原tar SHA，在新目录构建并检查最终ELF、安装脚本身份。PC --native只验证源码／配方和新生成本机程序的版本，不能作为ARM／USB／SWD通过证据；ARM交叉及板卡测试仍需实际运行。构建结果与回归见data/test_summary.md。

board/zynq/check_files.sh是只读文件检查；PL加载复用已受审批约束的PLPreparation，没有增加第五个公开工具。现有生产Agent、黄金STM32和v5位流未改。

本轮用户终端截图确认PetaLinux2017.4、Linux4.9.0-xilinx、ARM32、BusyBox1.24.1、Linaro GCC6.2.1及2019-10-18内核构建时间；/etc/issue也与两份原ramdisk相符。队伍报告原系统冷启动网络／SSH／USB及SWD链路已验证，单独日志待归档；云端新重封装产物没有上板，免密公钥持久化和PL开机自动加载另行记录。

新导出HDF已加入作为当前唯一公开交接版，内含v5 bit及BD与黄金文件逐字节相同。原PetaLinux／BSP、kernel／U-Boot／设备树源码、完整rootfs源码配方、FSBL ELF／boot BIF未找到，不声称执行petalinux-build／源码级BOOT打包。当前v5在Linux启动后从/sd/pl/zhidiao_observe_v5_led.bit写入/dev/xdevcfg，不要求重建BOOT.BIN。

完整方法见[Linux定制](../build/linux/readme.md)与[SD部署](../board/zynq/sd_deployment.md)。已收到两份SD材料分包，不再因原目录名称不同而要求重复提供；known_good备份按队伍说明记录存在，SHA不编造。
