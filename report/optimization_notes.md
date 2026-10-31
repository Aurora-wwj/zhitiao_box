# 优化与判断依据

完整周期参考 1000±50 ms：601.7169 ms（误差398.2831）→1001.08682 ms（误差1.08682），两轮 fresh_edges=2。测量表从最终 JSON 自动导出，未修改原始源码。
UART 5 s 窗口恰好截到末行不是丢字节；partial_tail 与 capture_limit、overflow、解码／帧／奇偶错误分开。真实第一轮证明半行后仍执行 PL。
BusyBox 用整数 usleep；捕获采用 /proc/uptime；固定窗口不等待换行，最大字节与 transport 错误仍停止。
资源／时序优化前后比较尚缺原始 FPGA 报告，暂不把指导 PDF 的资源数作为已独立核验结果。
