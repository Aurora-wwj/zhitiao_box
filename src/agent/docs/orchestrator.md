# Orchestrator、人工审批和真实反馈循环

更新日期：2026-10-28。部署命令及参数见 [v0.5 手册](integration-v0.5.md)。下文保留核心逐 cycle 授权接口；用户层默认语义审批的区别如下。

## v0.5 用户层与核心边界

核心 Orchestrator 仍不会自己批准真实 cycle。normal CLI/PC UI 在人工确认 SessionScope 后，核对受追踪输入 manifest、目标、部署、reader、白名单、采集时长和限制，派生精确单次 cycle 权限；每个新 source diff 仍需人工批准。--strict-approval 保留逐轮确认。两者使用同一 Controller/RealBackend，模型没有审批入口。

UART 通过独立 UARTObserverConfig 和 PLUARTReader 正式接入；RX FIFO reset 是审批明示的内部效果，结果不再附带 PA1。结构化 events 供 UI/报告及未来适配器使用；reviews 保留会话／cycle／完整 diff 和决定结果，属于证据而非持久化权限。恢复通过 parent_run_id 关联旧报告，不恢复旧授权。

## 1. 分层与最终判定

用户自然语言目标 → GoalInterpreter → 人工确认目标 → Agent/Orchestrator → ReviewedController → 四个硬件工具 → 实测证据 → Agent 分析及源码 proposal → 人工审阅 diff → 下一轮。

| 层 | 职责 |
| --- | --- |
| GoalInterpreter | 绑定部署所观测的 PA1，严格提取完整周期和容差；错误引脚拒绝，缺信息连续澄清 |
| Agent.decide | 根据源码和本轮证据提出 edit 或 stop；没有执行、授权或 PASS 操作 |
| Orchestrator | 单轮推进、证据与决策、审批、次数/预算、检查点报告及安全恢复 |
| ReviewedController | 真实整轮预览和单次授权；固定 build → flash/verify → 已选 UART → PL 顺序 |
| RealBackend | Keil、SSH/SCP、远端 SHA-256、OpenOCD、观测适配，不向模型开放底层命令 |
| SourceEditor | 显式白名单、before/after SHA-256、完整 diff、一次审批一个文件、原子替换 |
| ObservationBackend | 日志/物理测量的格式校验与确定性 GPIO 判定 |
| WebUIService | 本机浏览器的目标、澄清、按钮审批、历史和报告下载 |
| RunStore | 原子持久化审计；恢复校验，不恢复旧授权 |

GPIO 判定为 `abs(period_ms - expected_period_ms) <= tolerance_ms`。LLM 可以解释约 601 ms 与 1000±50 ms 的差距并提出修改，不能决定“这个数值算通过”。工具的 success、烧录 verified、物理测试 passed 保持分离。

## 2. 立即运行模拟循环

