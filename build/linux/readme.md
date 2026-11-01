# 基于ALINX预构建镜像的rootfs定制

本项目的实际路线是：ALINX官方／配套AX7Z020预构建Linux → 板卡启动验证 → 解包已有image.ub → 修改ramdisk/rootfs中的eth0网络配置 → 重新封装FIT → SD部署与冷启动复验。这里提供这条路线的复现方法，不声称拥有或执行过完整PetaLinux／BSP源码工程，不要求补做kernel、U-Boot或FSBL的源码构建。

## 基础系统与已知版本

| 项目 | 已确认值／依据 |
| --- | --- |
| 基础系统来源 | 队伍使用的ALINX AX7Z020官方／配套预构建镜像；厂商入口https://www.alinx.com/，由合法配套介质取得 |
| Target OS | PetaLinux 2017.4；队伍终端截图及两份已收ramdisk的/etc/issue一致 |
| Linux | 4.9.0-xilinx，armv7l／ARM 32-bit |
| BusyBox | v1.24.1 |
| 内核工具链 | Linaro GCC 6.2.1（2016.11），gcc 6.2.1 20161016 |
| 内核构建时间 | 2019-10-18 17:53:51 CST；为供应商内核时间，不是本次定制时间 |

截图中/etc/os-release不存在，版本核对使用uname、/proc/version、BusyBox及/etc/issue。以上是当前运行环境版本，不能反推一个未提供的PetaLinux源工程已完整交付。厂商原下载包的精确发行名称／历史直链尚未提供；不编造链接或把内核构建日期当成下载包版本，收到文件用下表SHA锁定。来源记录见[平台清单](../../data/linux_platform.json)。

## 输入与历史产物身份

| 文件 | SHA-256／说明 |
| --- | --- |
| BOOT.BIN | fa7c65b7880bf6c66ac4ce6186cb2dc88c7b6d3a48ed3c48e768c7cdb68f5641 |
| 原image.ub | 224b9b884352a931244541017024fdbff69297feeaadab2b1e5eb0d030bb0344 |
| 历史image_fixed.ub | 71fb28754b857b808340f87e9b54de2197d54141fd4c90eb1fd94360ac78635a |
| image.ub.known_good | 队伍确认本地有该备份；当前已核验两分包未包含它，SHA待本地单独登记，不假定等于另一镜像 |

两分包的原名为Zynq_Linux_Test.zip，已完整重组核对。它包含实际SD启动／部署材料。本文按这些已有文件复现部署，不再要求队伍因为目录名不同而重复提供。BOOT及镜像不直接提交Git；基础账号数据库、历史fixed中的设备专用私钥和供应商再分发边界仍按[许可说明](../../third_party_notices.md)处理。

已核对原件与历史fixed：kernel与FDT载荷逐字节相同，SHA分别为：

```text
kernel: 1d79eb0f62608d56b475b62c775497677003d61d9c7fc7469a7feb2e7e72cd7e
fdt:    bda8484b21a73218f455412e1f87e31c0fa52fdd3d44d285d1cddc08e06d6738
```

主要改动是etc/network/interfaces：保留其他网卡配置，将eth0由DHCP改为192.168.10.2/24，实际差异见[网络补丁](../../board/zynq/rootfs_network.patch)。历史fixed还增加过设备专用Dropbear主机私钥，并改变vt200／vt220的文件放置；这些差异如实登记，复现脚本仅重现网络定制，不复制现场私钥或无关终端文件变动。因此新产物不冒充与历史fixed字节相同。

## 离线复现

在Linux／WSL中准备Python3.13、U-Boot工具mkimage／dumpimage及device-tree-compiler的dtc。例如Debian／Ubuntu对应包为u-boot-tools与device-tree-compiler；这些主机工具用于重封装FIT，不改变镜像中的旧内核。保存实际使用版本。当前脚本只支持收到的inline-data FIT＋gzip newc CPIO布局，输入SHA固定为上表原image.ub；未知镜像、签名FIT及外置data布局会拒绝。

在仓库根目录执行，输入路径换成自己保留的原件，输出目录必须尚不存在：

