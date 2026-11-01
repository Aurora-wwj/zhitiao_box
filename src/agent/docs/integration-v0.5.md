# v0.5：UART 正式接入与 PC 控制台

更新：2026-11-01。产品名为“智调”（tiáo），代码统一发布到 main。日常使用以本文替代 v0.4 手册，旧文档保留历史背景。

## 1. 实测证据与本轮边界

当前主证据为最终 run_5d8e004954664f6c8f8ff0f85d31959b：真实两轮四接口均 success=true，完整周期601.7169 ms FAIL，经AI提案、人工批准HAL_Delay(300)→500、重新构建烧录后，PL实测1001.08682 ms PASS。两轮fresh_edges=2；第一轮UART partial_tail=true、truncated=false，随后正常执行PL。完整提案、applied_edit、reviews、audit及events见[公开脱敏JSON](../../../data/final_run_sanitized.json)和[当前验证摘要](validation/final-real-loop-2026-10-30.md)。这不是本次云端新上板。

早期Word与录像对应独立run_92dde302095a45cbb607f6371e524149：601.92511→999.92936 ms，明确--pl-only、uart_observed=false；它证明三接口LLM闭环，不能算完整四接口。原Word和附件已收到，摘要见[首次真实LLM记录](validation/first-real-loop-2026-10-28.md)。两次运行的结果、固件身份与验证范围分别保留，不合并或替换。

最新Linux离线结果见[验证记录](../../../data/test_summary.md)。Windows438项与LED28项是历史结果；代码同步后需重跑Windows并记录提交号。新环境的Keil／Vivado重建、LED独立灯效和冷启动验收分别记录，不能用历史smoke或软件测试替代。

## 2. 升级本地 Profile

保留 allowed_roots、Keil、target、SSH identity_file、known_hosts 等本机值，参考 [完整示例](../deployment.example.json)。在 observer 中采用与最终运行配置相同的 v5：

```json
{
  "bitstream": "/sd/pl/zhidiao_observe_v5_led.bit",
  "bitstream_sha256": "fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6",
  "poll_interval_s": 0.05,
  "timeout_s": 15,
  "transport_margin_s": 3,
  "monotonic_path": "/proc/uptime",
  "prepare_policy": "check_only"
}
```

这是 observer 内部片段，不是完整 JSON。另增加顶层配置：

```json
"uart_observer": {
  "stm32_tx_gpio": "PA2",
  "pl_rx_pin": "M17",
  "baud_rate": 115200,
  "data_bits": 8,
  "parity": "none",
  "stop_bits": 1,
  "rx_addr": "0x43C50000",
  "status_addr": "0x43C50008",
  "control_addr": "0x43C5000C",
  "busybox_path": "/bin/busybox",
  "prog_done_path": "/sys/class/xdevcfg/xdevcfg/device/prog_done",
  "monotonic_path": "/proc/uptime",
  "poll_interval_s": 0.01,
  "transport_margin_s": 3,
  "max_bytes": 1024
}
```

串口字段描述 bitstream 中已有的 115200 8N1，reader 不重配置波特率或接线。PA1→M18 用于周期；UART 来源为 PA2→M17。

prog_done 节点已在当前部署实测为 1。check_only 由部署方准备好正确 v5；prog_done 和文件 SHA 不证明运行镜像身份。显式 load_verified 时，保留受审批的 SHA→/dev/xdevcfg→prog_done 准备，界面展示替换 FPGA 的效果。不修改 BOOT.BIN、image.ub 或启动脚本。

v5 位流已公开在 build/fpga/zhidiao_observe_v5_led.bit；路径相对于仓库根目录。私人 deployment.local.json 不提交Git，也不被向导覆盖。现有部署保留认证及本机路径，仅在审阅后更新硬件字段。新建配置可运行：

