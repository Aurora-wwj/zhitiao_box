# 验证入口

Agent全部离线测试：在src/agent运行PYTHONPATH=src python3.13 -B -m unittest discover -s tests -v。
UART专项：-p "*uart*.py"；LED专项：-p test_status_indicator.py。
根目录运行 python3 sim/check_release.py 核对最终证据、源码／HEX身份和Keil文件引用。
工具没有Vivado／Keil／开发板时，不把软件验证当作硬件重建或重新上板。

## FPGA验证

安装Icarus Verilog（iverilog和vvp）及Tcl，在根目录运行：

```sh
python -B -m unittest discover -s sim -p test_fpga_release.py -v
```

6项回归涵盖黄金文件与原报告解析、BD／XDC契约、外部IP校验器的正反例、原计数RTL实际仿真和构建Tcl控制流。RTL覆盖六组行为，见fpga/measure_core_tb.v；Tcl构建测试使用命令替身，不验证Vivado API或IP布局。无模拟器／Tcl时相应项显示skip，不能标成已运行。

非系统安装可通过IVERILOG、VVP指定可执行路径，IVERILOG_BASE指定iverilog的ivl库目录。临时.vvp自动清理。无板卡、网络API或任意devmem调用。另见../report/fpga_evidence.md的启动相位和时序覆盖边界。

## Zynq公开材料与检查脚本

在根目录运行 `python3.13 -B -m unittest discover -s sim -p test_zynq_release.py -v`。覆盖20份源码／许可的SHA与tar成员、来源清单、源码损坏拒绝、已有构建目录保护、只读SD文件检查及错误位流／缺失工具拒绝。脚本不执行上传ARM程序、不写板卡；完整OpenOCD本机编译是额外的构建验证，见build/openocd及data/test_summary.md。CI没有把本机编译或ARM上板写成自动通过。

## 历史脚本

smoke/ 保存经过匿名化的四份 .py.txt 历史材料，不能直接执行；正式入口映射及已知缺陷见 smoke/README.md。正式离线测试仍在 src/agent/tests。

## 大附件分包

prepare_upload_parts.py用于切分／验证重组上传原件，步骤见../report/upload_parts.md。工具回归：python -B -m unittest discover -s sim -p test_upload_parts.py -v（在根目录运行）。不访问硬件或API。