在 Windows PowerShell 仓库根目录：

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
py -3.13 -B -m zhidiao_agent agent-demo
```

演示创建临时 main.c，模拟构建捕获初始周期 800，模拟烧录部署捕获值，模拟测量不满足 1000±50。脚本模型建议改为 1001，界面展示理由和 diff；人工批准后才修改，再次模拟构建/部署后测量通过。

该模式的 model_mode=scripted_mock、evidence_source=mock。没有真正模型推理、Keil 编译、UART 或 FPGA 实测；修改的是演示临时文件，不是已有 STM32 工程。进程退出删除临时工程。

要让 NiceCode 做真实决策而工具仍为模拟，在同一终端配置 API 环境变量后运行：

```powershell
py -3.13 -B -m zhidiao_agent agent-demo --protocol openai-responses --allow-network
```

这会发送临时源码和模拟证据，可能计费，evidence_source 仍是 mock。模型可以提出其他有效数值或停止，不保证固定输出 1001。

## 3. 真实用户入口

```powershell
py -3.13 -B -m zhidiao_agent agent-run "把 PA1 完整周期调到 1000 ms，误差不超过 50 ms。" --project "E:\Project\GPIO_PL_Test" --source Core/Src/main.c --config deployment.local.json --protocol openai-responses --allow-network --pl-only --max-attempts 3 --timeout-s 300
```

该命令会访问真实工程、调用真实模型并在批准后操作真实硬件。必须先完成 Deployment Profile 和 [单接口联调](integration-v0.4.md)。`--source` 相对于所选工程，按实际目录填写；可重复选择文件。

程序先核对本地输入并展示将发送的源码范围，请用户同意网络发送，再解析目标并请用户确认完整周期和容差。源码、当轮日志、工具证据会提供给配置的模型服务；不是自动上传整个仓库。密钥不输出、不写入项目。

部署中 `observer.observed_gpio` 标识实际接线，当前为 PA1。明确要求 PB3 等其他引脚时，在模型请求前拒绝；模型 ready JSON 必须返回一致的 observed_gpio，审批也显示引脚。修改接线后应更新可信配置并重新验收。

如果自然语言缺少明确目标或误差，界面允许继续回答澄清问题，最多补充三轮，不会由模型悄悄设定目标。当前只支持单个已接线 GPIO 的完整周期；PWM、占空比及其他用户目标需扩展严格契约，不能直接解释成任意命令。

第一轮取得当前代码的基线证据。测量失败或编译失败后，Agent 消费当轮结果并提出一个源码修改；人工审阅并批准后写入，然后批准新一轮真实构建和部署。新的尝试消费已修改源码，而不是重复烧录同一失败 artifact。

## 4. 人工审批交互与绑定

终端人工入口使用以下交互；浏览器界面提供对应的批准、取消和完整 diff 按钮：

- 展示修改理由、源码 diff，或本轮工程、目标和构建/烧录/观测计划。
- 输入“批准”、`approve`、`y`、`yes` 批准；前后空白被去除，英文不区分大小写。
- 输入 `diff`、`d`、“查看差异”可再次展示预览；其他输入取消。
- 内部保存并校验完整 proposal_id / fingerprint，用户无需手抄 64 位摘要。

源码编辑和真实执行轮次分开审批。批准源码不代表自动授权部署；每轮真实操作均有预览和独立授权。没有 --yes，没有非交互自动批准；stdin 重定向不能替代人工决定。

审批约束保持：action、精确参数、源码摘要、diff 与 payload 必须对应；一次使用后失效。执行计划绑定工程、全部受追踪输入的 source_digest、Deployment Profile、目标与观测选择。构建产物必须来自本轮批准的工程，再校验上传前后的 artifact 摘要。

模型没有 approve 方法，不能提交“已批准”JSON 绕过 gate。`ApprovalGate.decide`、`review_edit` 和 `review_execution` 只供可信的人机界面调用，不应注册为模型工具。这是进程内授权边界，不是操作系统安全沙箱或多用户身份认证系统。

## 5. 状态与 Python 接口

`Orchestrator(controller, agent, editor, task=..., project_path=..., params=..., include_uart=..., timeout_s=..., report_store=..., recovery_report=...)` 组合上下层。真实执行必须使用 ReviewedController；普通 Controller.run 继续阻止需要审批的真实后端。不要把 RealBackend.requires_approval 改成 false。

| 状态 | 行为 |
| --- | --- |
| READY | 可准备下一轮预览，或在真实轮次授权仍有效时执行 |
| AWAITING_EXECUTION_APPROVAL | 展示真实轮次计划，等待人工决定；重复 advance 不执行工具 |
| AWAITING_APPROVAL | 展示待改源码 diff；重复 advance 不执行工具或请求新模型 |
| PASS | 已选的确定性物理标准通过，终止 |
| FAIL | 次数耗尽或工具链失败，终止 |
| STOPPED | 用户/模型停止、过期审批、输入变化、超时或其他保护条件，终止 |

- `advance()` 最多推进一轮。待审预览未批准前不会开始工具，也不会反复请求模型。
- `review_execution(proposal_id, fingerprint, approved=...)` 审阅本轮真实计划；批准只授权，随后 advance 才执行。
- `review_edit(proposal_id, fingerprint, approved=...)` 审阅并应用绑定的源码修改；应用后仍需下一轮执行预览。
- `cancel()` 取消并停止。终态再次 advance 不重新运行工具。
- `report()` 返回与 run_id 关联的轮次、工具证据、模型决策、已应用编辑和当前待审计划。

Controller.max_attempts 仅允许 1–3，包含第一轮基线。用户流程总预算从初始预检和目标解析开始，包含澄清及等待人工审批；恢复时也计算已经消耗的预算和检查点后的停机时间。开始下一阶段前检查剩余时间并向受控硬件操作及原生 NiceCode 决策请求传递预算。自定义模型或 reader 回调还须遵守自己的 I/O 截止时间；程序不会用 Python 线程强杀任意阻塞回调。模型请求期间按 Ctrl+C 会返回结构化 CANCELLED 并停止。

编译失败或物理数值不达标可进入 AI 修复；烧录校验、SSH、UART 或测量工具失败则停止，不通过修改 C 代码掩盖设备链路故障。拒绝、过期或源码变化后的旧批准不授权写入或下一工具。

## 6. UART 未完成时的处理

默认真实流程要求 UART。没有 reader 时明确返回不可用并停止。命令行显式 `--pl-only` 对应 include_uart=False：跳过 UART 并保留审计标记，PASS 仅覆盖 PL gpio_period，不表示 UART 或完整四接口已验收。

不能把“没有 reader”当作“成功采集到空日志”。真实 reader 成功运行但没有字节时才可以 success=true、logs=[]。采集工具成功也不等于固件行为正确，例如收到 FW_ERROR 依然可能是成功的日志采集。

依赖注入保持：

```python
from zhidiao_agent.observations import ObservationBackend
from zhidiao_agent.tools.real_backend import RealBackend