```powershell
py -3.13 -B -m zhidiao_agent deployment-setup --project "C:\work\zhitiaohe\src\stm32\gpio_pl_test" --keil "C:\Keil_v5\UV4\UV4.exe" --known-hosts "C:\Users\YOUR_USER\.ssh\known_hosts" --project-file MDK-ARM/GPIO_PL_Test.uvprojx --target GPIO_PL_Test --output deployment.local.json --preview-only
```

先审阅预览，再去掉--preview-only并批准新建；不启用灯时加--no-led。向导默认check_only，不加载PL、不写LED；只有批准后续工作流才会有相应操作。示例中的路径和认证需按本机实际配置，缺identity时使用SSH agent并另行验证。

## 3. UART 采集契约

RealBackend(config) 自动接入 PLPeriodReader 与 PLUARTReader，仍保留可信自定义 reader 注入。原生 UART 绑定同一部署、host、runner 和独立 UART 配置，变更后旧后端拒绝执行。

批准的 capture 顺序：检查工具与 PL → 读走旧 sticky 健康标记 → Control 写 0x2 清 RX FIFO → 记录单调时钟起点 → 一次 SSH 内连续 drain FIFO → 文本与健康元数据。清 FIFO 是真实写操作，审批明确覆盖，内部权限单次有效，不增加第五个工具。

时间戳来自 /proc/uptime，表示 capture 开始到字节／日志被读出的真实单调时间，不冒充硬件线上到达时间。按换行组装文本并去掉 CRLF 的 CR。正常窗口截止的末尾部分行保留并标记 partial_tail=true，truncated=false；非法 UTF-8 替代并计数，不把合法 U+FFFD 当作解码错误。

输出包括 logs、overflow、truncated、partial_tail、capture_end_reason、decoding_errors、frame_errors、parity_errors、bytes_captured、capture_elapsed_ms、fifo_reset、timestamp_basis，以及独立 UART 来源字段。capture_end_reason 为 deadline 或 capture_limit。空窗口返回 success=true、logs=[]。最多 1024 字节，触限仍标记 truncated=true；轮询同时有 monotonic deadline 和有限次数保护。

Controller 对溢出、真正截断、解码／帧／奇偶错误继续采用停止策略；正常 deadline 的半行和空日志不阻止 GPIO 判定。旧 reader 的 truncated=true 也不自动豁免。传输错误继续停止，不让 AI 改源码掩盖硬件访问故障。详见 [窗口边界修复](uart-window-boundary-2026-10-30.md)。

## 4. BusyBox 和预算

小数 sleep 全部改为整数微秒 usleep，例如 0.05 s → 50000 us。PL 默认业务 15 s、PC transport 18 s；UART 默认 capture 5 s、transport 上限 8 s。全局剩余预算不足时缩短 transport 或停止，不扩张总预算。

deployment-check 新增 usleep、单调时钟和 UART status 检查，不读 RX FIFO、不写 Control。READY 也不能代替实际 UART 文本、freshness 或 SWD 验收。

## 5. 正式 real-log 与四接口 Agent

