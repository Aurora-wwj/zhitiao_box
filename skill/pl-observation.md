# 可信 PL 观测

## 适用范围
适用于硬件计数器具备周期／高电平、有效位及边沿计数的系统；需要已知时钟和镜像。

## 使用步骤
1. 核对时钟、镜像与GPIO身份。
2. 采集开始边沿计数，等待至少两个新边沿。
3. 用前后边沿计数夹住寄存器快照，检查valid和一致性。
4. 依据真实时钟换算ms；由确定性程序计算误差与容差。
5. 首先检查32位计数范围和可用观察窗口。

## 验证方法与已验证效果
最终两轮fresh_edges=2，period_ticks=60171690／100108682，100MHz；见公开报告observation字段。软件PL测试覆盖旧值与不一致。
复用前运行Agent对应离线测试，并在自己的板卡上重做同类测试；当前实例不替代新平台验收。

## 来源
从旧寄存器值可能冒充当前固件的观测风险和freshness超时经验提炼。

## 失效条件
prog_done不证明运行镜像身份；没有新边沿／valid、计数超范围、未知时钟或窗口不足时不可判PASS。

## 可执行的软件检查

从仓库根目录先执行 `python sim/check_release.py` 核对参考证据；再进入 `src/agent`，设置 `PYTHONPATH=src` 后运行：

```text
python -B -m unittest discover -s tests -p "test_pl_observer.py" -v
```

Windows使用Python3.13时可将python换为`py -3.13`。这些是离线验证，硬件迁移还须按report/reproduction.md重新部署并获得自己的实测报告。
## 本次原件检查补充

已收到最终计数RTL和实现报告，来源与SHA见data/fpga_manifest.json；Icarus仿真覆盖见sim/fpga/measure_core_tb.v。同步器复位为0，输入复位时已HIGH的首次valid可能包含启动残段；应等待后续稳定周期，不能仅凭valid或两个新边沿保证所有启动相位。valid也会保留旧结果，freshness检查不可省。
原全设计时序报告仍有未约束路径等HIGH警告，不能用正WNS单独证明CDC、所有外部I/O或全设计时序覆盖完成。黄金RTL／位流本次未修改，详情见report/fpga_evidence.md。
