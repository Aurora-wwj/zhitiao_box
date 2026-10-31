# STM32 构建

firmware.hex来自最终上传工程，SHA与第二轮真实报告一致；不是在当前云端重新编译。
在Windows根目录运行 ./build/stm32/build.ps1 -KeilUv4 C:/Keil_v5/UV4/UV4.exe。
脚本需要已安装STM32G4 DFP与Arm编译器；日志0 Error(s)与新产物检查后才判构建成功。当前Linux无Keil，未执行硬件编译。
