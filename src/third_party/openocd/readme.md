# OpenOCD／libusb 源输入与许可

这两份源码压缩包来自队友上传的 Zynq_Linux_Test.zip，按原字节保存。没有声称已独立验证官方签名，也没有用上传的静态 ELF 代替源码。

| 输入 | 字节数 | SHA-256 |
| --- | ---: | --- |
| openocd-0.12.0.tar.gz | 8445833 | bb367fd19ab96a65ee5b269b60326d9f36bca1c64d9865cc36985d3651aba563 |
| libusb-1.0.30.tar.bz2 | 656112 | fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf |

OpenOCD 主许可为 GPL-2.0-or-later，另有各文件的 SPDX 条款、文档许可及例外；原压缩包完整保留 COPYING、LICENSES、版权头和源码。libusb 为 LGPL-2.1-or-later，完整 COPYING、AUTHORS 等均保留。为便于阅读，licenses/ 另存对应许可原文副本。这些内容不适用仓库根 MIT 重许可。

上游入口：https://openocd.org/pages/getting-openocd.html ，https://libusb.info/ 。来源与公开 SHA 逐项见 ../../../data/zynq_linux_manifest.json。

构建入口为 ../../../build/openocd/build.py，步骤见[构建说明](../../../build/openocd/readme.md)。原上传 ARM 静态二进制未发布：未提供其确切工具链、编译参数和全部静态链接依赖的对应源码，不能用这两个压缩包声称已满足该二进制的全部源码／重链接要求。新构建也不默认等同于原件，需重新核对架构、SHA 和板卡行为。
