# 智调 Agent 项目进度与后续工作计划

更新日期：2026 年 10 月 30 日，v0.5 UART／PC 控制台。名称“智调”的“调”读 tiáo。

仓库：https://github.com/Aurora-wwj/zhidiao-agent

代码统一发布到 main，临时验证分支移除。已有仓库名、Python 包名和配置路径保持兼容。日期命名的旧进度文件保留历史快照，当前以本文及同名 PDF 为准。

## 1. 当前结论

首次真实 NiceCode LLM 闭环已由用户完成并提供 Word 与录像：PA1 完整周期 601.92511 ms，目标 1000±50 ms；AI 正确识别 HAL_Delay(300) 为单次翻转间隔，提出改为 500；人工批准后重新编译烧录，实测 999.92936 ms，第二轮 PASS。

首次真实闭环明确使用 PL-only。UART 已由硬件队友通过注入 reader 独立验收，包含正常文本与成功空采集；软件将该能力收编为 PLUARTReader，并补充完整四接口 workflow、语义审批和 PC 控制台。最新真机日志进一步证明原生 reader 已捕获真实文本，但正常窗口尾行被旧 truncated 逻辑误判，四接口整链因此停止，尚未完成实机验收。

新版四接口因果 mock 闭环与浏览器流程已通过。用户反馈 Windows 438 项全量通过，最新 LED 28 项、1.943 s、OK，真实 NiceCode＋模拟硬件四场景也正确。本次根据真实 LOG_INCOMPLETE 日志区分 deadline 的 partial_tail 和真正截断，并修正读字节跨 deadline 的误标；新增 17 项回归后 Linux 457 项通过。带尾行的浏览器两轮四接口也通过。本次 Windows、修补后真机与 LED 地址／bitstream 仍分别验收，冷启动继续为 P2。

## 2. 已有真实证据

| 能力 | 证据 | 范围 |
| --- | --- | --- |
| build_firmware | Keil rebuild，0 Error(s)、新 HEX | v0.5 材料报告重新实测 |
| flash_firmware | 两端 SHA 一致、program/verify/reset | 真实 OpenOCD/ST-Link/STM32 |
| run_hardware_test | 真实 FAIL/PASS，断线后 freshness timeout | PA1→M18，正式 period reader |
| read_target_log | 注入 reader 已验证多行与空采集；原生 reader 实测四条完整＋Z／ZH 尾行 | 新日志揭示正常尾行误判；修补后待回归 |
| 真实 Agent | 601.92511→AI diff→999.92936 PASS | 两轮，原实测未包含 UART |
| Windows 基线 | 用户 323 项：311 通过、12 跳过 | 旧版；部署 PC 可另有 Node 缺失跳过 |
| Windows v0.5 | 最新 LED 28 项、1.943 s、OK 截图；438 项全量通过反馈；脚本 UI 800→1001 PASS | 新增 17 项 UART 回归待 Windows；不推测全量跳过数或提交号 |
| 原生四接口真机尝试 | build／flash／UART 成功；两次 LOG_INCOMPLETE，未进入 PL | 49／50 字节、健康标记全清，软件误判已复现并修补；非整链 PASS |
| Windows API 联调 | NiceCode＋模拟硬件 800→1000 PASS；后续反馈 1000／1500、澄清、拒绝审批四项正确 | 用户手工反馈；不是四接口真机验收 |
| v4 镜像 | runtime load 与 prog_done=1 | 冷启动自动恢复未验收 |
| SSH key | 当前系统非交互可用；reboot 后曾丢失 | 持久化／自动恢复待后续 |

## 3. 本轮已实现的软件

