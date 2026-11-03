# 从零复现

## 软件与状态

克隆本仓库，安装Python3.13。FPGA重建另需合法Vivado2017.4及四项外部IP。Linux采用ALINX预构建镜像的可复现rootfs定制与部署，步骤见[定制说明](../build/linux/readme.md)及[SD部署](../board/zynq/sd_deployment.md)。没有完整PetaLinux源工程，不执行也不声称源码级重建Linux；该范围不作为当前路线突然新增的必做任务。

在 src/agent 下设置 PYTHONPATH=src，运行 python -B -m unittest discover -s tests -v。Windows 可用 py -3.13 或 scripts/test_windows.ps1。
运行 start_demo.bat 验证离线 UI；start_ai_mock.bat 另需 API Key、同意联网和上下文分享，不依赖真实板卡。

## STM32

当前发布目录已统一小写；旧目录与原JSON路径的关系、私人配置迁移及校验见[path_migration.md](path_migration.md)。

Windows 安装 Keil MDK（最终材料使用 V5.06 update 6）与 STM32G4xx DFP 2.0.0（工程 PackID 声明）；工程目标 GPIO_PL_Test，设备 STM32G431RBTx。运行根目录 build/stm32/build.ps1 -KeilUv4 <UV4.exe绝对路径>。该脚本在当前 Linux 未实际执行，Keil 生成工具和 DFP 须由部署者提供。
保留原 core/src/main.c 字节；当前值为已通过的500。要演示 FAIL→编辑→PASS，用独立测试副本准备已知未达标的基线，并更新审批根路径；不要覆盖黄金源码／证据。

另有独立[GPIO_PL_Test_LED工程](../src/stm32/gpio_pl_test_led/readme.md)，GitHub目录为src/stm32/gpio_pl_test_led，实测时原目录同为GPIO_PL_Test。它在PA1翻转后同步板载八个用户LED，本次源码仍为500 ms延时。使用其mdk-arm/gpio_pl_test.uvprojx和独立deployment.local.led.json，允许文件改为core/src/main.c；Keil Target仍为GPIO_PL_Test。按项目说明用原real-build接口重新构建，保存新HEX／SHA和测量记录；不覆盖原工程或借用旧JSON。

## Zynq 与四接口

参考 board/hardware_setup.md 与 board/wiring.md。系统版本为PetaLinux2017.4／Linux4.9.0-xilinx／ARM32／BusyBox1.24.1，证据见data/linux_platform.json。先按rootfs复现和SD部署说明准备已知镜像，配置网口、严格known_hosts与非交互SSH；私钥由每块板生成保管。队伍报告原系统冷启动网络／SSH／USB／SWD已验证；免密公钥自动恢复和PL开机自动加载另行记录，仍按初始化步骤准备。
当前部署在初始化阶段完成v5 PL加载，再启动Agent及LED；Agent保持check_only与原四接口执行顺序。现有独立目录`$env:PYTHONPATH = "E:\zhidiao-agent\src"`设置、三步SSH公钥恢复（最后输出ZHIDIAO_SSH_KEY_OK）、v5文件SHA校验与手动加载统一见[初始化参考](../board/zynq/pl_preparation.md)，本仓库目录布局继续使用下方的相对路径设置。
本仓库build/fpga/zhidiao_observe_v5_led.bit先核对SHA fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6。当前部署按初始化说明手动加载，再使用check_only；提供镜像的BusyBox 1.24.1未包含timeout applet，手动加载示例使用已有cat。Agent内部可选加载／检查能力仍复用受审批约束的PLPreparation；load_verified另需已验证的BusyBox超时能力。步骤见../board/zynq/pl_preparation.md，只支持已确认的/dev/xdevcfg。check_only与prog_done不证明当前运行镜像身份。
OpenOCD0.12.0安装在/sd/tools/openocd/bin/openocd，scripts为/sd/tools/openocd/share/openocd/scripts，使用interface/stlink.cfg与target/stm32g4x.cfg及其依赖。源码／构建步骤见../build/openocd/readme.md；原上传ELF未再分发，新ARM产物须重新验收。原镜像SHA、rootfs修改及FIT重封装步骤已整理；含主机私钥的历史镜像不公开。本次HDF仅作当前硬件交接，v5继续runtime load，不要求重建BOOT.BIN。../board/zynq/check_files.sh可先做只读文件检查，不代替四接口测试。

