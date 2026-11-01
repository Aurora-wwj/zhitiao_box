# FPGA 位流、报告与重建入口

`zhidiao_observe_v5_led.bit` 是上传的最终 v5，1,904,732 bytes，SHA-256：

```text
fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6
```

`reports/baseline` 和 `reports/final` 保存原始 placed utilization / routed timing summary，仅匿名化主机名。原件和公开版 SHA 见 ../../data/fpga_manifest.json。指标从报告解析为 ../../data/fpga_metrics.json 和 CSV。没有从 PDF 抄数字替代原始报告，也没有把位流 SHA 与报告之间未提供的构建签名说成已证明。

## Vivado 2017.4 重建

先安装合法 Vivado 2017.4，取得并通过 `check_ip_repo.py` 检查四项外部 IP，详见 ../../src/fpga/readme.md。在仓库根目录执行（在已配置 Vivado PATH 的终端）：

```powershell
py -3.13 -B build/fpga/check_ip_repo.py D:/vendor/ip_repo
vivado -mode batch -source build/fpga/build.tcl -tclargs -ip-repo D:/vendor/ip_repo -output D:/work/zhitiao-v5-project -mode project
```

`project` 模式创建工程、恢复 BD、验证连接并生成 wrapper，不执行综合。要完整生成新位流，使用另一份不存在的输出目录：

```powershell
vivado -mode batch -source build/fpga/build.tcl -tclargs -ip-repo D:/vendor/ip_repo -output D:/work/zhitiao-v5-build -mode bitstream -jobs 2
```

输出为新目录下 `zhitiao_fpga.runs/impl_1/system_wrapper.bit` 及 reports。脚本检查版本、IP、BD 单元、综合／实现进度、产物与 setup/hold slack；拒绝覆盖现有目录，不写板卡，不覆盖黄金 v5。必须继续人工审查 DRC、时序覆盖／pulse-width／CDC 与板卡行为。报告中的“所有已指定约束满足”不等于所有路径都已约束。

重建位流受生成时间等元数据影响，不能保证新文件 SHA 等于黄金 bit；新 SHA 需重新绑定 deployment 并验收，不能直接借用旧运行 JSON 的身份。

## 已运行与未运行

Linux 已实际运行 Icarus RTL 仿真、文件／报告校验、外部 IP 原件校验及 Tcl 控制流回归。Tcl 回归使用命令替身，只验证脚本路径和错误分支，不能验证 Vivado API、IP 重生成或布线。云端没有 Vivado／Keil／板卡，完整重建命令尚待实际 2017.4 环境执行；2025.2／2026.1 升级未验证。

原 final 报告 WNS=0.709 ns，TNS=0，但仍有 942 个无最大延迟约束的 pin、22 个缺 input delay 的端口、10 个缺 output delay 的端口，两路摄像头各 244 个寄存器时钟未定义，以及 1 个未接源的 generated clock 警告。应按用途补约束／明确豁免，不能标成全设计时序覆盖完成。