从本仓库 src/agent 目录的 PowerShell：

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
py -3.13 -B -m zhidiao_agent deployment-check --config deployment.local.json --preview-only
py -3.13 -B -m zhidiao_agent real-log --config deployment.local.json --duration-s 5 --preview-only
```

核对来源和 FIFO reset 效果后，去掉预览参数并批准。至少验证正常多行、暂停发送后的空采集、SSH 超时和不完整日志的错误路径。

```powershell
py -3.13 -B -m zhidiao_agent agent-run "把 STM32 PA1 的完整周期调到 1000 ms，误差不超过 50 ms。" --project "E:\Project\GPIO_PL_Test" --source Core/Src/main.c --config deployment.local.json --protocol openai-responses --allow-network --max-attempts 3 --timeout-s 600
```

默认执行四接口，--pl-only 只保留作显式降级。NiceCode 环境变量按 README 配置；整个测试套件不需要在线 API Key。

normal 模式：确认模型发送范围 → 批准精确会话范围 → 基线 build/flash/log/test → AI diff → 人工批准 → 自动 apply/build/flash/log/test。--strict-approval 保留每轮硬件确认。

SessionScope 仅属于可信 UI/CLI，模型不能调用。它绑定受追踪输入 manifest、目标、部署、reader 对象、白名单和限制，只允许把已批准文件的 SHA 更新为预期 after_sha256；其他变化停止。内部 cycle 和子权限仍单次有效，artifact/remote SHA 检查不变。

本轮核查补上原生 PL 目标能力检查：在审批和构建前，周期＋容差上界须同时满足 uint32 计数范围，以及 (窗口－轮询间隔)／(min_new_edges＋1)。默认上界约 4983.333 ms；目标 1000±50 ms 不受影响，60 秒目标会被拒绝。运行预算不足返回 TIMEOUT，不自动延长；模拟模式采用独立虚拟范围。

## 6. PC 端窗口

双击 start_ui.bat，启动窗口选择 profile、工程、源码和模型，密钥输入有遮罩。API Key 仅在当前进程内，不写入配置。之后自动打开 127.0.0.1 的控制台；网页不能选择任意文件路径或命令。

start_demo.bat 无需 Keil、API Key 和板卡，展示模拟 800→1001。它的界面、报告和证据均标为 mock。重启演示可恢复初始 800 ms 临时工程。

AI 开发者使用 start_ai_mock.bat：真实 NiceCode 理解目标并根据模拟反馈提出修改，仍只操作临时 main.c，四工具全部模拟。窗口只配置模型、Key、预算并同意联网；不需要部署 JSON。页面始终标明模拟硬件，报告 evidence_source=mock，并记录 model_info。该模式不会使用固定脚本把答案改成 1001；结果由模型提案和确定性模拟测量决定。完整步骤见 [AI 联调指南](ai-mock-quickstart.md)。

UI 用同一份结构化事件快照展示阶段；第二轮不沿用第一轮的分析完成标记。分析区域使用模型显式理由摘要，不从日志字符串猜状态。完整 diff 用 textContent，控制／bidi 字符可见转义。Before/After 使用测量证据，ERROR 与目标 FAIL 分开。UART 日志标明所属轮次，采集失败明确显示错误，成功空采集独立提示。

默认只监听回环地址，保留 Host、Origin、CSRF、大小和固定字段校验。API Key 不进入网页状态；私钥正文不会读取或发送。关闭浏览器不停止服务，终端 Ctrl+C 会等待本地进程树清理和报告保存。

## 7. 报告与后续

报告记录结构化事件、UART/PL 证据、模型提案、源码／固件 SHA 和授权轨迹。旧报告只提供证据，不恢复旧权限；安全检查点需输入一致、保留已用次数和耗时并重新审批。v0.4 Profile 新增字段后可能不再匹配旧检查点，应开新任务。

现在首次模型调用前就开始持久化 task_entry；API 超时／服务错误、目标解析失败和拒绝目标均保留 run_id，后续执行沿用同一 ID。真实 UI／CLI 与模拟入口统一记录 model_info。task_entry 不是可恢复执行检查点，旧版缺少兼容模型元数据的检查点也可能需要开新任务。归档失败会报错，已有工具证据在返回结果中保留。具体见 [三项修复说明](audit-fixes-2026-10-29.md)。

SSH 中断不能证明远端 OpenOCD 或 FPGA 加载停止。对应 hardware_state_uncertain 需要人工核对。公钥断电恢复、PL 冷启动集成继续列 P2；GPIO 自动初始化和更多协议留待后续扩展。

可选 LED 四灯进度条已实现；deployment.example.json 与 deployment-setup 默认配置 v5＋LED，deployment.no-led.example.json 或向导 --no-led 仍使用相同 v5、UART 与 PL，仅将 status_indicator 置 null。未提供该块的既有配置仍不创建适配器。批准执行后才通过结构化事件写固定 0x43C60000，LED 错误只警告，不影响四接口或 DUT 结果。v5 位流和最终运行配置已收到，但独立灯效实物验收仍待整理，见 [LED 适配器](led-status-indicator.md)。
