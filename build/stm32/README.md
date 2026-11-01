# STM32 构建

firmware.hex来自最终上传工程，SHA与第二轮真实报告一致；不是在当前云端重新编译。
在Windows根目录运行 ./build/stm32/build.ps1 -KeilUv4 C:/Keil_v5/UV4/UV4.exe。
脚本需要已安装STM32G4 DFP与Arm编译器；日志0 Error(s)与新产物检查后才判构建成功。当前Linux无Keil，未执行硬件编译。

新增并列工程`src/stm32/gpio_pl_test_led`在说明中称`GPIO_PL_Test_LED`；实测时原目录名也为`GPIO_PL_Test`。打开该目录的`mdk-arm/gpio_pl_test.uvprojx`，Target仍为`GPIO_PL_Test`；输出为其自身`mdk-arm/gpio_pl_test/gpio_pl_test.hex`。现有build.ps1默认仍构建原版；新变体可通过同一Agent real-build接口与独立本机配置构建，步骤见[LED工程说明](../../src/stm32/gpio_pl_test_led/readme.md)。旧firmware.hex及旧JSON不作为LED版产物／测量证据。
