# 按提交规范统一发布路径

依据上传AMD选题指南3.3.5.4，本次将原工程及第三方许可材料的发布路径统一为英文小写。指南示例明确使用的根`README.md`与`skill/README.md`保留，其余说明文件使用`readme.md`，根许可证使用`license`。扩展名使用点号，GitHub所需`.github`等隐藏目录保留。

## 工程入口及历史映射

| 迁移前 | 当前发布路径／状态 |
| --- | --- |
| src/stm32/gpio_pl_test/Core/Src/main.c | src/stm32/gpio_pl_test/core/src/main.c；文件原字节及黄金SHA不变 |
| src/stm32/gpio_pl_test/MDK-ARM/GPIO_PL_Test.uvprojx | src/stm32/gpio_pl_test/mdk-arm/gpio_pl_test.uvprojx；本地引用和输出名已同步 |
| MDK-ARM/GPIO_PL_Test/GPIO_PL_Test.hex | 新构建输出mdk-arm/gpio_pl_test/gpio_pl_test.hex；不是重新构建的历史HEX |
| Drivers／Core／MDK-ARM下的其他输入 | 分别迁移为drivers／core／mdk-arm，完整文件映射见../data/repository_path_map.json |
| 第三方AUTHORS／COPYING／LICENSES等展开材料 | 公开文件名小写，正文和版权声明逐字节不变；原始压缩包不重打包 |

内部Keil Target、Device、PackID和外部工具／SDK内的路径不属于仓库文件名，保持原设置。旧工程仅调整三份文件内容：Keil XML的本地源文件／include／输出路径，CubeMX工程名及MainLocation，以及HAL中Legacy头文件引用的大小写。其余源码，尤其黄金main.c与startup，保持字节不变。CubeMX再次生成可能恢复其默认目录大小写，重新发布前须再次检查。

## 现有部署如何同步

使用当前工程时，私人配置中的`project_file`改为`mdk-arm/gpio_pl_test.uvprojx`，可信启动窗口允许的源码改为`core/src/main.c`，重新预览并批准任务。两份公开部署示例已同步；不会自动重写本机配置或历史审批。若保留独立旧目录，启动器仍支持`Core/Src/main.c`；新目录优先使用小写路径。

根`build/stm32/build.ps1`默认构建原工程的新小写入口；LED版仍单独选择`src/stm32/gpio_pl_test_led`。两工程的Target同为`GPIO_PL_Test`，各自生成自己的HEX，不混用历史证据。Windows已存在的工作副本若没有正确体现仅大小写的改名，可在保留私人配置及未提交工作后另建干净克隆核对，不在脏工作区强制清理。

## 保持证据原貌

最终run_5d8e… JSON、完整diff、原PNG、黄金main.c、build/stm32/firmware.hex、v5位流及原FPGA实现报告未改字节。历史JSON继续记录当时的`Core/Src/main.c`；发布检查用外部路径映射找到当前文件，不修改JSON或把旧审批当作新任务授权。本次没有新的Keil／Vivado构建或板卡测量。

data/repository_path_map.json记录迁移基线提交、123份文件的旧／新路径和旧／新SHA，并列出需保持的历史证据。data/stm32_sha256.json校验当前发布文件；三份路径适配文件的新SHA不冒充旧输入SHA。OpenOCD清单中仅published_files.path改变，压缩包内source路径和文件SHA保留。

## 自动检查

根目录运行`python3.13 -B sim/check_release.py`，或单独运行`python3.13 -B sim/release_path_check.py`。有Git工作树时检查已跟踪及未忽略的新文件；干净发布归档中检查实际文件。新增大写／中文／空格路径、缺失迁移文件、改变的许可证和历史证据均会被拒绝。CI已加入该检查及test_release_paths.py回归。

回归还用GCC对两工程共42个C翻译单元做主机预处理，确认大小写敏感环境下头文件引用闭合；这不是ARM编译或Keil链接。Windows／Keil／Vivado及LED真机验收继续按release_status.md执行，不因文件命名完成而标记通过。
