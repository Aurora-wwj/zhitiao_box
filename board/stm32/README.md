# STM32测试工程

| 工程 | 位置 | 说明 |
| --- | --- | --- |
| GPIO_PL_Test | [原工程](../../src/stm32/gpio_pl_test) | 现有黄金源码与HEX、两轮四接口JSON对应工程 |
| GPIO_PL_Test_LED | [LED同步版](../../src/stm32/gpio_pl_test_led/readme.md) | 八个板载用户LED由同一PA1翻转循环更新；采用源码所述DK117E-G4连接映射 |

LED工程实测验证时原目录名同样为`GPIO_PL_Test`，发布位置按英文小写规则区分。原工程和黄金HEX索引仍在../../data/，保持原始字节；本LED变体需单独生成HEX并保存测量证据。
