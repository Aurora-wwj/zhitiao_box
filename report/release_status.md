# 发布状态

2026-11-01 分包整理阶段。

已收到并整理：Agent 正式代码／测试／启动器；GPIO_PL_Test 重建输入；最终 HEX；两轮真实四工具报告的匿名副本。
已核对：main.c SHA、提案 UTF-8 SHA、checkpoint 一致；HEX 与第二轮产物 SHA 一致；两轮 audit／freshness／UART partial-tail。
待补：最终 FPGA 源工程／BD／IP／XDC、v5 bit、utilization／timing 原报告、板端脚本及镜像许可来源、实物图片、官网同版设计报告。
指南所述 bit SHA 与资源数字目前仅可作为待核对引用，不标成仓库已具备或本次重新验证。
没有用旧 Agent checkout 或虚构 FPGA 文件替代缺失材料。

## 后续分包接收：smoke／SD

已接收并检查4份历史smoke代码，个人路径已匿名化，发布为sim/smoke/*.py.txt，保留来源与公开版SHA，不参与运行。
Zhidiao_Linux_microSD.zip超过当前32MiB附件传输上限，无法读取，未执行任何板端内容。仍需拆分上传小包后核对v5位流、脚本、OpenOCD／BOOT／Linux来源及许可；不从名称推断二进制可再分发。

## 后续FPGA大包接收

Zhidiao_PL.zip同样超过32MiB限制，未能下载到工作区。FPGA源码、位流和实现报告仍未检视。新增sim/prepare_upload_parts.py将原件切成普通小ZIP，重组后校验整体SHA，方便继续接收；步骤见upload_parts.md。5项工具回归通过，不替代FPGA重建／上板。
