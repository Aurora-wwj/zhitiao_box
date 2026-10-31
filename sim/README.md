# 验证入口

Agent全部离线测试：在src/agent运行PYTHONPATH=src python3.13 -B -m unittest discover -s tests -v。
UART专项：-p "*uart*.py"；LED专项：-p test_status_indicator.py。
根目录运行 python3 sim/check_release.py 核对最终证据、源码／HEX身份和Keil文件引用。
工具没有Vivado／Keil／开发板时，不把软件验证当作硬件重建或重新上板。

## 历史脚本

smoke/ 保存经过匿名化的四份 .py.txt 历史材料，不能直接执行；正式入口映射及已知缺陷见 smoke/README.md。正式离线测试仍在 src/agent/tests。
