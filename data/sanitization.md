# 公共证据处理

来源：上传 Agent 包中的 run_5d8e004954664f6c8f8ff0f85d31959b.json。原件保留在上传附件，未覆盖。
公开副本将 Windows 个人用户目录替换为 USER，项目与 Keil 路径替换为统一示例路径。
保留 run_id、四接口 audit、模型提案、diff、源码／产物 SHA、UART 与 PL 实测。
提案 content 的 UTF-8 SHA 与发布 main.c、checkpoint 一致；最终 HEX SHA 与第二轮 build／flash 一致。
路径匿名化后，原有审批 fingerprint 仅为历史证据，不能用于恢复授权或重放审批。

FPGA整理：四份实现报告与生成wrapper中的个人主机名替换为BUILD_HOST；XPR只将根Project的原绝对Path替换为linux_ov5640.xpr。保留所有版权头、指标和设计关系；data/fpga_manifest.json逐项记录原始／公开SHA和变动类型。原创RTL、四份XDC、BD与导出Tcl未改字节。原件仍在上传附件，不覆盖。