| 模块 | 实现 | 验收边界 |
| --- | --- | --- |
| UARTObserverConfig | PA2→M17、115200 8N1、独立寄存器和超时配置 | 与 PA1 周期身份分离 |
| PLUARTReader | 一次 SSH、清旧 FIFO、连续 drain、CRLF／UTF-8 文本、单调时钟 | 原生采集已见实测；窗口边界修补待真机回归 |
| UART 健康信息 | overflow、truncated、decoding/frame/parity errors、字节数 | 真正不完整日志停止，正常末行单独标注 |
| UART 窗口修补 | partial_tail、capture_end_reason；deadline 半行保留并允许后续 PL | 触限、transport 损坏和健康错误仍停止；17 项新增回归 |
| 原生自动接入 | RealBackend(config) 同时连接 period/UART reader | 配置／reader／runner 身份不符即拒绝 |
| FIFO reset 授权 | 预览明示 Control=0x2，内部单次 capture 权限 | 独立 real-log 或批准会话／轮次覆盖 |
| BusyBox 兼容 | 整数微秒 usleep，monotonic deadline 与有限轮询 | 不依赖 fractional sleep |
| timeout margin | PL 业务 15 s、PC 18 s；UART capture 5 s、PC 8 s | 不超出全局剩余预算 |
| 完整四接口 workflow | 默认 build/flash/log/test；因果 mock FAIL→edit→PASS | 默认不再需要 --pl-only |
| semantic approval | 会话范围＋每个 diff；批准修改后自动重新验证 | manifest／配置／目标／对象／限制严格绑定 |
| strict approval | 每轮硬件操作确认保留 | CLI 与启动器可选 |
| 结构化事件 | 构建、烧录、观测、分析、应用、终态进入报告与 UI；隔离可选订阅者 | LED 直接消费 tool_name／attempt／TOOL_FINISHED |
| 可选四灯进度 | 固定 0x43C60000 四位值；逐工具闪烁／成功常亮／错误双闪；新轮清空 | 默认 null；当前 28 项专项通过，LED 镜像与寄存器待真机 |
| LED 故障隔离 | 独立限时 transport、单次 warning 后停用；UI 阶段与判定不受影响 | 配置随 SessionScope 绑定；不增加公开工具或修改 FPGA |
| LED 启动异常修补 | Thread 创建／启动失败后丢弃无效对象，后续关闭和 CLI PASS 不受影响 | 新增 2 项故障注入回归，详细过程见 audit-led-2026-10-29.md |
| PC 启动窗口 | Tkinter 选择部署／工程／源码，遮罩 Key，自动打开本地控制台 | Key 不保存，网页不能任意选择路径 |
| PC 控制台 | 自然语言、阶段、分析摘要、完整 diff、Before/After、报告 | JSON／底层配置折叠 |
| AI 联调模式 | start_ai_mock.bat，真实 NiceCode＋模拟硬件，仅编辑临时 main.c | 用户已反馈四场景正确，不连接真实 LED |
| 模型与硬件来源 | 真实 UI、CLI 和模拟模式统一 model_info，记录请求模型／协议 | 不导出认证数据，不声称模型权重认证 |
| 真实目标能力校验 | 在审批和构建前检查计数范围、容差带、窗口与新边沿要求 | 默认周期＋容差上界约 4983.333 ms；不自动扩大窗口 |
| 任务进入审计 | 首次模型请求前分配 run_id，失败也归档，执行沿用同一 ID | task_entry 只供查看，不能恢复权限；归档失败显式报错 |
| UI 证据显示 | UART 日志标明轮次；正常半行加注释，真正截断／健康错误明确不完整 | 原日志不变，ERROR 与目标 FAIL 分开 |
| UI 本轮修复 | 分析完成标记限定当前轮次，采集失败明确提示，同次轮询共用事件快照 | 新增 5 项回归通过 |
| 一键运行 | start_ui.bat、start_demo.bat、start_ai_mock.bat 和源码入口 | 无手工 PYTHONPATH 要求 |
| 部署向导／诊断 | 新配置采用 v4＋UART；检查 usleep／单调时钟／UART status | 不清 FIFO，不写启动文件 |

四个公共工具签名和 contract_version=0.2 保持稳定。模型只给出 edit/stop 提案；PASS 仍按真实周期误差与容差计算。

## 4. 安全与审批

会话预览绑定受追踪工程输入摘要、目标、部署、原生 reader 对象、源码白名单、尝试次数和预算。SessionScope 只在可信 UI/CLI 内，在人工范围批准后派生单次 cycle 权限。新的源码 diff 必须人工批准；应用后只允许预期文件 SHA 改变，其他输入变化会停止。

