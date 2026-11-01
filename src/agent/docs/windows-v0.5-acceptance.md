# 智调 Windows v0.5 验收

更新：2026-11-01。代码统一使用 main。已有用户 Windows 438 项全量通过反馈，以及最新 LED 28 项、1.943 s、OK 截图；历史 370／412 项与提交号边界保留在验证记录中。

Windows 脚本演示 800→1001 PASS、真实 NiceCode＋模拟硬件 800→1000 PASS，以及两目标／澄清／拒绝审批四场景均有用户反馈。最终run_5d8e…已证明修补后的真实四接口601.7169→1001.08682 ms闭环，第一轮正常UART半行后PL继续。最新Linux结果见根data/test_summary.md；Windows最新整理版本尚待代码同步后重跑，LED独立灯效仍需现场证据。

## 1. 取得 main 最新版本

在 VS Code 的 zhitiaohe 仓库终端执行：

```powershell
git fetch origin
git switch main
git pull --ff-only origin main
```

保留 deployment.local.json 等本机配置。分支切换若被本地未提交改动阻止，先处理提示，不使用强制覆盖。

如果使用 ZIP 下载，请从 main 下载并解压到独立目录，避免混入旧源码。ZIP 中没有 .git；若上级目录碰巧属于另一个 Git 仓库，脚本的提交号可能来自上级仓库，应核对当前目录及实际 Git 根目录。

## 2. 完整离线测试

以下从zhitiaohe仓库根目录进入Agent子目录；已在src/agent时不要重复cd：

```powershell
cd src/agent
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_windows.ps1
```

或直接运行：

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
py -3.13 -B -m unittest discover -s tests -v
```

不需要 API Key、Keil 或板卡。应为 0 failures、0 errors。POSIX shell helper 在 Windows 跳过是正常的；未安装或未找到 Node 时 JavaScript 用例也会跳过。请回传 Ran / OK 或 FAILED 最后几行，以及脚本最后的 VERIFY_COMMIT / TEST_EXIT，确保对应这次验证版本。

Node 只用于可选 JavaScript 回归测试，运行控制台使用浏览器自带引擎，不需要 npm 或 Codex CLI。

以当次输出的Ran／OK／skip和VERIFY_COMMIT为准，不沿用历史测试总数。当前新增部署向导回归覆盖v5＋LED、--no-led仍保留v5／UART，以及预览／拒绝不写配置或连接；这些也应随全量执行。已有Windows438项和LED28项仅为历史结果。使用-p "*uart*.py"运行UART专项，-p test_status_indicator.py运行LED专项，均无需板卡。请同时保存git status --short，避免把未提交代码的结果归到旧提交号。

## 3. PC 窗口与离线演示

运行 start_demo.bat：

1. 浏览器自动打开本机控制台，明确显示模拟硬件。
2. 输入“把 PA1 完整周期调到 1000 ms，误差不超过 50 ms。”，勾选发送同意，点击分析。
3. 确认目标，基线显示 800 ms / FAIL。
4. 查看完整 diff，批准修改并重新验证。
5. 显示 1001 ms / PASS、两轮结果，能下载 JSON 报告。
6. 启动终端 Ctrl+C，等待服务完成清理。

再运行 start_ui.bat，确认原生启动窗口可打开、密钥字段有遮罩、文件选择器可用；未准备硬件配置时可以取消。该步骤不需要发送真实 API 请求。

请用文字回传“离线测试结果、启动窗口是否正常、演示是否 800→1001 PASS”。不要发送 API Key 或私钥。

AI 开发者下一步运行 start_ai_mock.bat，按 [真实 NiceCode＋模拟硬件步骤](ai-mock-quickstart.md) 验证真实模型与 UI。该模式需要 API Key 和联网同意，不需要真实部署。它的 API／Windows 结果与 start_demo.bat 的脚本演示分别记录。

本轮新增检查：如遇联网错误，在“刷新历史”中应能找到含 run_id、task_entry、model_info 和错误码的报告；正常任务沿用同一 ID。无需故意消耗线上请求，错误路径已在离线测试中使用 fake HTTP 覆盖。真实部署还应确认过大的目标在审批与构建前被拒绝；模拟模式保留独立范围。

## 4. 部署 PC 真机验收

Windows 离线通过后，在安装 Keil、保存工程并连接板卡的部署 PC 上，按v0.5手册确认uart_observer并准备v5。新建默认配置启用LED，尚未准备独立灯效验收时使用deployment.no-led.example.json或向导--no-led；它们不会退回旧镜像。

- deployment-check：READY；确认 usleep、monotonic_clock 和 uart_registers。
- real-log：正常 ZHIDIAO_OK 多行；暂停发送时 success=true、logs=[]；正常窗口半行 partial_tail=true、truncated=false；真正触限／传输错误仍停止。
- agent-run：不带 --pl-only，四工具均出现在同一轮 audit。
- 真实 FAIL→AI diff→人工批准→重建烧录→UART＋PL→真实 PASS。
- UI：显示真实标识、当前阶段、原始 diff、两轮测量及报告，日志标注所属轮次。

这部分验收需要板卡，离线测试与模拟界面不能替代。

窗口问题修补后要退出旧 UI／终端并重新启动，新建任务。确认 audit 中 read_target_log 后真正出现 run_hardware_test，再根据 PL 数值核对结果；不要把旧 LOG_INCOMPLETE 报告或模拟 PASS 当作新版真机通过。详情见 [窗口边界修复](uart-window-boundary-2026-10-30.md)。

既有配置未提供status_indicator时LED仍关闭；当前主示例和新建向导默认v5＋LED，可显式选择无灯版本。新增GPIO和灯效按[四灯说明](led-status-indicator.md)独立验收，不把旧v4或prog_done=1当作新GPIO验收证据。
