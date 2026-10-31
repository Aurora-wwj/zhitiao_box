# UART 采集窗口末行与真正截断的区分

更新：2026-10-30。依据用户提供的《错误日志（参考）》和硬件联调说明修复；附件只作证据参考，未执行其中命令，也未将原始日志／本机配置提交到仓库。

## 已核对的实测证据

两次真实四接口尝试均完成 build、flash 和 read_target_log，但 Controller 返回 LOG_INCOMPLETE，audit 中没有 run_hardware_test。这是明确停止，尚无证据表明程序卡死在 PL 访问中。

| UART 记录 | 第一次 | 第二次 |
| --- | --- | --- |
| 完整日志 | 4 条 ZHIDIAO_OK | 4 条 ZHIDIAO_OK |
| 窗口末尾 | Z，4970 ms | ZH，4980 ms |
| bytes_captured | 49 | 50 |
| capture_elapsed_ms | 5000 | 5010 |
| 旧返回 | success=true、truncated=true | success=true、truncated=true |
| 健康状态 | overflow=false，frame/parity/decoding_errors=0 | 同左 |

原生 reader 原先用 limited OR pending 判定 truncated，混淆了真正字节限制与正常窗口的未闭合末行；Controller 的严格停止规则因此阻断了后续 PL。文档中另外一条 FLASH_NOT_VERIFIED 的子工具错误为 CANCELLED，属于人工取消，未作为 UART 根因处理。后面的模拟 PASS 也不视为四接口真机完成。

## 修复后的含义

| 场景 | 返回与行为 | 后续 PL |
| --- | --- | --- |
| 正常 deadline，末行未换行 | 保留原文；partial_tail=true、truncated=false、capture_end_reason=deadline | 健康字段无错时继续 |
| 正常 deadline，完整文本或静默 | partial_tail=false、truncated=false | 继续 |
| max_bytes 或明确采集限制 | truncated=true、capture_end_reason=capture_limit；即使最后一行完整也不豁免 | LOG_INCOMPLETE，停止 |
| overflow／帧／奇偶／UTF-8 解码错误 | 保留所有健康字段；partial_tail 不覆盖错误 | LOG_INCOMPLETE，停止 |
| SSH／transport completion 损坏 | 仍严格校验 envelope、E 结束标记、计数和时间；无完整结束证据则工具失败 | LOG_COLLECTION_FAILED／相应错误，停止 |
| 旧 reader 的 truncated=true | 不凭日志内容、条数或 partial_tail 提示猜测它只是尾行 | 继续保持停止 |

partial_tail 表示未闭合最后一条日志，不证明固件正常；PL 仍独立按数值与容差决定 PASS。采集窗口可能只收到半行，软件仍允许将其作为辅助观测，和成功空采集一样不替代 PL。非法 UTF-8 包括被窗口拆开的不完整码点仍计 decoding_errors，继续采用严格停止策略。

原生 reader 同时区分“读字节时跨过 deadline”和“字节数触限”：前者的读出时间已在窗口外，不计入本窗口，也不伪造 capture_limit。不会等待下一次换行，不延长 5 s 窗口或整轮预算。若 count 已达 max_bytes，即使 completion 漏置 limited 位，也保持 truncated=true。

ObservationBackend 对两个新增字段作类型／枚举校验；capture_limit 必须伴随 truncated=true，partial_tail 必须有实际尾行。旧的日志列表或元数据格式继续可用。可信自定义 reader 如需使用新语义，须自行正确区分尾行和真正丢失，不得直接清除原 truncated 标志。

UI 在最新一轮 UART 文本后标明“采集窗口正常结束，末行未闭合”，不修改原日志；真正截断／健康错误会显示“证据不完整”，并在没有模型分析摘要时明确说明已停止后续 PL，避免误认为仍在等待。AI 上下文保留字段，提示中明确半行自身不等于固件失败。公开四工具签名、contract_version=0.2、审批／SHA／FIFO reset／PL freshness／LED 规则均未改。

## 软件验证

新增 17 项回归：15 项 reader／workflow／元数据／UI 和 2 项实际生成 shell 的 deadline／max_bytes 检查。后两项在 Windows 按 POSIX 条件跳过。

- UART 与窗口联合专项：33 项通过。
- Linux Python 3.13 最终全量：457 tests in 25.571s，OK。
- 覆盖多条完整日志加 Z／ZH、两轮 FAIL→AI diff→人工批准→重建烧录→PASS、触限含完整末行、真正 transport 缺尾、健康错误、旧 truncated 保持停止和尾行提示不跨轮。
- Linux Chromium：真实本地服务／页面、fake Keil／SSH／UART／PL、脚本模型；带 ZH 尾行的两轮 800→1001 PASS，每轮 audit 均含四工具，JavaScript 错误 0。

用户已有 Windows 438 项全量通过反馈，以及最新 LED 28 项、1.943 s、OK 截图。这些是本次 UART 修补前的证据；新增用例和修补后的真机行为需另行记录。云端未调用在线 NiceCode 或真实板卡。

## 部署复测

更新 main 后退出旧 UI／终端进程，重新打开 start_ui.bat，新建一个任务，不把旧终态报告作为已修复的新运行。

1. 先采集真实 UART：若窗口结束为 Z／ZH 等尾行，确认 success=true、partial_tail=true、truncated=false、capture_end_reason=deadline 且健康字段全清。完整／空窗口则 partial_tail=false。
2. 启用 UART 跑完整 Agent，确认本轮 audit 在 read_target_log 后出现 run_hardware_test。基线已经达标时直接 PASS 正常；验收修改闭环需使用已知未达标的测试基线。
3. 核对实际 PL 数值和完整 diff／审批轨迹，导出 JSON 报告。若出现 capture_limit 或健康错误，继续停止并排查，不能将其改成非致命尾行。

LED 继续按独立硬件验收安排启用。本次修复不改镜像、GPIO 方向、SSH 密钥、冷启动文件或工程源码。