artifact 路径、artifact SHA、远端 SHA、target、before/after SHA 和单次消耗约束保留。没有模型自批准、任意 shell、Git commit/push 或第五个硬件工具入口。strict 模式仍可逐轮确认。

页面继续使用回环监听、Host／Origin／CSRF、固定字段、大小限制、CSP nonce 和 textContent；控制／bidi 字符可见转义，不改变审批 payload。API Key 不进入页面状态。FIFO 清空和可选 FPGA 重载效果在审批中明确显示。

服务退出会取消本地进程树、等后台清理并保存已有运行报告；保留已完成 PASS/FAIL。终止本地 SSH 不证明远端 OpenOCD 或 FPGA 加载停止，相应中断继续记录 hardware_state_uncertain。强制结束进程／断电无法保证最终报告写入。

## 5. 当前部署事实

| 项目 | 值 |
| --- | --- |
| STM32 工程 | E:\Project\GPIO_PL_Test |
| Keil / Target | D:\Keil_v5\UV4\UV4.exe / GPIO_PL_Test |
| Zynq | root@192.168.10.2:22；HOME=/home/root |
| period / high | 0x43C30000 / 0x43C30008 |
| edge / valid | 0x43C40000 / 0x43C40008 |
| UART RX / status / control | 0x43C50000 / 0x43C50008 / 0x43C5000C |
| 周期与 UART 接线 | PA1→M18；PA2/USART2_TX→M17 |
| v4 镜像 | /sd/pl/zhidiao_observe_v4.bit |
| v4 SHA-256 | 8b224710de8b547198eeffe83ee2abd8a44cc6d2d18555af93a706ec4cfc56ab |
| prog_done | /sys/class/xdevcfg/xdevcfg/device/prog_done，当前部署已实测 |

check_only 由部署方预先加载正确镜像。prog_done 与 SD 文件 SHA 不提供运行镜像身份认证。显式 load_verified 会在授权内校验并加载已选镜像；不改 BOOT.BIN、image.ub、网卡或启动脚本。

## 6. 软件验证

本轮 Linux Python 3.13 离线 457 项全部通过，详细记录见 validation/v0.5-software-checks.md。原有 440 项加 17 项 UART 窗口回归，联合 UART 专项 33 项通过；覆盖真实日志对应的 Z／ZH 尾行、触限／健康错误保持停止、传输 completion 缺失、旧 reader 兼容、UI 提示、两轮四接口，以及实际生成 shell 的跨 deadline 和 max_bytes 边界。此前模型、审计、审批、LED 等回归继续通过。云端未调用在线 NiceCode 或板卡。

Linux Chromium 实际操作通过：输入目标→确认→模拟 800 ms FAIL→查看原始 diff→批准→模拟 1001 ms PASS，未发现 JavaScript 错误。演示使用临时源码和脚本模型，不调用 NiceCode、不连接板卡。

API 联调模式也完成 Linux Chromium 浏览器验证：原生客户端配合 fake HTTP 提取 1500 ms 目标，模拟 800 FAIL→API 提案→人工审批→1500 PASS；无 JavaScript 错误，错误后硬件标识仍为模拟。fake HTTP 不作为真实在线模型验收。

用户已回传 Windows 412 项、26.244 s、OK（skipped=15），后续再提供 LED 26 项、1.688 s、OK 截图，并文字反馈 438 项全量通过；真实 API＋模拟硬件四场景均正确。438 项反馈未附耗时／跳过数量／提交号，不补写推测值。代码继续直接更新 main。

随后用户补验 LED 28 项、1.943 s、OK，已覆盖那 2 项线程启动异常用例。新增 UART 17 项尚待 Windows，其中 2 项 POSIX shell 用例正常跳过。Linux Chromium 新增带 ZH 尾行的原生流程测试，fake Keil／SSH／UART／PL＋脚本模型：两轮 800→diff 审批→1001 PASS，每轮四工具齐全，JavaScript 错误 0。这是软件验证，修补后的真机需重新运行并保留新报告。

