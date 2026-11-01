# Third-party notices

根 MIT 仅适用于队伍拥有许可权的原创 Agent、文档及脚本；不覆盖第三方代码、自动生成模板或工具。

| 内容 | 来源与许可 |
| --- | --- |
| CMSIS | Arm / ST；src/stm32/gpio_pl_test/Drivers/CMSIS/LICENSE.txt（Apache-2.0） |
| STM32G4 device headers | ST；Drivers/CMSIS/Device/ST/STM32G4xx/LICENSE.txt；按其声明适用 BSD-3-Clause |
| STM32G4 HAL 与 CubeMX 生成框架 | ST；Drivers/STM32G4xx_HAL_Driver/LICENSE.txt，保留各文件版权与上游条款 |
| LED同步工程中的CMSIS／ST头文件／HAL | src/stm32/gpio_pl_test_led中同一来源的独立副本；三个license.txt与版权头原字节保留。仅适配发布路径、Keil／CubeMX引用和一处Legacy头文件路径大小写，不适用根MIT重许可 |
| Keil、CubeMX、Vivado | 外部专有工具，需要用户合法安装；不包含安装包或软件许可证 |
| OpenOCD0.12.0 | src/third_party/openocd的原源码包：GPL-2.0-or-later及各文件SPDX／文档条款；COPYING、LICENSES与版权头保留。原上传静态ELF不再分发 |
| libusb1.0.30 | 同目录原源码包：LGPL-2.1-or-later，COPYING／AUTHORS保留；不适用根MIT |
| ALINX／Digilent 自定义 IP | 已核对上传包，四项 IP 不整体再分发；VLNV／37文件SHA及获取步骤见 data/fpga_external_ips.json、src/fpga/README.md。保留依赖不等于赋予根MIT许可 |
| AMD/Xilinx 自动生成的 BD、wrapper、约束／工程及工具报告 | 上传最终设计的配置／生成材料，保留原版权头；不以根MIT重许可供应商IP实现或模板。内置IP需由合法Vivado生成 |
| 最终 v5 bitstream | 队伍提供的实现产物，保留黄金SHA；包含外部IP实现，不表示取得其中IP源码的独立许可 |
| Linux/BOOT 镜像 | 已核对Zynq_Linux_Test组成，但缺完整构建来源／许可，且fixed内嵌私钥；不发布原镜像。原完整SD大包仍未读取 |

上游参考：https://github.com/STMicroelectronics/STM32CubeG4 ，https://github.com/ARM-software/CMSIS_5 ，https://openocd.org/ 。上传包内第三方许可证与版权头原样保留。
