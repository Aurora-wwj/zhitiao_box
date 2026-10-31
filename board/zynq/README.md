# Zynq Linux测试材料与部署

已接收两份分包重组的Zynq_Linux_Test.zip：37273220字节，整体SHA-256为6cf4aaf320c9aaaae11b938725f0e9666cafa9fe6a97f8dc1a9a5159c1084b11。它包含BOOT、两份FIT镜像、早期HEX、ARM测试程序、静态OpenOCD及两份源码包；不等于完整SD卡或Linux／BOOT可重建工程。原Zhidiao_Linux_microSD.zip仍无可读副本，不混淆两份材料。

已发布：OpenOCD0.12.0／libusb1.0.30源码与完整许可、构建入口、文件检查、网络配置示例和现有PL加载入口说明。已核对部署的887份OpenOCD脚本全部与源码相同。来源与SHA见../../data/zynq_linux_manifest.json，检查详情见../../report/zynq_intake.md。

未发布：原静态ARM ELF（确切工具链与全部静态链接依赖来源未齐）、BOOT.BIN和image*.ub（缺完整构建来源；fixed镜像含主机私钥）、无源码的arm_hello和非最终GPIO1.hex。独立Dropbear主机私钥排除，绝不放入Git。最终固件仍以build/stm32和真实运行JSON的SHA为准。

## 目录与操作顺序

- /sd/pl/zhidiao_observe_v5_led.bit：本仓库build/fpga中的黄金v5。
- /sd/tools/openocd/bin/openocd：经目标板验收的ARM32 hard-float工具；版本0.12.0。
- /sd/tools/openocd/share/openocd/scripts：interface/stlink.cfg、target/stm32g4x.cfg及其依赖；不要只拷两份cfg。
- /sd/firmware/<run_id>/firmware.hex：由RealBackend上传并比较SHA后再program／verify／reset。

先准备自己的合法Linux／BOOT系统及非交互SSH，再按../../build/openocd/README.md构建／取得工具。复制到SD目录、确认v5路径后，可在板端运行：

```sh
sh check_files.sh /sd
```

脚本只检查文件／可执行位和v5文件SHA，不执行OpenOCD、不读写MMIO、不加载PL；输出hardware_result=NOT_TESTED、running_pl_identity=NOT_VERIFIED。它不代替deployment-check／real-flash／real-log／real-test。

PL加载／检查沿用已有Controller审批路径，详见pl_preparation.md。冷启动authorized_keys恢复与PL自动加载仍未验收，不能仅凭镜像中存在某配置就宣称持久化成功。

## 网络与SSH

已确认image_fixed.ub的rootfs有eth0静态192.168.10.2/24，示例见network_interfaces.example。PC参考192.168.10.1/24；应在目标系统合并配置并完成断电上电测试。该观察不证明当前板卡已启动此镜像，也不证明SSH免密已持久化。

每块板使用自己生成的Dropbear主机密钥，不复用上传包的私钥。通过可信板卡控制台检查现有密钥；缺失时可用目标系统的dropbearkey生成，按该系统的持久化方式保存。PC对照真实公钥指纹建立known_hosts；用户登录私钥保留在PC，只有对应公钥进入板端authorized_keys。不关闭StrictHostKeyChecking，不把主机私钥与登录私钥混为一谈。

完整系统复现仍需：FSBL／U-Boot及BOOT打包配置、Linux／DT／rootfs源码与构建配方、所用SDK／静态库来源、原OpenOCD确切编译记录及板卡冷启动验收。没有用猜测的镜像生成命令代替这些缺件。
