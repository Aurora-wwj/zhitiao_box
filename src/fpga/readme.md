# 最终 v5 FPGA 源输入

来自上传 Zhidiao_PL.zip，经四份小 ZIP 重组并核对整体 SHA。仅整理最终 zhidiao_measure_ax7z020，不发布缓存、旧 v2/v3/v4 位流、重复生成 IP 或整个 .runs。

`zhidiao_measure/` 保留原目录关系：原创计数 RTL、system.bd、原始工程 XPR、顶层 wrapper、四份 XDC，另将板级 BD 导出 Tcl 放到根目录。RTL、BD、XDC 与导出 Tcl 均保持原字节。XPR 的原绝对工程路径改为相对路径，wrapper 主机名匿名化；双 SHA 见 ../../data/fpga_manifest.json。

实际工具 Vivado 2017.4，part xc7z020clg400-2，top system_wrapper。100 MHz FCLK0 经 BUFG 接入测量核与 AXI；system.bd 与导出 Tcl 包含 v5 UART 和 LED。此设计仍保留 ALINX 原示例的摄像头／HDMI／VDMA 电路，整板资源数字不等于观测核单独资源。

当前交接文件为[system_wrapper.hdf](zhidiao_measure/system_wrapper.hdf)，由用户本次重新导出，原字节保留。内含system_wrapper.bit与黄金v5、system_bd.tcl与现有导出文件逐字节一致，10个成员及寄存器／LED参数由sim/linux_check.py检查，SHA见../../data/linux_platform.json。它作为当前交接版替代原归档vendor-base HDF；Git此前未跟踪旧HDF。内部MODE／资源字段不替代原impl报告。

目标Linux为PetaLinux2017.4／4.9.0-xilinx，基于ALINX预构建镜像做rootfs定制与部署，见[Linux说明](../../build/linux/readme.md)。最终PL在Linux启动后从/sd/pl/zhidiao_observe_v5_led.bit动态加载到/dev/xdevcfg，复现v5不要求重新生成BOOT.BIN，也不因有HDF就声称具备完整PetaLinux源工程。

## 四项外部 IP

未将上传目录 ip_repo、生成的 ipshared 或第三方网表整体套用根 MIT 发布。包内缺少覆盖所有供应商文件的完整再分发许可；清单保留每个 VLNV、相对路径、字节数与 SHA：../../data/fpga_external_ips.json。

| VLNV | 外部 ip_repo 内目录 |
| --- | --- |
| alinx.com.cn:user:i2c_extender:1.1 | alinx/i2c_extender |
| www.alinx.com.cn:user:alinx_ov5640:6.4 | alinx/ov5640_ip |
| digilentinc.com:ip:axi_dynclk:1.0 | ip/axi_dynclk_v1_0 |
| digilentinc.com:ip:rgb2dvi:1.3 | ip/rgb2dvi_v1_3 |

从合法取得的 ALINX AX7Z020 linux_ov5640、Vivado 2017.4 配套例程取得匹配 ip_repo；若没有，向板卡供应方申请该版本。官方入口 https://www.alinx.com/ ，不能用任意最新版同名 IP 代替。上传原件已含这四项依赖，拥有该原件的队友可在本机直接校验。源文件完整性检查：

```powershell
py -3.13 -B build/fpga/check_ip_repo.py D:/vendor/ip_repo
```

必须四项 VLNV 和 37 个文件均匹配。检查不执行其中代码，也不授予再分发许可。随后使用 ../../build/fpga/build.tcl；不建议直接依赖 XPR 内历史生成的 IP fileset。Vivado 内置 IP 由合法安装的 2017.4 生成。

## RTL 与验证边界

测量计数每 tick=10 ns，32 位时间戳约 42.95 s 回绕；无符号减法只适用于一个回绕周期以内的间隔。period/high 在完整观测后更新，valid 保持到复位；软件必须继续检查新边沿和快照一致性。

新增仿真确认：低电平启动、非 50% 占空比、频率变化、停止后保留旧值、计数回绕与再次复位。另确认一个原件边界：同步器复位为 0，外部输入已为 HIGH 时可能产生启动上升沿，首次 valid 并不保证覆盖复位前已经开始的完整物理周期；原注释中 WAIT_LOW 的描述不能作为该保证。应等待持续稳定的后续周期再验收；仅两个新边沿不构成所有启动相位都安全的证明。

本次整理没有修改已验证的黄金 RTL／位流，也没有重跑真机。若需严格拒绝该首次残段，应在独立测试中修订 RTL、重新生成位流并完成上板验证，不能在本仓库悄悄替换 v5 证据。
