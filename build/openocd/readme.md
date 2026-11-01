# OpenOCD 0.12.0 构建与交付边界

输入是仓库 src/third_party/openocd 中两份带许可证的原始源码包。build.py先校验SHA，再在新目录解压并构建静态libusb与OpenOCD，启用ST-Link/HLA；不下载源码、不安装到当前系统或Zynq、不执行上传ARM ELF、不调用SWD。

## ARM32 hard-float 交叉构建

在Linux或WSL中安装Python3.13、make、pkg-config及合法的arm-linux-gnueabihf GCC/binutils工具链和静态目标libc开发文件。编译器须自带可用目标sysroot。缺失工具／静态库时按日志补齐，不把PC库拿来替代。

在仓库根目录运行：

```sh
python3.13 -B build/openocd/build.py --output build/openocd/work-arm --host arm-linux-gnueabihf --jobs 2
```

输出目录必须不存在。所有构建和安装限于该目录；出错保留build.log以便排查，不清理已有工作。产物在 `package/sd/tools/openocd/`，包含bin/openocd及share/openocd/scripts。build_result.json记录新SHA、编译目标和ELF架构；脚本要求ARM32 hard-float和无动态解释器／动态段，安装的stlink.cfg、stm32g4x.cfg必须与源码一致。

libtool的`-static`不保证所有系统库静态链接，链接阶段另加`-all-static`，并解析最终ELF检查，失败则不宣布构建完成。新产物不保证与上传ELF字节一致。交叉构建与Zynq运行仍需部署者实际验收；构建脚本不自动复制或替换板端工具。

`-all-static`通过AM_LDFLAGS传给libtool链接阶段，避免Jim Tcl直接调用gcc时收到不支持的libtool专用选项。本机链接仍有glibc关于NSS／getpwuid／域名解析的警告；无动态ELF段不等于所有运行路径无外部依赖，目标系统兼容性必须实测。

## PC本地构建验证

Linux安装本机gcc、binutils、make、pkg-config及静态libc开发文件后可运行：

```sh
python3.13 -B build/openocd/build.py --native --output build/openocd/work-native --jobs 2
```

这会使用同一构建步骤生成PC架构ELF，只执行新编译程序的`--version`进行软件检查。**该ELF不能安装到Zynq。** 它不验证ARM ABI、USB ST-Link、SWD或烧录。发布检查与实际执行范围见 ../../data/test_summary.md。

安装新ARM产物前保留原工具，核对架构和SHA，再由部署者放入/sd/tools/openocd。按board/zynq说明做文件检查、已有deployment-check与独立real-flash验收，保留新证据；不能借用历史报告证明新工具通过。
