# Zynq Linux测试材料与部署

已接收两份分包重组的Zynq_Linux_Test.zip：37273220字节，整体SHA-256为6cf4aaf320c9aaaae11b938725f0e9666cafa9fe6a97f8dc1a9a5159c1084b11。它包含实际SD启动／部署所用BOOT、两份FIT、早期HEX、ARM测试程序、静态OpenOCD及两份源码包。队伍另确认有image.ub.known_good备份及本次新导出的HDF；备份未包含在已核验两分包中，SHA单独记录，不因包名不同重复索取整份SD材料。

Linux按实际完成路线交付：ALINX AX7Z020预构建镜像→ramdisk/rootfs网络定制→FIT重封装→SD部署和冷启动链路验证。详见[定制说明](../../build/linux/readme.md)及[SD部署](sd_deployment.md)。目前没有完整PetaLinux／BSP源码工程，不声称从源码重编Linux，也不把补做它列为本路线新增必做项。已确认PetaLinux2017.4、Linux4.9.0-xilinx、ARM32、BusyBox1.24.1。

已发布：OpenOCD0.12.0／libusb1.0.30源码与完整许可、构建入口、文件检查、网络配置示例和现有PL加载入口说明。已核对部署的887份OpenOCD脚本全部与源码相同。来源与SHA见../../data/zynq_linux_manifest.json，检查详情见../../report/zynq_intake.md。

未直接发布：原静态ARM ELF（确切工具链与全部静态链接依赖来源未齐）、BOOT.BIN和image*.ub（供应商整镜像再分发范围未确认、含账号数据库；历史fixed还含设备专用私钥）、无源码的arm_hello和非最终GPIO1.hex。独立Dropbear主机私钥排除；公开镜像SHA、组件差异和可执行重封装方法。最终STM32固件仍以build/stm32和真实运行JSON的SHA为准。

## 目录与操作顺序

- /sd/pl/zhidiao_observe_v5_led.bit：本仓库build/fpga中的黄金v5。
- /sd/tools/openocd/bin/openocd：经目标板验收的ARM32 hard-float工具；版本0.12.0。
- /sd/tools/openocd/share/openocd/scripts：interface/stlink.cfg、target/stm32g4x.cfg及其依赖；不要只拷两份cfg。
- /sd/firmware/<run_id>/firmware.hex：由RealBackend上传并比较SHA后再program／verify／reset。

按已收预构建基底的rootfs／SD步骤准备Linux／BOOT和非交互SSH，再按../../build/openocd/readme.md构建／取得工具。复制到SD目录、确认v5路径后，可在板端运行：

```sh
sh check_files.sh /sd
```

脚本只检查文件／可执行位和v5文件SHA，不执行OpenOCD、不读写MMIO、不加载PL；输出hardware_result=NOT_TESTED、running_pl_identity=NOT_VERIFIED。它不代替deployment-check／real-flash／real-log／real-test。

当前v5 PL在Linux启动后的初始化阶段动态加载，再启动Agent与LED；Agent使用check_only，保持现有四接口顺序，不要求重新生成BOOT.BIN。本次[src/fpga/zhidiao_measure/system_wrapper.hdf](../../src/fpga/zhidiao_measure/system_wrapper.hdf)内含位流与黄金v5逐字节一致。路径变量、三步SSH公钥恢复、v5 SHA与手动加载统一见[板端初始化说明](pl_preparation.md)。队伍报告原系统冷启动网络／SSH／USB／SWD验证通过；单独冷启动日志待归档，authorized_keys恢复及PL开机自动加载不由本次版本截图推定通过。

已对提供的image_fixed.ub做只读检查：`/bin/busybox`指向BusyBox 1.24.1的busybox.nosuid，applet列表没有`timeout`。当前手动加载说明使用已有`cat`，Agent保持`check_only`；可选`load_verified`需要额外确认其BusyBox超时依赖可用，不把该镜像当作已满足此策略的全部条件。

## 网络与SSH

已确认image_fixed.ub的rootfs有eth0静态192.168.10.2/24，示例见network_interfaces.example。PC参考192.168.10.1/24；复现时合并配置并做断电上电测试。队伍反馈原系统已完成该链路验证；新的重封装产物仍需独立记录，SSH联通与免密公钥持久化分别验收。

每块板使用自己生成的Dropbear主机密钥，不复用上传包的私钥。通过可信板卡控制台检查现有密钥；缺失时可用目标系统的dropbearkey生成，按该系统的持久化方式保存。PC对照真实公钥指纹建立known_hosts；用户登录私钥保留在PC，只有对应公钥进入板端authorized_keys。不关闭StrictHostKeyChecking，不把主机私钥与登录私钥混为一谈。

当前Linux复现交付包括基础镜像来源／版本和SHA、rootfs实际修改、FIT重封装、SD部署和冷启动复验方法。没有FSBL ELF／boot BIF、原完整PetaLinux／kernel／U-Boot／DT源码工程，因此不提供声称可从源码重建整套Linux的petalinux-build指令；这不是当前预构建镜像定制路线的新增必补任务。
