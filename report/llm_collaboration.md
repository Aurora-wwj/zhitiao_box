# LLM协作与证据索引

## Representative LLM Collaboration Record

本项目保留了一次完整、可核验的大模型协作闭环。该案例展示了大模型如何依据真实硬件反馈提出源码修改，并由人工审批与确定性硬件测量完成最终验证。

### Evidence-Driven Iteration

```text
Natural-language goal
“把 STM32 PA1 的完整周期调到 1000 ms，误差不超过 50 ms”
        ↓
Build + Flash + UART + FPGA PL Measurement
        ↓
Round 1 physical evidence
Period = 601.7169 ms
High time = 300.36864 ms
Verdict = FAIL
        ↓
Model reasoning
A full GPIO period contains two toggle intervals.
HAL_Delay(300) therefore produces a period of about 600 ms.
        ↓
Proposed source edit
HAL_Delay(300) → HAL_Delay(500)
        ↓
Human review and approval
        ↓
Rebuild + Reflash Target MCU + UART + FPGA PL Measurement
        ↓
Round 2 physical evidence
Period = 1001.08682 ms
High time = 500.07403 ms
Absolute error = 1.08682 ms
Verdict = PASS
```

### Prompt / Context → Model Response → Approved Diff → Physical Verification

**Prompt / Context.**
模型接收自然语言目标、经批准的 STM32 源码以及本轮真实工具结果。第一轮中，构建与烧录均成功，但 FPGA PL 独立测得 PA1 完整周期仅为 `601.7169 ms`，因此工具执行成功并不等同于 DUT 达标。

**Recorded User Prompt.**
主案例中保存的用户任务原文为：

```text
把 STM32 PA1 的完整周期调到 1000 ms，误差不超过 50 ms
```

**Representative System Prompt Excerpt.**
当前固定代码 `src/agent/src/zhidiao_agent/agent.py` 中的系统提示模板包含以下原文，用于约束模型只能依据已提供证据提出建议，并明确区分模型推理、工具执行与硬件判定：

```text
Propose changes and explain evidence. Never claim that tools ran or tests passed
without supplied results. You cannot approve or execute operations.
The deterministic controller owns tool order and retry limits.
Distinguish tool success, flash verification and hardware test pass.
```

该摘录来自当前公开源码中的系统提示模板；运行时模型还会接收用户任务、经批准的源码和本轮结构化工具证据。历史未保存的 HTTP 请求/响应报文不据此重建。

**Model Response.**
模型结合源码中的 `HAL_Delay(300)` 与 PL 测得的 `601.7169 ms` 周期、`300.36864 ms` 高电平时间进行分析，判断一个完整周期包含两次约 300 ms 的翻转间隔，因此提出将单次延时修改为 500 ms，并明确要求修改后重新通过物理测量验证，而不能依据模型预测直接宣布 PASS。

**Approved Diff.**
人工审阅完整源码 diff 后批准修改。核心功能修改为：

```diff
- HAL_Delay(300);
+ HAL_Delay(500);
```

实际批准的完整 diff 还包含一处与功能无关的注释文字调整；项目保留原始完整差异，不将历史记录重新美化为“只修改一行”。

**Physical Verification.**
修改后系统重新构建并烧录目标 STM32G431RBT6，随后重新采集 UART 与 FPGA PL 证据。第二轮 PL 独立测得完整周期 `1001.08682 ms`，相对 1000 ms 目标的绝对误差为 `1.08682 ms`，满足 ±50 ms 容差，由确定性硬件测试规则判定为 `PASS`。

### Responsibility Boundary

本案例中的职责边界保持明确：

* **AI Model**：理解目标、分析证据、提出源码修改；
* **Human**：审阅并批准新的源码 diff；
* **Controller**：约束工具顺序、路径、预算、重试与停止条件；
* **Tool Backend**：执行真实构建、目标 MCU 烧录、UART 采集与硬件测试；
* **FPGA PL**：独立测量目标硬件的真实物理行为；
* **PASS / FAIL**：由确定性测试规则产生，而非由模型自行声明。

因此，本项目中的“大模型协作”并非让模型直接控制任意硬件命令，而是形成：

**真实证据 → 模型分析 → 人工批准 → 真实执行 → 新物理证据**

的受控闭环。

### Evidence Files

该代表性交互可通过仓库中的以下材料交叉核验：

* `data/final_run_sanitized.json`：两轮真实工具结果、模型决策、人工审批及最终判定；
* `data/final_source_change.diff`：实际批准并应用的完整源码差异；
* `data/measurements.csv`：两轮物理测量结果；
* `report/test_evidence.md`：真机证据与测试口径说明。

本文只将具有现有记录支持的内容归因于模型；未保存的原始网络请求或对话不会被重新构造为“原始交互记录”。


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

BusyBox整数usleep、UI模型120s deadline、结构化events与LED隔离等工程经验分别见日期文档及[优化记录](optimization_notes.md)。
