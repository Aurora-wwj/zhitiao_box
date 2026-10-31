# FPGA 原件、验证与复现范围

2026-11-01：四个 part-0001.zip ～ part-0004.zip 按上传工具清单重组，原 Zhidiao_PL.zip 共116739469字节，SHA-256为1f87f8d6dad48ae1286790ebec802fd776a0e939093d7cb384498fa327abf052。分包不改变原件；原始大 ZIP 和所有缓存不进 Git。

保留最终测量工程的 RTL、BD、导出 Tcl、wrapper、四份约束和工程文件；发布 v5 位流。为资源对比只保留原始 baseline/final 的 utilization_placed 与 timing_summary_routed，不复制全部生成文件。报告仅替换主机名；数据未重算为更好结果。每项来源和双 SHA 见 data/fpga_manifest.json。

| 指标 | 原始 vendor baseline | 最终 v5 工程 | 差值 |
| --- | ---: | ---: | ---: |
| LUT | 6756 | 7274 | +518 |
| FF | 10853 | 12083 | +1230 |
| BRAM tiles | 20.5 | 20.5 | 0 |
| DSP | 0 | 0 | 0 |
| IOB | 38 | 44 | +6 |
| WNS/ns | 1.091 | 0.709 | -0.382 |
| WHS/ns | 0.047 | 0.020 | -0.027 |
| TNS / THS | 0 / 0 | 0 / 0 | 0 / 0 |

这是在供应商摄像头／HDMI底座增加周期观测、UART和LED后的整套设计开销，不是对同一功能做资源下降优化。不能从两个报告单独证明每个模块的精确增量。报告与位流是同一上传工程交付物，但没有独立签名的构建日志将二者强绑定；未在云端重建证明。

时序报告“已指定约束满足”的同时，final 有942个未约束最大延迟pin、22个无input delay输入、10个无output delay输出、两路cmos_pclk各244个寄存器无时钟及1个generated clock未接源。保留原警告；正WNS不是全设计时序覆盖证明。跨时钟同步与所有外部接口约束仍需实际Vivado审阅。

独立 Icarus Verilog 仿真覆盖周期／高电平／边沿计数、变化、无信号、复位及32位回绕。它不是全BD／UART／AXI／LED仿真。startup HIGH的首次值可能包含复位残段，valid为sticky；见src/fpga/README.md。没有修改黄金RTL/bitstream来隐藏该边界。

构建入口见build/fpga/README.md。外部IP因完整再分发许可未附而以VLNV／37文件SHA清单及合法获取步骤交付；不称为无需依赖的一键工程。后续已收到Zynq_Linux_Test并核对OpenOCD源码／FIT组成，详见report/zynq_intake.md；完整BOOT／Linux构建输入仍缺，不能把测试包检查说成镜像已重建或冷启动已验证。