## 7. 下一步与优先级

| 优先级 | 工作 | 完成标准 |
| --- | --- | --- |
| 已完成反馈 | Windows／AI 侧基线验收 | 最新 LED 28 项截图 OK、438 项全量通过反馈；AI 四场景正确 |
| 待补记录 | UART 窗口修补 Windows 回归 | 当前总计 457 项；UART 联合 33 项无需板卡，含 2 项新增 POSIX skip |
| P0 | 正式 real-log 修补后复测 | 窗口半行 partial_tail=true、truncated=false；真正触限／错误继续停止 |
| P0 | 四接口真实 LLM 闭环 | 无 --pl-only；两轮均有 build/flash/log/test；真 FAIL→AI diff→真 PASS |
| P1 | PC UI 真机展示 | 阶段、理由、diff、UART 轮次、Before/After 与报告一致 |
| P1 | 可选 LED 板卡验收 | 先独立确认新增地址与输出方向，再检查四工具进度、测量 FAIL 保持、重置与错误双闪 |
| P2 | SSH 公钥持久化 | 断电后恢复 /home/root/.ssh/authorized_keys 并免密可用 |
| P2 | PL 冷启动恢复 | 选择启动镜像集成或受审批 runtime 准备并冷启动验证 |
| 后续 | GPIO 自动初始化、更多协议／安装包 | 独立契约和实测；不阻塞本版主线 |

## 8. 当前使用方式

Windows AI 开发电脑先运行 scripts/test_windows.ps1，再双击 start_ai_mock.bat：填写模型与 Key、同意联网，在页面同意发送上下文，输入完整周期及容差，核对并批准目标和 diff，下载报告。初始模拟周期为 800 ms，后续值由模型修改决定，不固定为 1001。步骤见 ai-mock-quickstart.md。

start_demo.bat 继续提供完全离线脚本演示。部署 PC 补入独立 uart_observer 和 v4 后，先验收正式 real-log，再运行默认四接口 agent-run 或 start_ui.bat。

任务范围批准后进行基线；每个新 diff 均人工审批。报告默认 .zhidiao/runs/，任务 ID 在模型调用前分配，早期错误也可查。可选 LED 默认关闭；新增 GPIO／镜像独立验收后才按 led-status-indicator.md 启用，旧 v4 SHA 或 prog_done=1 不证明 LED 可用。详情见 integration-v0.5.md、v0.5-checklist.md、audit-fixes-2026-10-29.md 与首次真机证据摘要。

## 9. 仍有的限制

输入摘要覆盖受支持的工程内 C/Keil/链接与脚本配置，不能替代外部依赖锁定或操作系统隔离。现有白名单 UTF-8 文件一次只修改一份，单文件 128 KiB、上下文最多 8 文件合计 256 KiB。UART 原生采集最多 1024 字节，正常半行标 partial_tail，触限标 truncated；解码和硬件错误仍停止。时间戳是板端读出时间，不是硬件线上到达时间。自定义回调仍须遵守 I/O 截止时间，旧 truncated=true 不自动豁免；关闭不会强行杀死 Python 线程。

当前控制台使用本机浏览器窗口与标准库启动窗口，不提供远程多用户服务。模拟模式只读取临时源码中的完整周期整数常量，不验证 C 编译、真实 MCU 时序或半周期实现。临时工程退出清理，报告保留，重启后不恢复旧工程权限。新模式单次 API 上限 120 秒，停止需等待当前有界请求结束。

真实 UART 独立接口、原生 reader 的文本捕获和顶层三工具闭环已有证据，Windows 脚本 UI、438 项单测、LED 28 项与真实 API 四场景已有反馈。四工具真机整链在旧正常尾行误判处停止，修补后的整链、本次 Windows／LED 板卡与冷启动分别验收。LED 四灯表示工具成功而非 DUT 通过，PL-only 的 UART 灯保持灭；PC 经 SSH 驱动的闪烁受延迟影响，进程关闭后不保证错误双闪持续。SD 日志归档／清理未实现，报告保存在 PC。
