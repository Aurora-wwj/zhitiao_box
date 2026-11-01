# 首次真实 LLM 闭环证据摘要

依据用户上传的“第一次真实完整LLM测试记录.docx”、126.41 秒录像及 v0.5 规划 PDF。已核对 Word 的命令、源码 diff、两轮工具结果，以及录像中的审批和最终结果。本文保留必要的 run_id 和数值，省略个人 Windows 用户目录与认证文件内容。

| 项目 | 记录 |
| --- | --- |
| run_id | run_92dde302095a45cbb607f6371e524149 |
| 来源 | 真实 NiceCode、Keil、Zynq、OpenOCD、STM32、PL |
| 工程 / Target | E:\Project\GPIO_PL_Test / GPIO_PL_Test |
| 源文件 | Core/Src/main.c |
| 目标 | PA1 完整周期 1000 ms，容差 ±50 ms |
| 模式 | --pl-only；uart_observed=false；明确跳过 read_target_log |
| 初次实测 | 601.92511 ms，60192511 ticks，fresh_edges=4，FAIL |
| AI 判断 | 300 ms 是单次 toggle 间隔，完整周期约 2×300 ms |
| 获批修改 | HAL_Delay(300) → HAL_Delay(500) |
| 第二次实测 | 999.92936 ms，99992936 ticks，fresh_edges=2，PASS |
| 最终状态 | attempts=2，evidence_source=real，hardware_state_uncertain=false |
| Orchestrator 耗时 | 91.4098352 s，不含此前全部用户交互时间 |

两轮 build 均产生新 HEX，Keil 为 0 Error(s)、0 Warning(s)。flash 保留本地／远端 SHA 一致、Programming Finished、Verified OK 与 Resetting Target。两轮 PL 均 freshness_verified=true；最终判定由容差规则完成。

```diff
- HAL_Delay(300);
+ HAL_Delay(500);
```

源码修改前 SHA：7a9f900ade8d8564e51d4053d38edc1fd31cc227f87bb76ab63029567d92dc54

源码修改后 SHA：dfeb0f124d1234c265f248bf8e3014182117dedd2d5f45594e848ea8b258ca8a

这证明早期三接口真实Agent闭环，明确不证明UART。上文数值已重新对照收到的Word终端JSON核验；完整四接口是后续run_5d8e…，见[最终验证](final-real-loop-2026-10-30.md)，不能按早期记录的旧“待验收”措辞否定后来的真实结果。录像与Word原件作为原始材料保留，不作为运行依赖，也未原样公开。

原Word SHA-256：1952c1f9dc887ea2e85227f3fb031aab93bfc356ca8da7341222c50c89266a52。该哈希标识本次收到的附件，不认证硬件来源；公开摘要省略私人路径与认证信息。
