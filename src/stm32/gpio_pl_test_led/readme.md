# GPIO_PL_Test_LED：STM32用户LED与PA1同步演示工程

这是队友补充的独立Keil工程，和原`../gpio_pl_test`并列保留，用于让硬件测试更直观。按AMD选题指南3.3.5.4的英文小写命名要求，GitHub目录为`src/stm32/gpio_pl_test_led`，对应合集中的逻辑位置`Project/GPIO_PL_Test_LED`。

**队友说明：实测验证时，这个工程文件夹的原名也是`GPIO_PL_Test`。** 发布说明中称为`GPIO_PL_Test_LED`以便与原工程区分；内部Keil Target仍为`GPIO_PL_Test`。原工程、黄金HEX和已有实测JSON保持不变。

## 效果与适用硬件

- 目标芯片为STM32G431RBT6；源码采用DK117E-G4板卡的LED连接映射。
- PC8～PC15通过板载M74LS573控制LD1～LD8，PD2保持高电平使能锁存器；LED为低电平亮。
- PA1每次翻转后，`DK117E_LED_FollowPA1()`读取PA1并更新八灯：PA1高时灯亮，PA1低时灯灭。
- PA1方波与八灯共用同一主循环节拍，没有另设LED定时器。GPIO读取／写入存在执行延迟，不能把软件同步描述为零延迟硬件同沿。
- 这里的“全部LED”指该板八个用户灯；电源、USB及调试器指示灯不由此程序控制。LED及锁存器均为该板已有器件，无需额外外接显示硬件。

实际附件`main.c`为`HAL_Delay(500)`，原字节保留；完整周期标称约1000 ms，实际以PL测量为准。PA2／USART2仍为115200 8N1，每四次翻转输出一次`ZHIDIAO_OK`。PC8～PC15与LCD数据线复用，此演示不同时运行LCD。

## 打开与重新构建

1. 在Keil中打开本目录`mdk-arm/gpio_pl_test.uvprojx`，选择Target `GPIO_PL_Test`。
2. 安装工程声明的`Keil.STM32G4xx_DFP.2.0.0`与兼容的Arm Compiler 5；上传项目记录为V5.06 update 6（build 750）。
3. 执行Rebuild，检查新构建日志与新HEX。输出配置为`mdk-arm/gpio_pl_test/gpio_pl_test.hex`，不要把仓库`build/stm32/firmware.hex`当作LED版产物。

本目录按英文小写发布，已同步Keil的本地源文件／头文件目录和输出名称、CubeMX工程名及主文件路径；Target、器件和原编译设置保持。`gpio_pl_test.ioc`仍按原配置保留，LED初始化位于main.c的USER CODE块；如重新用CubeMX生成，应复核PC8～PC15／PD2占用及文件路径。

## 接入现有Agent

在`src/agent`复制公开部署示例为私人`deployment.local.led.json`，填写自己的路径和认证，并修改以下非秘密字段；该本机文件不上传：

```json
{
  "allowed_roots": ["C:\\work\\zhitiaohe\\src\\stm32\\gpio_pl_test_led"],
  "project_file": "mdk-arm/gpio_pl_test.uvprojx",
  "target": "GPIO_PL_Test"
}
```

以上是已有部署配置的字段片段；其余v5、SSH、UART与LED配置按实际部署保留。可信启动窗口选择此工程，允许修改的源文件为`core/src/main.c`。构建仍使用原来的四接口，预览示例（在`src/agent`的PowerShell）：

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
$led_project = (Resolve-Path ..\stm32\gpio_pl_test_led).Path
py -3.13 -B -m zhidiao_agent real-build $led_project --config deployment.local.led.json --preview-only
```

审阅后去掉`--preview-only`并按提示批准，才会执行Keil。当前源码已经是500 ms延时，首次可能直接达标；不要为了展示重用或伪造一次FAIL→修改→PASS记录。现有根目录构建脚本仍默认原工程。

## 来源与验证范围

来源为本次上传的`GPIO_PL_Test.zip`；原始成员到公开文件的路径、原始／公开SHA及必要大小写适配见`../../../data/stm32_led_manifest.json`。附件旧README、CHANGELOG、MANIFEST及校验脚本仍描述300 ms基线，与实际500 ms源码不一致，未沿用；缓存、用户IDE选项和编译产物按原仓库规则排除。

仓库提供源文件身份／工程引用检查及主机HAL替身验证，用于验证LED与PA1的软件同步关系；具体执行结果见`../../../data/stm32_led_verification.txt`。本次环境没有Keil或板卡，未重新编译或上板。队友提供的用途及实测原目录名如实记录；旧`run_5d8e…` JSON只证明原工程，不作为本LED变体的新测量报告。

CMSIS、ST设备头文件和HAL许可证保留在各自`license.txt`中；第三方内容不改为根MIT许可。
