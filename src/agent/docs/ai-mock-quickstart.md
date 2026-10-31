# AI 开发者联调：真实 NiceCode＋模拟硬件

更新：2026-10-29。Windows 使用 Python 3.13；代码统一位于 main。

这个模式用于独立开发目标理解、追问、证据分析、diff 审批和 UI，不需要部署电脑或板卡。目标解析和修改建议来自用户配置的 NiceCode API，四个硬件工具全部模拟。临时 main.c 的周期常量驱动模拟测量；不执行 C 编译、Keil、SSH、烧录或真实 PL／UART 访问。

## 1. 取得当前代码

从 GitHub main 下载 ZIP，解压到新目录，用 VS Code 打开。已有 Git 克隆也可以正常拉取 main，保留本机配置，不强制覆盖本地未提交修改。

本次使用 start_ai_mock.bat。三个入口的区别：

| 入口 | 模型 | 硬件 |
| --- | --- | --- |
| start_demo.bat | 固定脚本，完全离线 | 模拟 |
| start_ai_mock.bat | 用户配置的真实 NiceCode API | 模拟 |
| start_ui.bat | 用户配置的真实 NiceCode API | 真实部署 |

## 2. 配置并启动

双击 start_ai_mock.bat，或在仓库根目录 PowerShell 执行：

```powershell
py -3.13 -B scripts\start_ui.py --mock-hardware
```

无需设置 PYTHONPATH，也无需 npm、Codex CLI 或 deployment.local.json。

在新窗口中：

1. 模型先使用此前成功调用的 gpt-5.6-sol，或填写账户当前支持的模型名。
2. 在遮罩输入框粘贴完整 NiceCode API Key。Key 留空时使用当前进程的 NICECODE_API_KEY；不发送到聊天或保存进代码。
3. 总预算先保持 600 秒，包含等待人工确认的时间。
4. 勾选“同意本次使用 NiceCode API（会联网，可能计费）”。
5. 点击“打开 AI 联调控制台”。

使用 https://api.nicecode.ai/v1 和 Responses 协议，可通过当前进程 NICECODE_BASE_URL 调整兼容地址。构造服务和打开窗口不发起模型请求；需要浏览器中再次同意发送上下文并提交目标，才调用 API。单次请求上限 120 秒，受剩余总预算约束，无自动网络重试。

## 3. 完成第一轮模型联调

页面顶部应显示“NiceCode API · 模拟硬件”，源码应位于系统临时目录，只允许修改 main.c。

输入：

```text
把 PA1 的完整周期调到 1000 ms，误差不超过 50 ms。
```

依次操作：

1. 勾选发送同意，点击“分析目标”。
2. 检查模型提取的目标为完整周期 1000 ms、容差 ±50 ms，再批准目标。
3. 模拟基线为 800 ms，显示 FAIL；模型根据这份模拟证据返回修改建议。
4. 审阅完整 diff，确认只修改临时 main.c 中的完整周期常量，再批准。
5. 程序重新模拟 build／flash／log／test。测量进入 950～1050 ms 时由确定性规则判定 PASS。
6. 下载当前 JSON 报告。

真实模型的答案不是固定脚本：它可能改为 1000 ms，也可能给出其他达标值、要求停止或返回无效提案。无效提案会停止；每个新 diff 都需要人工批准，最多三轮工具执行。不要为了得到 PASS 批准明显错误的修改。

## 4. 保存评测结果

首先核对报告：

- evidence_source 为 mock，不能将本次结果记录为真机验收。
- model_info.source 为 nicecode_api，requested_model 为请求中配置的模型名，protocol 为 openai-responses。该名字记录请求配置，不证明第三方实际运行的模型权重。
- 每轮 audit 中依次有 build_firmware、flash_firmware、read_target_log、run_hardware_test。
- 模型提案、批准的源码前后 SHA、测量数值与最终判定一致。

继续测试明确的不同目标，例如完整周期 1500 ms、误差 10 ms；也可以输入“让 PA1 闪慢一点”检查模型是否追问，而不是自行编造完整目标。每次建议重启入口，以便从新的 800 ms 临时工程开始。

记录用户输入、模型名、提取目标、修改理由、diff、轮次、终态和错误码。运行报告默认位于启动目录下 .zhidiao/runs/。源码是临时文件，退出后清理；报告继续保留。历史报告可下载；跨进程重启后的临时工程不是原工程，不能恢复旧授权或旧检查点。

任务在首次模型调用前分配 run_id；目标解析失败也进入历史。report_stage=task_entry 的早期报告只供查看；后续执行会沿用同一 ID，报告中保留 task_entry 及模型信息。磁盘无法归档时会停止继续请求，执行后发生归档故障则保留返回结果中的已有证据。

## 5. 常见结果

| 现象 | 处理 |
| --- | --- |
| 找不到 start_ai_mock.bat | 重新取得 main 最新代码，旧 ZIP 没有该入口 |
| 配置／鉴权错误 | 检查完整 Key、模型名和 NiceCode 账户可用情况；Key 不进入截图 |
| TIMEOUT | 检查服务与网络；重新开始任务，必要时更换账户支持的模型 |
| INVALID_RESPONSE | 模型未按结构化协议回复，保留报告和错误信息用于后续调试 |
| SOURCE／APPROVAL 错误 | 不在审批期间手工改临时文件；重新启动并审阅新任务 |
| API 错误后页面仍显示模拟硬件 | 这是正确行为，API 失败不会切换硬件后端 |

关闭浏览器不结束服务。退出请在启动终端按 Ctrl+C，等待当前有界请求结束、保存报告和清理临时工程。

用户已回传 Windows 真实 NiceCode＋模拟硬件 800→1000 PASS，页面显示请求模型 gpt-5.6-sol；后续反馈 1000／1500 ms、目标澄清和拒绝审批四项均正确。LED 最新 28 项、1.943 s、OK 截图及 438 项全量通过反馈已记录。云端仍使用 fake HTTP，不调用线上服务；当前 UART 窗口修补后 Linux 457 项通过，新增 17 项 Windows／真机另行记录。模拟 UI 不连接真实 LED，其 PASS 也不代替四接口真机验收。