```sh
python3.13 -B build/linux/customize_rootfs.py inspect /path/to/image.ub
python3.13 -B build/linux/customize_rootfs.py repack /path/to/image.ub --output build/linux/work-rootfs
```

输出目录已被.gitignore排除。脚本不连接板卡、不写SD、不执行ARM程序，不覆盖输入或旧输出。新目录包含kernel.bin、system.dtb、ramdisk.cpio.gz、image.its、image_fixed.ub、mkimage.log和build_result.json。解出的载荷仍是私人本机构建材料，不将整个工作目录推送Git。

实际处理步骤如下：

1. 解析FIT，核对三个载荷的原有SHA-1节点及默认conf@1配置，保留内核load／entry、FDT和启动配置。
2. 取出ramdisk@0的gzip载荷，在CPIO记录层只替换etc/network/interfaces中的eth0配置，保留其他文件、设备节点、uid／gid、权限、符号链接与硬链接信息，不向主机文件系统解包rootfs。
3. 将新CPIO压缩为gzip，生成引用原kernel、新ramdisk、原FDT的image.its，用mkimage -f重新封装并更新FIT载荷hash。保持FIT中原compression字段；收到镜像的ramdisk字段是none，而其载荷本身为gzip CPIO，不额外改变层级。
4. 重新解析生成镜像，核对kernel／FDT SHA、load／entry及配置元数据未变，静态网络配置存在且未嵌入设备专用Dropbear私钥。build_result.json明确boot_bin_rebuilt=false、board_tested=false。

可用标准工具查看和单独提取原载荷；下面索引已经对收到镜像核对，其他镜像应先检查列表：

```sh
dumpimage -l /path/to/image.ub
# 在单独的本机工作目录内：
dumpimage -T flat_dt -p 0 -o kernel.bin /path/to/image.ub
dumpimage -T flat_dt -p 1 -o system.dtb /path/to/image.ub
dumpimage -T flat_dt -p 2 -o ramdisk.cpio.gz /path/to/image.ub
```

脚本生成的image.its就是可审查的重新封装输入，mkimage日志保留实际调用结果。FIT时间戳使用原镜像timestamp，gzip的mtime固定为0；同一工具环境重复生成结果应相同。Python／gzip／mkimage版本变化可能改变整体SHA，验收重点同时包括组件SHA和唯一rootfs改动，不把新整体SHA写成旧fixed的SHA。

## HDF与最终PL

当前硬件交接文件为[src/fpga/zhidiao_measure/system_wrapper.hdf](../../src/fpga/zhidiao_measure/system_wrapper.hdf)，本次用户重新导出的原字节已加入，SHA为ff24021b5052bf91d5101e804fdd2917c457fc8a45db16caed89d349c3fd3198。此前Git树没有跟踪旧HDF，本次以此导出作为唯一公开交接文件，替代对原归档vendor-base HDF的依赖。

HDF来自Vivado2017.4、xc7z020clg400-2。其内system_wrapper.bit与现有v5黄金位流、system_bd.tcl与现有导出文件均逐字节一致；地址与LED参数已检查。PS初始化的c／h／tcl也与上传基础工程的对应文件一致。HDF中的Post-Synthesis模式／内部资源统计不替代原实现报告。

最终v5 PL在Linux启动后从/sd/pl/zhidiao_observe_v5_led.bit写入/dev/xdevcfg。复现当前PL功能沿用这个runtime load流程，不要求重新生成BOOT.BIN，不以本HDF宣称已拥有FSBL ELF／boot BIF或完整系统源码工程。步骤见[SD部署](../../board/zynq/sd_deployment.md)及[现有初始化说明](../../board/zynq/pl_preparation.md)。

## 验证范围

仓库提供离线重封装及回归检查，实际结果见[data/linux_customization_verification.txt](../../data/linux_customization_verification.txt)。队伍反馈此前已完成冷启动网络／SSH、USB Host与OpenOCD／ST-Link／SWD链路验证；当前截图确认运行版本，专门冷启动日志后续归档。云端没有新上板，不把离线新镜像写成已冷启动通过，也不从密码登录截图推导免密公钥已经持久化。
