# 可选四灯工具进度条

更新：2026-11-01。v5位流、BD／XDC和最终运行中的LED配置已收到并核对。软件适配器及离线回归已实现；四阶段及 no-UART LED灯实物状态已归档；普通闪烁／双闪故障态仍按验证边界说明。

## 启用

未提供 status_indicator 或设为 null 时不创建适配器、不发出 LED SSH 命令。当前deployment.example.json与deployment-setup向导默认v5＋LED；deployment.no-led.example.json或向导--no-led保留相同v5／UART／PL、只关闭灯。已有配置不会自动迁移，原有四接口行为保持。

当前v5 PL在初始化阶段加载完成，再启动Agent及LED；Agent使用check_only，保留现有执行顺序。初始化与SSH位流文件SHA校验参考[PL初始化说明](../../../board/zynq/pl_preparation.md)；SHA校验不执行加载，LED开始工作前需确认v5已准备好。

仅在板上已准备包含该 4-bit AXI GPIO 的镜像、确认 Data 寄存器可写且方向已设为输出后，在本机 deployment.local.json 的最外层加入：

```json
"status_indicator": {
  "type": "axi_gpio_led_bar",
  "data_addr": "0x43C60000",
  "active_low": true
}
```

JSON 地址须用字符串。该块只能写固定地址 0x43C60000、32 位宽访问、数值 0～15。bit0～3 依次为 LED1～4；active-low 时 0xF 全灭、0x0 全亮。软件不写 GPIO TRI 方向寄存器，也不主动加载 LED bitstream。

当前位流为build/fpga/zhidiao_observe_v5_led.bit，部署路径/sd/pl/zhidiao_observe_v5_led.bit，SHA-256为fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6。新建配置与两份示例均采用此身份。历史v4路径与SHA只描述旧镜像，不用于当前默认配置；prog_done也不证明运行中的镜像身份或LED地址可访问。

## 显示规则

| 灯 | 公开工具 |
| --- | --- |
| LED1 | build_firmware |
| LED2 | flash_firmware |
| LED3 | read_target_log |
| LED4 | run_hardware_test |

每轮由带新 attempt 的 BUILDING 开始，清空上一轮完成与错误位。未开始灭；当前工具普通闪烁（标称每秒一次）；TOOL_FINISHED 且 success=true 常亮。success=false 或工具抛异常时，该工具双闪，之前成功的灯保持常亮，后续灯灭。双闪标称为亮 120 ms、灭 120 ms、亮 120 ms、灭 640 ms。

run_hardware_test 的 success=true、passed=false 表示测量成功但周期未达标，LED4 正常常亮。AI 分析、等待源码 diff 审批期间保持本轮状态；下一轮 BUILDING 才重新清空。完整四接口流程最终 PASS 后四灯常亮；即使测量 FAIL，四灯也可能全部亮，因此灯不是 DUT PASS/FAIL 的判定器。

显式 PL-only 跳过 UART 时，LED3 始终灭，最终 PASS 只保留实际成功执行工具的灯，避免显示未执行的工具成功。

## 接入与隔离

适配器消费 WorkflowEvents 的 kind、tool_name、attempt、TOOL_FINISHED.success，不解析 UI 文本。仅 ReviewedController 在批准周期实际开始后订阅和启动；预览、目标分析、拒绝会话均不写灯。正常 start_ui.bat / serve / agent-run 的语义和严格审批模式自动接入；独立 real-build / real-flash 命令不额外启动进度条，模拟 UI 也不访问真实 LED。

SessionScope 和逐轮审批原有的 deployment 摘要现包括冻结的 status_indicator；运行中改地址／极性／启停配置会使绑定失效，必须重建后端并重新审批。writer 持有原部署的固定 SSH 目标，模型没有寄存器值、devmem 或 shell 入口；仍只有四个公开硬件工具。

后台 worker 使用独立 ProcessRunner、独立取消事件、严格 known_hosts、非交互 SSH。单次写入上限 2 秒，不占用四接口的 runner，不阻塞工具调用。为避免积压，状态更新会合并；过短阶段可直接显示完成，实际闪烁节奏受 SSH 延迟影响，待真机验证。全灭默认值由硬件提供；软件不会在未经批准的启动界面阶段写入全灭值。

写灯出错只记录固定文本 warning 和结构化 INDICATOR_ERROR / STATUS_INDICATOR_UNAVAILABLE，随后停用本次适配器，避免重试风暴。日志不导出原始 SSH 异常文本。该事件不会改变工具结果、UI 当前工具阶段或 DUT 判定；后台警告若晚于某份报告快照，可在启动终端和实时事件中查看。

线程创建或启动失败也使用同一停用／警告策略，立即清除未启动的线程对象。这样即使工具执行成功，UI／CLI 退出也不会 join 一个未启动的线程而报错。本次复核的复现与边界见 [核查记录](audit-led-2026-10-29.md)。

成功静态状态写入后 worker 自行退出；工具运行和错误双闪期间保留 worker。新 UI 任务／恢复、服务退出或 CLI 返回时会关闭旧适配器、取消自有本地 SSH，并保留最后写入值；进程退出后不承诺持续双闪。直接在 Python 中创建 ReviewedController 的集成方，应在 finally 调用 controller.close_status_indicator()。

## 验收

当前 28 项离线测试覆盖：全部灯位、普通闪烁与双闪时间点、测量 FAIL、下一轮重置、陈旧事件、PL-only、配置与命令注入拒绝、严格 SSH 和四位值、慢／坏 transport 隔离、批准前零写入、会话配置变化、工具异常事件、完整两轮四接口 FAIL→diff→PASS、UI／CLI 清理、UI 阶段不受警告影响，以及线程启动失败时清理／CLI PASS 不受影响。

用户已回传 Windows 首版 26 项专项 1.688 s、OK 截图及 438 项全量通过反馈，随后补验当前 28 项、1.943 s、OK，已覆盖新增启动异常用例。后续 UART 修补的 Windows 记录另计。

板卡返回后先独立验证新增 GPIO 地址和输出方向，再启用本配置。正式联调观察两轮清空与逐灯进度、周期 FAIL 后四灯保持、PASS 保持，以及拔断 LED transport 时工作流判定不受可选显示故障影响。测试 transport 故障宜在可控环境中注入；拔断整板网络本身也会使烧录／观测失败，不能据此推断是 LED 改变了工具结果。