在src/agent复制deployment.example.json为deployment.local.json，修改本机绝对路径与SSH路径；私人配置不上传。也可使用deployment-setup预览并经批准新建，向导不会覆盖已有配置。主示例及向导均为v5＋LED；deployment.no-led.example.json或向导--no-led只关闭灯，仍保持相同v5、UART与PL。确认v5已正确加载；不要把配置存在或check_only当作运行镜像已认证。运行 deployment-check --preview-only，再按提示执行实际检查；real-build／real-flash／real-log／real-test 使用现有 CLI --help 的参数，均保留审批。
启动 start_ui.bat，选择配置、工程、core/src/main.c、模型与 Key，勾选 UART。批准任务范围与每个 diff，确认每轮 audit 四工具齐全，PASS 来自 PL。导出新的报告，不能重放 data/ 中的历史审批。

报告区分别标注当前运行ID与历史所选ID：轮次表、审计JSON及“下载当前JSON”对应当前运行；历史选择只影响下载所选报告／恢复入口，不切换当前结果展示。资料中的旧截图可能尚无这些标签，按data/screenshots/readme.md的说明解读。复现前述实测案例要保留UART启用；PL-only基线截图不等于四接口验收。

## 验证边界

云端软件测试不等于 Windows Keil／Vivado 重建或本轮上板验证。Vivado 实际版本 2017.4，较指南推荐版本旧；正式报告需解释差异。重建步骤见 ../build/fpga/readme.md，外部IP清单见 ../src/fpga/readme.md。已提供Tcl，尚待真实Vivado执行并保存新构建记录。

安装Icarus Verilog和Tcl后，在根目录运行 `python -B -m unittest discover -s sim -p test_fpga_release.py -v` 验证RTL与整理脚本；未安装模拟器时RTL项会显示skip，不能称为仿真通过。原始全设计报告仍含未约束路径等HIGH警告，启动相位边界见FPGA说明。

## 独立工具命令（在 src/agent 的 PowerShell）

先配置本机绝对路径和认证；以下参数均可先加 --preview-only 查看，不会自行执行硬件。去掉预览参数后仍需审批。

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
$project = (Resolve-Path ..\stm32\gpio_pl_test).Path
py -3.13 -B -m zhidiao_agent deployment-check --config deployment.local.json --preview-only
py -3.13 -B -m zhidiao_agent real-build $project --config deployment.local.json --preview-only
py -3.13 -B -m zhidiao_agent real-flash "$project\mdk-arm\gpio_pl_test\gpio_pl_test.hex" --config deployment.local.json --preview-only
py -3.13 -B -m zhidiao_agent real-log --config deployment.local.json --duration-s 5 --preview-only
py -3.13 -B -m zhidiao_agent real-test --config deployment.local.json --expected-period-ms 1000 --tolerance-ms 50 --preview-only
```

项目当前已是达标固件，不能仅为了展示而直接改黄金源码；新一轮测试要生成自己的报告，不能使用历史 fingerprint 作为权限。

## 保存新的复现记录

新实验保留代码提交号、git status --short、工具版本、部署配置的非秘密硬件字段、构建日志和新产物SHA。Windows全量在src/agent运行scripts/test_windows.ps1，保存VERIFY_COMMIT、TEST_EXIT、Ran／OK／skip；提交号与未提交改动分别记录。最新Windows由队伍代码同步后补跑，不能提前填写通过。

Keil与Vivado必须在真实工具环境运行现有构建入口，保留完整命令、依赖版本和日志；新产物如与历史黄金SHA不同，重新绑定配置并验收，不覆盖旧证据。板卡实验另保存四工具audit、UART健康、freshness、目标容差及LED独立验收结果。

Linux复现验收按现有预构建基底、网络定制、FIT重封装、SD部署及冷启动日志执行，不把缺少原始PetaLinux／BSP源码工程写成必须另做一套Linux。保存基础系统来源／版本、输入输出SHA与实际修改；新的重封装产物需独立上板，不能借用原fixed的结果。已有材料映射见material_index.md，资源比较见fpga_evidence.md。
