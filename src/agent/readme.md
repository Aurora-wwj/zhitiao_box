# 智调 Agent 软件包

当前仓库路径已按提交规范统一小写：原工程入口为`mdk-arm/gpio_pl_test.uvprojx`，源码为`core/src/main.c`；历史记录保留原名，见仓库`report/path_migration.md`。私人配置需按当前工程重新核对，不自动修改。

本目录保持 Python 3.13 的原 src/zhidiao_agent、tests、启动器布局。请先读仓库根 README.md 和 report/reproduction.md。

最终真实两轮四接口：601.7169→1001.08682 ms PASS，证据见 ../../data/final_run_sanitized.json；src/agent/docs 内旧进度为历史快照。
在本目录运行 start_demo.bat、start_ai_mock.bat 或 start_ui.bat；区别和配置见根 README。
上传包中的真实 UI NiceCodeConfig timeout_s=120 已保留。公开示例和 deployment-setup 向导统一为 v5＋LED；位流已在 ../../build/fpga/zhidiao_observe_v5_led.bit。deployment.no-led.example.json 或向导 --no-led 使用同一 v5，仅关闭灯；未配置 status_indicator 的原有配置仍保持不写灯。

示例路径须替换为本机路径，确认板端镜像后再运行；私人 deployment.local.json 不公开，向导不会覆盖已有配置。当前操作说明见 [v0.5 集成](docs/integration-v0.5.md)，原始材料与公开路径对照见 [材料索引](../../report/material_index.md)。
