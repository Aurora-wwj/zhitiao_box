# UART 证据采集

## 适用范围
适用于有可控FIFO和单调时钟的串口观测；当前AXI Uartlite，115200 8N1。

## 使用步骤
1. 预览并批准一次RX FIFO reset，排除旧数据。
2. 单次SSH连续drain，只有空FIFO时按整数usleep等待。
3. 用单调时钟设置固定窗口，按换行组装文本。
4. deadline半行保留为partial_tail，不扩大窗口等待换行。
5. max_bytes／transport丢失／overflow／解码／帧／奇偶错误仍停止。

## 验证方法与已验证效果
最终真实第一轮partial_tail=true、truncated=false，后续PL仍执行；第二轮无半行。联合UART离线专项覆盖错误分类。
复用前运行Agent对应离线测试，并在自己的板卡上重做同类测试；当前实例不替代新平台验收。

## 来源
从5s窗口末尾Z／ZH被旧truncated误判导致LOG_INCOMPLETE的真实失败提炼。

## 失效条件
不是所有半行都健康；不能清除真正truncated或错误标记。旧reader含糊的truncated=true保持停止；时间戳是读出时间，不是线上到达时间。

## 可执行的软件检查

从仓库根目录先执行 `python sim/check_release.py` 核对参考证据；再进入 `src/agent`，设置 `PYTHONPATH=src` 后运行：

```text
python -B -m unittest discover -s tests -p "*uart*.py" -v
```

Windows使用Python3.13时可将python换为`py -3.13`。这些是离线验证，硬件迁移还须按report/reproduction.md重新部署并获得自己的实测报告。
