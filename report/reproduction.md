# 从零复现

## 软件与状态

克隆本仓库，安装Python3.13。FPGA源输入、v5位流和实现报告已收到，重建另需合法Vivado2017.4及四项外部IP。Zynq Linux测试包已核对并整理OpenOCD源码／许可及构建入口；完整BOOT／Linux／rootfs构建输入仍缺，不能仅凭当前仓库重建整套系统镜像。

在 src/agent 下设置 PYTHONPATH=src，运行 python -B -m unittest discover -s tests -v。Windows 可用 py -3.13 或 scripts/test_windows.ps1。
运行 start_demo.bat 验证离线 UI；start_ai_mock.bat 另需 API Key、同意联网和上下文分享，不依赖真实板卡。

## STM32

Windows 安装 Keil MDK（最终材料使用 V5.06 update 6）与 STM32G4xx DFP 2.0.0（工程 PackID 声明）；工程目标 GPIO_PL_Test，设备 STM32G431RBTx。运行根目录 build/stm32/build.ps1 -KeilUv4 <UV4.exe绝对路径>。该脚本在当前 Linux 未实际执行，Keil 生成工具和 DFP 须由部署者提供。
保留原 Core/Src/main.c 字节；当前值为已通过的500。要演示 FAIL→编辑→PASS，用独立测试副本准备已知未达标的基线，并更新审批根路径；不要覆盖黄金源码／证据。

## Zynq 与四接口

参考 board/hardware_setup.md 与 board/wiring.md。配置网口、严格 known_hosts 与非交互 SSH；私钥自行生成保管，不进入仓库。上电后恢复 authorized_keys、准备 PL（冷启动持久化未验收）。
本仓库build/fpga/zhidiao_observe_v5_led.bit先核对SHA fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6。实际PL加载／检查复用已有受审批约束的PLPreparation，步骤见../board/zynq/pl_preparation.md；只支持已确认的/dev/xdevcfg。check_only与prog_done不证明当前运行镜像身份。
OpenOCD0.12.0安装在/sd/tools/openocd/bin/openocd，scripts为/sd/tools/openocd/share/openocd/scripts，使用interface/stlink.cfg与target/stm32g4x.cfg及其依赖。源码／构建步骤见../build/openocd/README.md；原上传ELF未再分发，新ARM产物须重新验收。Linux／BOOT构建来源仍缺，含主机私钥的原镜像不公开。../board/zynq/check_files.sh可先做只读文件检查，不代替四接口测试。

在 src/agent 复制 deployment.example.json 为 deployment.local.json，修改所有本机绝对路径与 SSH 路径；确认 v5 已加载。运行 deployment-check --preview-only，再按提示执行实际检查；real-build／real-flash／real-log／real-test 使用现有 CLI --help 的参数，均保留审批。
启动 start_ui.bat，选择配置、工程、Core/Src/main.c、模型与 Key，勾选 UART。批准任务范围与每个 diff，确认每轮 audit 四工具齐全，PASS 来自 PL。导出新的报告，不能重放 data/ 中的历史审批。

## 验证边界

云端软件测试不等于 Windows Keil／Vivado 重建或本轮上板验证。Vivado 实际版本 2017.4，较指南推荐版本旧；正式报告需解释差异。重建步骤见 ../build/fpga/README.md，外部IP清单见 ../src/fpga/README.md。已提供Tcl，尚待真实Vivado执行并保存新构建记录。

安装Icarus Verilog和Tcl后，在根目录运行 `python -B -m unittest discover -s sim -p test_fpga_release.py -v` 验证RTL与整理脚本；未安装模拟器时RTL项会显示skip，不能称为仿真通过。原始全设计报告仍含未约束路径等HIGH警告，启动相位边界见FPGA说明。

## 独立工具命令（在 src/agent 的 PowerShell）

先配置本机绝对路径和认证；以下参数均可先加 --preview-only 查看，不会自行执行硬件。去掉预览参数后仍需审批。

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
$project = (Resolve-Path ..\stm32\gpio_pl_test).Path
py -3.13 -B -m zhidiao_agent deployment-check --config deployment.local.json --preview-only
py -3.13 -B -m zhidiao_agent real-build $project --config deployment.local.json --preview-only
py -3.13 -B -m zhidiao_agent real-flash "$project\MDK-ARM\GPIO_PL_Test\GPIO_PL_Test.hex" --config deployment.local.json --preview-only
py -3.13 -B -m zhidiao_agent real-log --config deployment.local.json --duration-s 5 --preview-only
py -3.13 -B -m zhidiao_agent real-test --config deployment.local.json --expected-period-ms 1000 --tolerance-ms 50 --preview-only
```

项目当前已是达标固件，不能仅为了展示而直接改黄金源码；新一轮测试要生成自己的报告，不能使用历史 fingerprint 作为权限。
