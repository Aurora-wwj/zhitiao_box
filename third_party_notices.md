# Third-party notices

根 MIT 仅适用于队伍拥有许可权的原创 Agent、文档及脚本；不覆盖第三方代码、自动生成模板或工具。

| 内容 | 来源与许可 |
| --- | --- |
| CMSIS | Arm / ST；src/stm32/gpio_pl_test/drivers/cmsis/license.txt（Apache-2.0） |
| STM32G4 device headers | ST；drivers/cmsis/device/st/stm32g4xx/license.txt；按其声明适用 BSD-3-Clause |
| STM32G4 HAL 与 CubeMX 生成框架 | ST；drivers/stm32g4xx_hal_driver/license.txt，保留各文件版权与上游条款 |
| LED同步工程中的CMSIS／ST头文件／HAL | src/stm32/gpio_pl_test_led中同一来源的独立副本；三个license.txt与版权头原字节保留。仅适配发布路径、Keil／CubeMX引用和一处Legacy头文件路径大小写，不适用根MIT重许可 |
| Keil、CubeMX、Vivado | 外部专有工具，需要用户合法安装；不包含安装包或软件许可证 |
| OpenOCD0.12.0 | src/third_party/openocd的原源码包：GPL-2.0-or-later及各文件SPDX／文档条款；公开展开的copying、licenses及版权头正文保留，原包内COPYING／LICENSES名称不改。原上传静态ELF不再分发 |
| libusb1.0.30 | 同目录原源码包：LGPL-2.1-or-later，COPYING／AUTHORS保留；不适用根MIT |
| ALINX／Digilent 自定义 IP | 已核对上传包，四项 IP 不整体再分发；VLNV／37文件SHA及获取步骤见 data/fpga_external_ips.json、src/fpga/readme.md。保留依赖不等于赋予根MIT许可 |
| AMD/Xilinx 自动生成的 BD、wrapper、约束／工程及工具报告 | 上传最终设计的配置／生成材料，保留原版权头；不以根MIT重许可供应商IP实现或模板。内置IP需由合法Vivado生成 |
| 最终 v5 bitstream | 队伍提供的实现产物，保留黄金SHA；包含外部IP实现，不表示取得其中IP源码的独立许可 |
| Linux/BOOT 镜像 | 以队伍提供的ALINX配套预构建镜像作本地基础，公开来源／版本、SHA、rootfs网络补丁与重封装方法；不以根MIT重新许可整套Linux。历史fixed内嵌私钥、原件含账号数据库，且未确认供应商整镜像再分发范围，原镜像不入Git；没有把完整PetaLinux源码工程列为本路线新增必做项 |
| 当前system_wrapper.hdf | 用户重新导出的Vivado2017.4硬件交接ZIP，保留全部原字节及内部供应商版权／许可文本。内含bit／BD与已有v5一致，生成的PS初始化文件不改为根MIT许可 |

上游参考：https://github.com/STMicroelectronics/STM32CubeG4 ，https://github.com/ARM-software/CMSIS_5 ，https://openocd.org/ 。上传包内第三方许可证与版权头原样保留。

比赛发布的许可证路径已统一小写，原始名称及双SHA见data/repository_path_map.json；此重命名不修改许可证正文或重新授权。原始第三方源码压缩包保持上游字节与内部目录，用于原版本构建及许可溯源，仅在独立且不纳入发布树的构建目录解包。
