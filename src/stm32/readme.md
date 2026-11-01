# STM32测试代码（Keil工程）

原合集的`Project`目录对应本仓库`src/stm32`。两份工程并列，均可独立选择：

| 合集／说明名称 | GitHub目录 | 用途与证据 |
| --- | --- | --- |
| Project/GPIO_PL_Test | [gpio_pl_test](gpio_pl_test) | 原成功工程，已有两轮四接口JSON与黄金HEX |
| Project/GPIO_PL_Test_LED | [gpio_pl_test_led](gpio_pl_test_led/readme.md) | 八个用户LED与PA1同步的直观演示；单独构建和验证 |

LED工程实测验证时，文件夹原名也为`GPIO_PL_Test`。GitHub新增路径按AMD指南使用英文小写，说明名称保留`GPIO_PL_Test_LED`；不要覆盖原工程或混用两份固件证据。Keil Target均保留`GPIO_PL_Test`，新变体的项目文件及源码路径采用英文小写。
