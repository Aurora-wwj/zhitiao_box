# 从零复现

## 软件与状态

克隆本仓库，安装Python3.13。FPGA源输入、v5位流和实现报告已收到，重建另需合法Vivado2017.4及四项外部IP。Zynq Linux测试包已核对并整理OpenOCD源码／许可及构建入口；队伍已确认BOOT／Linux镜像原件存在，但完整BOOT／Linux／rootfs从零构建输入与说明尚未齐全，不能仅凭当前仓库重建整套系统镜像。

在 src/agent 下设置 PYTHONPATH=src，运行 python -B -m unittest discover -s tests -v。Windows 可用 py -3.13 或 scripts/test_windows.ps1。
运行 start_demo.bat 验证离线 UI；start_ai_mock.bat 另需 API Key、同意联网和上下文分享，不依赖真实板卡。

## STM32

Windows 安装 Keil MDK（最终材料使用 V5.06 update 6）与 STM32G4xx DFP 2.0.0（工程 PackID 声明）；工程目标 GPIO_PL_Test，设备 STM32G431RBTx。运行根目录 build/stm32/build.ps1 -KeilUv4 <UV4.exe绝对路径>。该脚本在当前 Linux 未实际执行，Keil 生成工具和 DFP 须由部署者提供。
保留原 Core/Src/main.c 字节；当前值为已通过的500。要演示 FAIL→编辑→PASS，用独立测试副本准备已知未达标的基线，并更新审批根路径；不要覆盖黄金源码／证据。

## Zynq 与四接口

参考 board/hardware_setup.md 与 board/wiring.md。配置网口、严格 known_hosts 与非交互 SSH；私钥自行生成保管，不进入仓库。上电后恢复 authorized_keys、准备 PL（冷启动持久化未验收）。
当前部署在初始化阶段完成v5 PL加载，再启动Agent及LED；Agent保持check_only与原四接口执行顺序。现有独立目录`$env:PYTHONPATH = "E:\zhidiao-agent\src"`设置、三步SSH公钥恢复（最后输出ZHIDIAO_SSH_KEY_OK）、v5文件SHA校验与手动加载统一见[初始化参考](../board/zynq/pl_preparation.md)，本仓库目录布局继续使用下方的相对路径设置。
本仓库build/fpga/zhidiao_observe_v5_led.bit先核对SHA fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6。实际PL加载／检查复用已有受审批约束的PLPreparation，步骤见../board/zynq/pl_preparation.md；只支持已确认的/dev/xdevcfg。check_only与prog_done不证明当前运行镜像身份。
OpenOCD0.12.0安装在/sd/tools/openocd/bin/openocd，scripts为/sd/tools/openocd/share/openocd/scripts，使用interface/stlink.cfg与target/stm32g4x.cfg及其依赖。源码／构建步骤见../build/openocd/README.md；原上传ELF未再分发，新ARM产物须重新验收。Linux／BOOT原件存在但完整构建来源与配方仍待整理，含主机私钥的原镜像不公开。../board/zynq/check_files.sh可先做只读文件检查，不代替四接口测试。

在src/agent复制deployment.example.json为deployment.local.json，修改本机绝对路径与SSH路径；私人配置不上传。也可使用deployment-setup预览并经批准新建，向导不会覆盖已有配置。主示例及向导均为v5＋LED；deployment.no-led.example.json或向导--no-led只关闭灯，仍保持相同v5、UART与PL。确认v5已正确加载；不要把配置存在或check_only当作运行镜像已认证。运行 deployment-check --preview-only，再按提示执行实际检查；real-build／real-flash／real-log／real-test 使用现有 CLI --help 的参数，均保留审批。
启动 start_ui.bat，选择配置、工程、Core/Src/main.c、模型与 Key，勾选 UART。批准任务范围与每个 diff，确认每轮 audit 四工具齐全，PASS 来自 PL。导出新的报告，不能重放 data/ 中的历史审批。

报告区分别标注当前运行ID与历史所选ID：轮次表、审计JSON及“下载当前JSON”对应当前运行；历史选择只影响下载所选报告／恢复入口，不切换当前结果展示。资料中的旧截图可能尚无这些标签，按data/screenshots/README.md的说明解读。复现前述实测案例要保留UART启用；PL-only基线截图不等于四接口验收。

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

## 保存新的复现记录

新实验保留代码提交号、git status --short、工具版本、部署配置的非秘密硬件字段、构建日志和新产物SHA。Windows全量在src/agent运行scripts/test_windows.ps1，保存VERIFY_COMMIT、TEST_EXIT、Ran／OK／skip；提交号与未提交改动分别记录。最新Windows由队伍代码同步后补跑，不能提前填写通过。

Keil与Vivado必须在真实工具环境运行现有构建入口，保留完整命令、依赖版本和日志；新产物如与历史黄金SHA不同，重新绑定配置并验收，不覆盖旧证据。板卡实验另保存四工具audit、UART健康、freshness、目标容差及LED独立验收结果。

BOOT／Linux镜像有原件，但完整从零构建步骤仍需补齐；不以“镜像可以启动”替代工具链、源码／DT／rootfs、BOOT打包及冷启动持久化的复现记录。已有材料映射见material_index.md，资源比较见fpga_evidence.md。
