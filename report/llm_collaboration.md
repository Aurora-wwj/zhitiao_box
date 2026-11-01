# LLM协作与证据索引

## 当前主案例：完整两轮四接口

主证据为run_5d8e004954664f6c8f8ff0f85d31959b，公开脱敏版在[data/final_run_sanitized.json](../data/final_run_sanitized.json)。原Agent存档与最后网页导出是同一次run，只有elapsed_s约0.02s差异，来源及双SHA见[data/report_sources.json](../data/report_sources.json)。原始文件已收到，不再列为“缺少LLM或真机记录”。本次未重新上板。

| 证据入口（JSON路径） | 可核对内容 |
| --- | --- |
| /task_entry、/metadata、/reviews | 用户目标、发送／目标／源码diff审批和审阅轨迹 |
| /cycles/0/execution/audit | 第一轮build／flash／read_target_log／run_hardware_test均成功；周期601.7169 ms，passed=false |
| /cycles/0/model_decision | 实际模型action=edit、reason、白名单文件、before_sha256及完整替换内容 |
| /cycles/0/applied_edit、/reviews | 经人工批准后应用；不是模型自己批准 |
| /cycles/1/execution/audit | 重新执行四接口，周期1001.08682 ms，passed=true |
| /events、/checkpoint | 阶段事件和最终输入身份；历史批准不可恢复／重放 |

实际reason原文：

> 真实 PL 测得 PA1 完整周期为 601.7169 ms，高电平为 300.36864 ms，且当前循环每次翻转后 HAL_Delay(300)，因此一个完整周期包含两次约 300 ms 延时。将单次延时改为 500 ms，预计完整周期约 1000 ms，可满足 ±50 ms 目标。构建成功和烧录 verified 仅证明固件已成功生成并写入，不代表硬件周期通过；UART 的 partial_tail 仅表示采集结束时最后一行缺少换行，不是固件故障。修改后仍需由 PL 重新测量 PA1 判定。

完整差异见[data/final_source_change.diff](../data/final_source_change.diff)。核心为HAL_Delay(300)→500，另有assert_failed注释“error line source number”→“line source number”。完整已批准差异与黄金源码如实保留，不能把历史提案美化为只改一行。

Agent系统提示在[src/agent/src/zhidiao_agent/agent.py](../src/agent/src/zhidiao_agent/agent.py)，目标提取在goals.py。现有JSON记录模型决策和工具反馈，足以支撑本案例的协作过程；它不是完整HTTP请求／响应抓包，不宣称包含未保存的网络报文或所有原始聊天。API Key、认证头、私人部署配置不公开。

## 早期独立案例：PL-only真实LLM闭环

《第一次真实完整LLM测试记录.docx》原件及Agent内摘要均已收到。原Word终端JSON再次核对：run_92dde302095a45cbb607f6371e524149，601.92511→999.92936 ms，两轮各build／flash／run_hardware_test；明确--pl-only、uart_observed=false，没有read_target_log。

模型也提出HAL_Delay(300)→500，但早期最终源码SHA为dfeb0f124d1234c265f248bf8e3014182117dedd2d5f45594e848ea8b258ca8a，与当前主案例黄金源码不同。两份记录不互相覆盖，不将两次实验或两份源码混为一份。公开摘要、原Word身份和范围见[首次真实记录](../src/agent/docs/validation/first-real-loop-2026-10-28.md)。原Word未经单独脱敏，不直接发布。

## 失败诊断与修复过程

原错误记录的read_target_log成功且健康错误为零，窗口末尾只剩Z／ZH，却被truncated触发LOG_INCOMPLETE。修复把正常deadline半行与capture_limit、真实传输错误分开；最终主案例第一轮partial_tail=true、truncated=false后确实继续到PL。详见[窗口修复记录](../src/agent/docs/uart-window-boundary-2026-10-30.md)。这是按原日志和代码归纳的工程纠错，不伪造逐字LLM聊天。

BusyBox整数usleep、UI模型120s deadline、结构化events与LED隔离等工程经验分别见日期文档及[优化记录](optimization_notes.md)。接线照、四灯状态帧、新Windows回归和独立重建仍待整理，不影响已存在的主运行证据。
