# 硬件调试失败排查

## 适用范围
适用于PC／Zynq／目标板多层调用链，优先检查工具失败而不是让模型修改源码。

## 使用步骤
1. BUILD_FAILED：核对编译日志和产物，不烧旧HEX。
2. SSH_CONNECT_FAILED：检查路由、host key、非交互认证，不通过关闭验证掩盖问题。
3. UART_READ_FAILED：检查已知镜像、寄存器、BusyBox和单调时钟。
4. LOG_INCOMPLETE：区别正常deadline尾行与真实触限／健康错误。
5. PL超时：检查接线、时钟、valid和新边沿；没有新数据不判PASS。
6. 审批或输入变化：新建会话重新审阅；取消后保存报告。

## 验证方法与已验证效果
src/agent/tests覆盖停止、超时、错误归档、输入变化和LED故障隔离；最终报告证明UART修补后的真实四工具通过。
复用前运行Agent对应离线测试，并在自己的板卡上重做同类测试；当前实例不替代新平台验收。

## 来源
BusyBox无小数sleep、正常UART半行、120s模型请求预算、SSH/PL冷启动恢复等开发观察。

## 失效条件
不能把应用层FAIL、工具故障和人工取消混为一谈。不同平台的设备节点、时钟与认证不可照抄；超出受支持GPIO范围需新设计与验证。

## 可执行的软件检查

从仓库根目录先执行 `python sim/check_release.py` 核对参考证据；再进入 `src/agent`，设置 `PYTHONPATH=src` 后运行：

```text
python -B -m unittest discover -s tests -p "test_audit_fixes.py" -v
```

Windows使用Python3.13时可将python换为`py -3.13`。这些是离线验证，硬件迁移还须按report/reproduction.md重新部署并获得自己的实测报告。
