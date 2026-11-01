# SD部署与冷启动复验

本项目基于ALINX配套预构建Linux做rootfs定制，当前路线与镜像SHA见[Linux定制说明](../../build/linux/readme.md)。无需为复现v5 runtime PL重新构建BOOT.BIN。下面是由部署者在备用SD和真实AX7Z020上执行的方法；云端整理不会格式化SD、上传现场镜像或连接板卡。

## 准备与目录

保留现有已通过的SD及启动文件；用备用卡按AX7Z020配套资料准备FAT启动分区，并保留该资料的分区及启动开关设置。已收到材料未说明全部分区参数，不凭空给出扇区／dd命令。现有根文件系统是FIT内ramdisk，按当前SD契约使用以下布局：

```text
sd_root/
  BOOT.BIN
  image.ub
  image.ub.known_good
  pl/zhidiao_observe_v5_led.bit
  tools/openocd/bin/openocd
  tools/openocd/share/openocd/scripts/...
  firmware/<run_id>/firmware.hex
  logs/
```

BOOT.BIN及image.ub是板端启动文件的约定名称，不将它们擅自改成仓库目录命名，也不在Agent普通烧录流程中覆盖。image.ub.known_good是本机回退备份，分别记录SHA；不能凭名称认定与原image.ub相同。

1. 校验保留的BOOT.BIN、原image.ub及历史fixed的SHA，来源见Linux定制说明；用新脚本复现时另保存build_result.json。
2. 将选定且验收过的fixed产物作为SD根目录image.ub安装，保留原件及回退备份。只把image_fixed.ub放旁边不代表当前U-Boot会启动它；按现有契约检查实际加载文件。
3. 保留原BOOT.BIN，将黄金v5位流放到pl/zhidiao_observe_v5_led.bit。该bit SHA为fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6。
4. 部署已验收的ARM32 hard-float OpenOCD0.12.0及完整scripts目录。PC本机构建的x86-64程序不能放到板端；源码构建与验证入口见[OpenOCD说明](../../build/openocd/readme.md)。
5. 安全弹出备用卡，按板卡资料设SD启动，记录串口启动日志。进入Linux后确认SD挂载点为/sd，设备节点以实际识别为准；原始PetaLinux根文件系统中的fstab并不单独证明/sd已自动挂载。

## 冷启动和链路记录

每轮保存本次镜像SHA、实际加载文件、板卡／卡标识、完整启动日志、时间和代码提交号，记录断电再上电的过程。重封装工具的board_tested=false只有在真实复验后才能由独立记录补充，不能手改历史报告冒充运行。

| 项目 | 操作／期望证据 |
| --- | --- |
| 系统版本 | uname -a；cat /proc/version；/bin/busybox \| head -n 1；cat /etc/issue。期望4.9.0-xilinx、ARM32、BusyBox1.24.1、PetaLinux2017.4；/etc/os-release不存在不作为失败 |
| 网络 | PC使用192.168.10.1/24，板端ifconfig eth0显示192.168.10.2与255.255.255.0；断电后复查，而非仅执行运行时ifconfig |
| SD | mount输出中确认/sd；核对BOOT／image、工具和v5文件身份 |
| SSH | 按可信主机指纹建立known_hosts，检查连接；自动Agent另外要求BatchMode公钥登录成功 |
| USB Host | 保存ST-Link接入后的dmesg及/sys/bus/usb/devices枚举结果，再核验OpenOCD输出 |
| OpenOCD／SWD | 下面的init／targets检查应识别ST-Link和STM32G4；后续通过原real-flash流程核验program／verify／reset |
| v5 PL | 按初始化说明先核对bit SHA、手动写入/dev/xdevcfg并检查prog_done；随后由现有四接口读取新鲜物理证据 |
| 闭环 | 新运行JSON包含四工具audit、UART健康、PL freshness及确定性PASS／FAIL，不借用历史JSON证明新SD通过 |

板端OpenOCD连接检查示例（由部署者执行，不是新增Agent工具）：

```sh
/sd/tools/openocd/bin/openocd \
  -s /sd/tools/openocd/share/openocd/scripts \
  -f interface/stlink.cfg -f target/stm32g4x.cfg \
  -c "init; targets; shutdown"
```

SSH公钥恢复、PYTHONPATH及v5动态加载使用[现有初始化步骤](pl_preparation.md)。当前顺序继续是Linux启动 → 网络／SSH就绪 → 初始化手动加载v5 → 启动Agent与LED → build／flash／UART／PL，prepare_policy保持check_only。提供的BusyBox1.24.1没有timeout，手动加载使用已有cat，不能直接切换为依赖timeout的load_verified。

队伍报告已验证冷启动网络／SSH联通、USB Host及OpenOCD／ST-Link／SWD；本次版本截图包含密码提示，SSH可连接与免密公钥持久化分别记录。新复现镜像不嵌入现场Dropbear主机私钥；每块板生成并妥善保存自己的主机身份，若变化须可信核对新指纹。这里不声称已验收PL开机自动加载或authorized_keys自动恢复。

对原基底的只读检查确认：etc/init.d/dropbear的start分支会在缺少主机密钥时调用dropbearkey生成，再启动服务。该行为不保证密钥跨initramfs冷启动持久化；新卡首次启动通过可信串口核对主机公钥指纹，再建立PC known_hosts。不要通过复制历史镜像中的同一私钥来制造一致指纹，也不关闭StrictHostKeyChecking。

当前没有原始完整PetaLinux/BSP、kernel／U-Boot／设备树源码、rootfs整套源码配方及FSBL ELF／boot BIF；这是实现范围说明，不列为本路线突然新增的必补开发任务。补充材料重点是来源、配置改动、重封装、SD部署及实际复验记录。
