# 优化与判断依据

完整周期参考 1000±50 ms：601.7169 ms（误差398.2831）→1001.08682 ms（误差1.08682），两轮 fresh_edges=2。测量表从最终 JSON 自动导出，未修改原始源码。
UART 5 s 窗口恰好截到末行不是丢字节；partial_tail 与 capture_limit、overflow、解码／帧／奇偶错误分开。真实第一轮证明半行后仍执行 PL。
BusyBox 用整数 usleep；捕获采用 /proc/uptime；固定窗口不等待换行，最大字节与 transport 错误仍停止。
资源／时序原报告已从FPGA四分包收到，解析结果见data/fpga_metrics.csv、report/fpga_evidence.md。原底座→最终：LUT6756→7274，FF10853→12083，BRAM20.5不变，IOB38→44；WNS1.091→0.709ns。这里是增加观测／UART／LED功能的开销，不能称为资源下降优化；全设计仍有未约束路径等HIGH警告。
