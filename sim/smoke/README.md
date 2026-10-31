# 历史 smoke 脚本（仅供参考）

这四份源文件来自单独上传的 zhidiao-smoke-archive.zip，已检查并用 USER 替换个人 Windows 路径。为防止误运行／导入，保留为 .py.txt，不参与 Python unittest 或生产入口；原始附件不变，双份 SHA 见 manifest.json。

| 历史文件 | 原用途 | 当前正式入口／差异 |
| --- | --- | --- |
| period_reader_smoke.py.txt | 多次SSH读取周期／高电平／边沿 | real-test 使用原生 PLPeriodReader，一次SSH并校验快照一致性、计数范围、freshness和预算 |
| hardware_test_smoke.py.txt | 给ObservationBackend注入周期reader | 用于理解稳定接口；正式验收使用真实配置及原生real-test |
| realbackend_hardware_test_smoke.py.txt | 注入reader给RealBackend | 历史目标为600ms，不是当前1000±50ms主实验；不能直接沿用 |
| uart_reader_smoke.py.txt | FIFO reset后逐字节打印 | 原版按循环次数估时、每轮仅取一个字节、只看最终状态且没有整体SSH timeout；正式real-log采用单调deadline、连续drain、健康累积、partial_tail区分和硬预算 |

这些脚本曾用于早期接通硬件，不因归档而获得正式工具的安全／计时保证。尤其不能把旧reader输出当作最终一致性或完整UART证据，也不要把.py.txt改回.py后直接上板。

## 正式检查（在 src/agent）

设置PYTHONPATH=src，以deployment.local.json绑定自己的可信板卡与路径；先运行 real-test --config deployment.local.json --expected-period-ms 1000 --tolerance-ms 50 --preview-only，或 real-log --config deployment.local.json --duration-s 5 --preview-only。
去掉 --preview-only 后仍需明确审批；参考根report/reproduction.md。不得套用历史600ms目标或个人密钥路径。

## 本次验证边界

仅进行Python AST语法与匿名化／SHA校验，不执行脚本，不发SSH、不清FIFO、不访问板卡。它们不是新增的四个公开工具或LLM可调用接口。
