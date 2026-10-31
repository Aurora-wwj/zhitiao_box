# 智调 Windows v0.5 验收

更新：2026-10-30。代码统一使用 main。已有用户 Windows 438 项全量通过反馈，以及最新 LED 28 项、1.943 s、OK 截图；历史 370／412 项与提交号边界保留在验证记录中。

Windows 脚本演示 800→1001 PASS、真实 NiceCode＋模拟硬件 800→1000 PASS，以及两目标／澄清／拒绝审批四场景均有用户反馈。真机新增 UART 窗口半行问题已修补，当前 Linux 为 457 项；新增 17 项 Windows、LED 板卡及修补后的四接口真机整链分别验收。

## 1. 取得 main 最新版本

在 VS Code 的 Agent 仓库终端执行：

```powershell
git fetch origin
git switch main
git pull --ff-only origin main
```

保留 deployment.local.json 等本机配置。分支切换若被本地未提交改动阻止，先处理提示，不使用强制覆盖。

如果使用 ZIP 下载，请从 main 下载并解压到独立目录，避免混入旧源码。ZIP 中没有 .git；若上级目录碰巧属于另一个 Git 仓库，脚本的提交号可能来自上级仓库，应核对当前目录及实际 Git 根目录。

## 2. 完整离线测试

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_windows.ps1
```

或直接运行：

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
py -3.13 -B -m unittest discover -s tests -v
```

不需要 API Key、Keil 或板卡。应为 0 failures、0 errors。POSIX shell helper 在 Windows 跳过是正常的；未安装或未找到 Node 时 JavaScript 用例也会跳过。请回传 Ran / OK 或 FAILED 最后几行，以及脚本最后的 VERIFY_COMMIT / TEST_EXIT，确保对应这次验证版本。

Node 只用于可选 JavaScript 回归测试，运行控制台使用浏览器自带引擎，不需要 npm 或 Codex CLI。

当前预计收集 457 项测试。已有 Windows 438 项全量和 LED 28 项通过记录；本次新增 17 项 UART 窗口回归尚待 Windows，其中 2 项是 POSIX shell 测试，Windows 正常跳过。使用 -p "*uart*.py" 可只运行当前联合 33 项 UART 专项；LED 专项仍为 28 项，均无需真实板卡。

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

Windows 离线通过后，在安装 Keil、保存工程并连接板卡的部署 PC 上，按 v0.5 手册补充 uart_observer 并准备 v4。

- deployment-check：READY；确认 usleep、monotonic_clock 和 uart_registers。
- real-log：正常 ZHIDIAO_OK 多行；暂停发送时 success=true、logs=[]；正常窗口半行 partial_tail=true、truncated=false；真正触限／传输错误仍停止。
- agent-run：不带 --pl-only，四工具均出现在同一轮 audit。
- 真实 FAIL→AI diff→人工批准→重建烧录→UART＋PL→真实 PASS。
- UI：显示真实标识、当前阶段、原始 diff、两轮测量及报告，日志标注所属轮次。

这部分验收需要板卡，离线测试与模拟界面不能替代。

窗口问题修补后要退出旧 UI／终端并重新启动，新建任务。确认 audit 中 read_target_log 后真正出现 run_hardware_test，再根据 PL 数值核对结果；不要把旧 LOG_INCOMPLETE 报告或模拟 PASS 当作新版真机通过。详情见 [窗口边界修复](uart-window-boundary-2026-10-30.md)。

可选 LED 默认关闭。新增镜像／GPIO 由硬件方独立确认后再按 [四灯说明](led-status-indicator.md) 启用，不把旧 v4 或 prog_done=1 当作新增 GPIO 的验收证据。
