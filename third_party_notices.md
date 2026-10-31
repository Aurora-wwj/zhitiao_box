# Third-party notices

根 MIT 仅适用于队伍拥有许可权的原创 Agent、文档及脚本；不覆盖第三方代码、自动生成模板或工具。

| 内容 | 来源与许可 |
| --- | --- |
| CMSIS | Arm / ST；src/stm32/gpio_pl_test/Drivers/CMSIS/LICENSE.txt（Apache-2.0） |
| STM32G4 device headers | ST；Drivers/CMSIS/Device/ST/STM32G4xx/LICENSE.txt；按其声明适用 BSD-3-Clause |
| STM32G4 HAL 与 CubeMX 生成框架 | ST；Drivers/STM32G4xx_HAL_Driver/LICENSE.txt，保留各文件版权与上游条款 |
| Keil、CubeMX、Vivado | 外部专有工具，需要用户合法安装；不包含安装包或软件许可证 |
| OpenOCD | 外部 GPL 软件；当前不再分发二进制，部署者须从官方来源获取并履行其许可 |
| ALINX／Digilent 自定义 IP | 已核对上传包，四项 IP 不整体再分发；VLNV／37文件SHA及获取步骤见 data/fpga_external_ips.json、src/fpga/README.md。保留依赖不等于赋予根MIT许可 |
| AMD/Xilinx 自动生成的 BD、wrapper、约束／工程及工具报告 | 上传最终设计的配置／生成材料，保留原版权头；不以根MIT重许可供应商IP实现或模板。内置IP需由合法Vivado生成 |
| 最终 v5 bitstream | 队伍提供的实现产物，保留黄金SHA；包含外部IP实现，不表示取得其中IP源码的独立许可 |
| Linux/BOOT 镜像 | SD大包尚未可读取，未发布；来源、许可和重建方式待核对 |

上游参考：https://github.com/STMicroelectronics/STM32CubeG4 ，https://github.com/ARM-software/CMSIS_5 ，https://openocd.org/ 。上传包内第三方许可证与版权头原样保留。