observations = ObservationBackend(
    uart_reader=real_uart_reader,
    period_reader=real_period_reader,
)
backend = RealBackend(config, observations=observations)
```

基础回调契约：

```python
uart_reader(duration_s, timeout_s) -> [
    {"timestamp_ms": 0, "text": "FW_BOOT_OK"}
]
period_reader(timeout_s) -> {"period_ms": 1001.0}
```

v0.5 已按硬件定义接入 PLUARTReader，仍兼容可信 reader 返回列表或 `{"logs": [...], "overflow": false, "truncated": false, "decoding_errors": 0}`。正常窗口截止的未闭合末行用 partial_tail=true、capture_end_reason=deadline 表示，不设置 truncated。真正触限、溢出或解码／帧／奇偶错误继续以 LOG_INCOMPLETE 停止；旧 truncated=true 不自动豁免。详见 [当前 UART 契约](integration-v0.5.md) 与 [窗口边界修复](uart-window-boundary-2026-10-30.md)。

PL reader 已有正式实现；observer 配置存在时可自动接入 RealBackend。Freshness 要求 valid=1、至少两个新边沿及稳定计数检查，并保留相关测量元数据供审计。PL 参数来源于部署配置，模型不会生成 devmem 地址。

## 7. 源码修改约束

只编辑工程中显式允许的现有 C/C++、头文件、汇编文件。拒绝绝对路径、盘符、反斜线、父路径穿越、符号链接和 Git/Agent 元数据。不自动创建或删除文件，不自动改 Git 配置、提交或推送。

一次 proposal 替换一个完整 UTF-8 文件，最大 128 KiB；模型源码上下文最多 8 个文件、合计 256 KiB。before_sha256 必须匹配模型读取时的实际字节；审批前或写入准备期间文件变化均拒绝覆盖。采用同目录临时文件与原子替换，保留源文件模式。

该机制不能判断任意已批准 C 代码是否正确，也不能防止外部程序同时修改工程。复杂 Keil 外部依赖、GBK 和多文件事务仍需后续设计。`.zhidiao` 是报告等生成元数据的保留目录，不允许 SourceEditor 编辑，也不计入工程源码摘要。

## 8. 后端身份与受控 PL 准备

一个 RealBackend 绑定初始 DeploymentConfig。替换 host、认证或 observer 后，旧实例立即拒绝预览与执行；原生 PLPeriodReader 的配置与 transport 也必须匹配，避免“烧录到新板，却读取旧板”误判。需要切换板卡时新建 backend 和审批，不静默替换正在使用的 reader。

默认 `check_only` 读取已准备的 PL。`load_verified` 需要在可信 profile 指定 SD .bit 路径和 SHA-256，预览明确显示加载效果；批准后内部准备步骤校验 SHA、加载 `/dev/xdevcfg` 并检查 prog_done。它属于现有硬件观测的内部准备，每个批准轮次执行一次，在 UART/PL 两次观测之间保持同一配置，不增加第五个公开工具。

没有人工批准的观测计划时不能加载 FPGA。控制器只能在已批准整轮内派生本次准备授权；模型不能授权加载或更换 bitstream。加载镜像、板端 BusyBox 选项与 prog_done 路径仍需实机回归。

## 9. 浏览器人机界面

```powershell
py -3.13 -B -m zhidiao_agent serve --project "E:\Project\GPIO_PL_Test" --source Core/Src/main.c --config deployment.local.json --protocol openai-responses --allow-network --pl-only --port 8765
```

在本机打开 `http://127.0.0.1:8765`。界面展示固定工程、源码白名单、PA1 目标和发送同意选项；输入任务后可补充澄清，再批准目标。本轮验证和源码 diff 各自通过按钮审批；界面显示理由、实际测量、运行历史和 JSON 下载。

只允许一个后台操作推进。网页取消会停止本地命令进程树并阻止后续步骤；原生模型请求按其 I/O timeout 返回。停止信号在发布工作线程前初始化，线程内部不能清掉并发的取消。终端 Ctrl+C 关闭服务时拒绝新任务，等待非 daemon 工作线程结束、已有运行的最终报告保存完成；保存错误向调用方返回。关闭不改变已完成 PASS/FAIL 的证据。

终止本地 SSH 不能证明远端 OpenOCD 或 FPGA 加载已结束，报告仍保留相应 hardware_state_uncertain 标记。自定义回调需遵守截止时间，关闭不会强行杀死 Python 线程。关闭浏览器窗口不会终止服务，请使用界面停止或终端 Ctrl+C。服务只绑定回环地址，POST 校验 Host、Origin、CSRF 和大小限制；不接收网页指定的任意本地工程路径。它面向当前电脑的可信用户，不提供远程多用户身份认证。

## 10. 持久化报告与恢复

`RunStore(root)` 将每个 run_id 保存为 `run_<32位hex>.json`，默认目录为当前工作目录 `.zhidiao/runs`。保存采用同目录临时文件和原子替换，并请求受限文件模式；最大 4 MiB，拒绝符号链接目标、非法 JSON 和非有限数值。报告过滤凭据字段与常见 token 模式，仍应按本地工程资料管理。

POSIX 文件请求 0600 模式；Windows 的实际访问权限由目录 ACL 决定。发生可能留下远端烧录或 FPGA 加载进程的中断时，hardware_state_uncertain=true；本地调用返回不代表远端动作已终止。

Orchestrator 在执行工具或应用编辑前先记录 in_flight 意图，并在 advance、review 和 cancel 后保存检查点。报告包含 task、goal、observed_gpio、工程/部署、源码摘要、工具结果、模型决策、审批预览和状态。保存失败时停止，避免缺失审计记录后继续下一工具。报告目录位于工程内时只能使用 `.zhidiao` 子树，避免报告改变受审批的源码摘要。

```powershell
py -3.13 -B -m zhidiao_agent report ".zhidiao/runs/run_EXAMPLE.json"
```

实际使用时替换占位文件名。`agent-run` 可加 `--report-dir <目录>` 或 `--resume-report <报告路径>`。恢复先核对相同 task/goal、部署、源码白名单、源码摘要、次数和时间限制；保留已经用掉的次数及耗时，创建新 run_id 并关联 parent_run_id。

恢复永不重建 ApprovalGate 的已批准状态。待执行轮次重新预览、重新审批；待编辑内容重新生成 proposal_id/fingerprint，请人工再审。标记为执行中的检查点拒绝继续，先检查硬件再开始新的已审阅运行。PASS/FAIL/STOPPED 报告可重新查看，不会触发额外执行。更换目标、任务、源码或配置时应开启新 run。命令行省略 task 且提供 --resume-report 时复用原报告任务；显式改成其他任务不允许恢复。浏览器也可查看历史并申请恢复允许的检查点。

## 11. 验证与未完成项

单元测试使用 mock 模型、传输与命令 runner，覆盖 freshness、回绕、零周期、畸形 SSH 输出、审批绑定/拒绝/重放、源码变化、工具失败、次数/时间限制及完整模拟循环。产品的语义权限由人工范围批准派生，不提供绕过 diff 审批的开关。

硬件队友 v0.4 的证据确认三接口及非交互 SSH 的真实可行性；本次新正式封装和真实 Agent 需要部署 PC 回归，不能将云端测试通过等同于新的硬件 FAIL→AI 修改→PASS 已验收。

v0.5 材料已证明 PL-only 真机 601.92511→AI 修改 HAL_Delay→999.92936 PASS，以及 UART 注入 reader 的独立实测。本轮正式 UART reader、四接口语义会话和新控制台已完成软件实现；新版 Windows／四接口真机结果按当前进度表继续验收。

SSH 公钥断电持久化与 PL 冷启动自动加载属于低优先级后续增强。当前使用已准备的运行环境即可联调；后续选择启动镜像或受审批的运行时加载方案时，再安排部署和冷启动验收。
