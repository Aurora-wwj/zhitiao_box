# v0.4 部署、PL 观测与真实 Agent 联调

> 本文保留 v0.4 历史状态。当前 UART、语义审批和 PC 窗口使用 [v0.5 手册](integration-v0.5.md)。

更新日期：2026-10-28（退出清理修复与联调优先级对齐）。本文替代日常使用中的 v0.3 部署步骤；[v0.3 手册](integration-v0.3.md) 保留历史上下文。

## 1. 本轮状态与验收边界

硬件队友在 v0.4 PDF 中报告：`RealBackend.build_firmware()`、`flash_firmware()`、`run_hardware_test()` 已完成真实硬件验证，SSH key 非交互认证已工作。PL 实测约 601 ms 时，1000±50 ms 返回 success=true、passed=false，600±50 ms 返回 success=true、passed=true。

本次将联调用 PL reader 收入正式模块，并补上后端配置绑定、PA1 目标身份、浏览器界面、部署向导、PL 内部准备和持久化报告。云端测试使用 mock，不连接 Windows Keil、Zynq 或 STM32；本次新版仍需在同一部署 PC 回归。`read_target_log()` 的真实 UART 数据源尚待硬件队友提供。

用户已确认真实 NiceCode 模型＋模拟硬件链路正常。下一步优先验收顶层 Agent 的 PL-only 真机闭环：真实 FAIL→AI 分析和源码修改审批→rebuild/flash→真实 PASS。免密 SSH 当前可用；公钥与 PL 配置的断电后持久化/自动恢复属于低优先级后续增强，不作为本轮运行中系统联调的前置条件。

## 2. 部署准备

真实硬件命令在安装 Keil、保存 STM32 工程并连接 Zynq 的 Windows PC 上执行。AI 开发电脑可以先运行测试和 `agent-demo`，无需 Keil 或开发板。

当前团队已验证的部署事实：

| 项目 | v0.4 实测值 |
| --- | --- |
| 实测 GPIO | `PA1`，已接线至 PL 观测通道 |
| STM32 工程 | `E:\Project\GPIO_PL_Test` |
| Keil 工程文件 | `MDK-ARM/GPIO_PL_Test.uvprojx` |
| Target | `GPIO_PL_Test` |
| HEX | `MDK-ARM/GPIO_PL_Test/GPIO_PL_Test.hex` |
| Zynq SSH | `root@192.168.10.2:22` |
| PC 网口 | `192.168.10.1/24` |
| 项目 SSH key 名 | `id_zhidiao_rsa` |
| Zynq root HOME | `/home/root`，不是 `/root` |
| 非交互 PATH | `/usr/bin:/bin` |
| devmem | 推荐绝对命令 `/bin/busybox devmem` |
| OpenOCD | `/sd/tools/openocd/bin/openocd` |
| scripts | `/sd/tools/openocd/share/openocd/scripts` |
| interface / target | `interface/stlink.cfg` / `target/stm32g4x.cfg` |

实际本机盘符、用户名、Keil 安装目录和工程路径必须自行核对。程序不改网卡、不安装密钥、不修改 Zynq 启动镜像。

在仓库根目录打开 PowerShell：

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
py -3.13 -B -c "import zhidiao_agent; print('模块加载成功')"
py -3.13 -B -m unittest discover -s tests -v
```

新终端需要重新设置 PYTHONPATH 和 NiceCode 环境变量。看到 `No module named zhidiao_agent` 时先核对工程目录和模块路径；此时还没有发出 API 请求。

## 3. Deployment Profile

复制仓库中的 [deployment.example.json](../deployment.example.json) 为本地 `deployment.local.json`。该本地文件在 `.gitignore` 中；保留自己的现有配置，按需加入 `observer`，不要直接覆盖。

配置集中管理：允许的工程根目录、Keil 路径/工程/target、SSH host/port/user、identity_file、known_hosts、旧版 RSA/SCP 兼容和 PL observer。API Key、私钥正文、SSH 密码均不属于此 JSON。

`known_hosts` 必须是已通过可信渠道核对的主机公钥文件。SSH 使用 BatchMode=yes、StrictHostKeyChecking=yes；不自动接受未知主机、不请求密码、不关闭 TLS/主机校验。旧版 Dropbear 所需的 ssh-rsa 兼容仅对本次调用生效，不修改全局 SSH 配置。密钥路径中的 Windows 用户目录按本人环境填写。

Observer 示例片段：

```json
{
  "observer": {
    "observed_gpio": "PA1",
    "pl_clock_hz": 100000000,
    "period_addr": "0x43C30000",
    "high_addr": "0x43C30008",
    "edge_addr": "0x43C40000",
    "valid_addr": "0x43C40008",
    "busybox_path": "/bin/busybox",
    "prog_done_path": "/sys/class/xdevcfg/xdevcfg/device/prog_done",
    "bitstream": null,
    "bitstream_sha256": null,
    "prepare_policy": "check_only",
    "bitstream_device": "/dev/xdevcfg",
    "min_new_edges": 2,
    "poll_interval_s": 0.05,
    "timeout_s": 15
  }
}
```

这里只展示新增片段，完整 JSON 还需已有的 allowed_roots、Keil 和 SSH 配置。`prog_done_path` 是可配置的默认候选路径，PDF 没有证明该路径在当前板端存在，联调前应由队友确认后填写。采样窗口要覆盖至少两个新边沿；目标周期很长时相应调整 timeout_s。

在 Python 中，`DeploymentConfig.observer` 使用 `PLObserverConfig`；JSON load 会将 observer 对象转换成该类型。`observed_gpio` 表示真实接线的 STM32 引脚，当前实测为 PA1。用户明确指定其他引脚时会在请求模型前拒绝；模型 ready 目标也必须回传同一个引脚。该字段描述物理事实，不能通过改字符串来改变实际接线。`RealBackend(config)` 会为配置了 observer 的部署自动接入 `ObservationBackend(period_reader=PLPeriodReader(...))`。显式传入 observations 仍支持队友的可信自定义 reader。

## 4. PL 生命周期：明确选择检查或加载

当前已知工作镜像文件名为 `zhidiao_measure_v3.bit`，SHA-256：

```text
8541e1b522f8fe91b87837efd18863c8862a13ecca2d16385ae143114bf08bf3
```

队友已通过 `/dev/xdevcfg` 运行时加载并测量成功；尚未证明镜像会随 Zynq 重启自动恢复。现有配置默认 `prepare_policy="check_only"`：只检查 prog_done 和已配置的 SD 文件摘要，由部署方先准备好正确镜像。

需要由工作流恢复 PL 时，可以在可信本地 profile 中选择：

```json
{
  "prepare_policy": "load_verified",
  "bitstream": "/sd/pl/zhidiao_measure_v3.bit",
  "bitstream_sha256": "8541e1b522f8fe91b87837efd18863c8862a13ecca2d16385ae143114bf08bf3",
  "bitstream_device": "/dev/xdevcfg"
}
```

上面是 observer 内的片段。`/sd/pl/...` 是需要队友确认的存放路径示例。加载模式要求配置镜像路径与摘要，镜像必须为 SD 部署根目录内的 .bit 文件，写入设备限定为 `/dev/xdevcfg`。

审批预览会明确展示“校验这个镜像、替换当前 FPGA 配置、重置观测子系统”的效果。批准真实观测或整轮验证后，Backend 仅在该授权内派生一次内部准备授权：读取镜像 SHA → 一致后加载 → 要求 prog_done=1 → 再执行 UART/PL。每个批准轮次准备一次，不会在 UART 和 PL 两次观测之间重新加载；没有审批时不能加载。四个公共工具签名保持不变，不增加第五个 load_fpga 工具。

加载 helper 使用 BusyBox 的 `sha256sum`、`timeout -s KILL`、`date`、`cat`、`sh` 和 `sleep`。PC 命令预算、板端 loader timeout 和有限轮询共同限制操作；当前板端 BusyBox 的实际选项支持仍需回归，不支持时明确失败。

`check_only` 下的 SD 文件 SHA 只能证明文件完整性，prog_done 只证明配置完成；两者都不能证明当前运行镜像就是该文件。`load_verified` 会实际加载这次批准的文件，但 prog_done 也不是镜像身份的硬件认证。

这种运行时准备可以作为 PDF 的 Deployment 方案 B，在 SSH 可用后恢复 PL。程序不改 BOOT.BIN、image.ub 或系统启动脚本；RAM rootfs 的 authorized_keys 恢复仍须由硬件部署方接入启动流程并冷启动验证。

## 5. 正式 PL reader 与 freshness

`tools/pl_observer.py` 的 `PLPeriodReader` 用一次 SSH 在板端运行只读采集脚本，减少多个 ssh.exe 的启动开销。寄存器与时钟均从 Deployment Profile 获取，LLM 无需知道地址。

测量顺序：记录 edge_start → 等待相对起点至少两个新边沿 → valid=1 → 读取 period/high → 检查采样期间边沿计数稳定 → 返回经过校验的快照。

计数器采用 32 位回绕计算。valid=0、边沿不变、旧周期、period_ticks=0、异常高电平长度、畸形输出、SSH 失败或超时均不作为有效测量。结果保留 tick、edge、freshness 等证据供审计，不把固定值或 STM32 自报值伪装为 PL 实测。

软件检查只能利用现有寄存器协议；未提供硬件锁存快照协议。稳定计数前后检查能减少不一致，不能替代未来硬件层更强的原子快照保证。

## 6. 四接口独立验收

以下示例均从仓库根目录运行。先用 `--preview-only` 核对配置；去掉该参数后还需在终端明确批准才执行。

```powershell
py -3.13 -B -m zhidiao_agent real-build "E:\Project\GPIO_PL_Test" --config deployment.local.json --preview-only
py -3.13 -B -m zhidiao_agent real-flash "E:\Project\GPIO_PL_Test\MDK-ARM\GPIO_PL_Test\GPIO_PL_Test.hex" --config deployment.local.json --preview-only
py -3.13 -B -m zhidiao_agent real-test --config deployment.local.json --expected-period-ms 1000 --tolerance-ms 50 --preview-only
py -3.13 -B -m zhidiao_agent real-log --config deployment.local.json --duration-s 5 --preview-only
```

- build：核对 target、真实 HEX 位置、源码摘要、Keil rebuild 及日志；0 Error(s) 和新鲜有效 HEX 才成功。
- flash：本地 HEX 摘要 → SCP → 远端大小及 SHA-256 → 一致后 OpenOCD；正常退出并确认 Programming Finished、Verified OK、Resetting Target 才 verified=true。
- test：PL 测量工具成功与 passed 分离。约 601 ms 对 1000±50 ms 应 success=true、passed=false；对 600±50 ms 应 passed=true。
- log：当前没有真实 UART reader 时明确 BACKEND_UNAVAILABLE。预留调试入口不代表第四个接口已经硬件完成，不会生成假日志。

每个入口展示语义计划，内部 fingerprint 仍与精确参数绑定。输入“批准”、`approve`、`y` 或 `yes` 批准；`diff` / `d` / “查看差异”重新展示；其他输入取消。前后空白会被去除，用户无需复制 64 位摘要。非交互 stdin 不授权，程序没有 --yes。

## 7. 自然语言 Agent 与真实闭环

先在同一终端按 [README](../readme.md) 安全设置 NICECODE_API_KEY、NICECODE_BASE_URL 和当前可用的 NICECODE_MODEL。已配置的密钥无需再次输入，也不要输出变量值。

```powershell
py -3.13 -B -m zhidiao_agent agent-run "把 STM32 PA1 的完整周期调到 1000 ms，误差不超过 50 ms。" --project "E:\Project\GPIO_PL_Test" --source Core/Src/main.c --config deployment.local.json --protocol openai-responses --allow-network --pl-only --max-attempts 3 --timeout-s 300
```

源文件路径以本地工程为准，重复 `--source` 可选择多个文件。白名单以外的文件不会作为模型源码上下文或允许编辑文件。当前只支持已有 UTF-8 文件；GBK 工程需先单独设计编码策略。

交互过程：

1. 检查本地工程/部署和允许的源码，展示模型发送范围，由用户同意后才请求模型。
2. 将自然语言解析为部署所观测引脚（当前 PA1）的 **完整周期**与误差范围；信息不足时继续回答澄清问题，最多补充三轮。显示引脚和数值请用户确认，模型不能改观测引脚、最大轮次或部署参数。
3. 展示本轮构建、上传、烧录、观测计划并等待批准。第一轮先建立当前工程的真实基线。
4. 按确定顺序执行该轮，收集真实证据；若已满足数值目标，停止并报告 PASS。
5. 编译失败或目标不达标时，将证据与白名单源码交给 Agent，展示修改原因和完整 diff，等待人工批准。
6. 批准且 before_sha256 仍匹配后写入；新一轮必须再次审阅执行计划，再重新 build/flash/observe。
7. 达到最多轮次、总预算、拒绝、异常或停止条件时终止，不自动重复烧录同一份失败源码。总预算从流程开始计算，包含目标解析、澄清和等待人工确认。

`--pl-only` 是 UART 尚未完成时的显式降级选择：报告注明跳过 UART，PASS 只覆盖 PL GPIO 周期。省略该参数即要求 UART；未接好时停止。不能把缺失 UART 包装成空日志成功。

已有真实 UART reader 时可以从 Python 注入 `ObservationBackend(uart_reader=..., period_reader=...)`；CLI 的板端 UART 实现需等待正式访问契约后接入。

## 8. 审批、故障和后续

一个 RealBackend 只属于初始部署配置。更换 host、认证、observer 或原生 reader 的 transport 后，旧后端会拒绝预览和执行；应新建后端并重新审批，避免“烧录新板、测量旧板”。

整轮批准绑定工程、受追踪输入的源码摘要、部署配置、PA1 目标、观测选择和预算；Controller 仅在此授权内派生本轮 build/flash 的子授权。新编译的 artifact 必须符合批准的项目和摘要；配置、源码或固件变化使批准失效。每轮、每次源码修改均单次有效，模型不能调用批准方法。

流程保留 `RealBackend.requires_approval=True`。超时在工具阶段内传递剩余预算，结束后不再调用下一工具；SSH 断开或 PC 杀进程不能保证板端 OpenOCD 同时结束，需在部署 PC 检查残留状态后再决定下一次操作，不自动重试。

## 9. 首次部署配置与只读诊断

已有本地配置时保留原文件。要生成新配置，在部署 PC 执行下面的预览，按自己的用户名和安装目录修改参数：

```powershell
py -3.13 -B -m zhidiao_agent deployment-setup --project "E:\Project\GPIO_PL_Test" --keil "D:\Keil_v5\UV4\UV4.exe" --project-file "MDK-ARM/GPIO_PL_Test.uvprojx" --target GPIO_PL_Test --known-hosts "C:\Users\YOUR_USER\.ssh\known_hosts" --identity "C:\Users\YOUR_USER\.ssh\id_zhidiao_rsa" --observed-gpio PA1 --output deployment.local.json --preview-only
```

移除 `--preview-only` 后，界面展示生成的完整 JSON、文件效果和检查项，人工批准后才写入；输出必须不存在，避免覆盖用户配置。可增加 `--check-remote`，将本次只读 SSH 诊断也纳入同一审批。远端传输失败时不写配置；诊断本身存在 FAIL/UNKNOWN 时可以保存有效配置，但结果为 NOT_READY/INCOMPLETE，不能当成已部署可用。未检查远端时结果为 CONFIGURED_NOT_VERIFIED。

本地检查 Python、Keil、工程 target、ssh/scp 和指定身份文件是否存在。known_hosts 文件存在不等于主机公钥已经核实，仍由部署者通过可信渠道确认。工具不读取或上传私钥正文，不安装公钥、不修改网卡或启动文件。

已有 profile 的独立诊断：

```powershell
py -3.13 -B -m zhidiao_agent deployment-check --config deployment.local.json --preview-only
```

移除预览参数并批准后，检查实际 `$HOME`、authorized_keys 是否存在、OpenOCD/scripts、ST-Link USB 候选设备、BusyBox、prog_done 和寄存器访问。缺少 lsusb 等条件报告 UNKNOWN；这些只读检查不证明 SWD 正常、bitstream 身份正确或本轮 freshness 合格，仍需 real-build/flash/test 验收。

## 10. 浏览器操作界面

```powershell
py -3.13 -B -m zhidiao_agent serve --project "E:\Project\GPIO_PL_Test" --source Core/Src/main.c --config deployment.local.json --protocol openai-responses --allow-network --pl-only --max-attempts 3 --timeout-s 300 --port 8765
```

浏览器打开 `http://127.0.0.1:8765`。界面展示固定工程、源码白名单和观测引脚；勾选发送同意、输入目标，必要时回答澄清，再确认目标。每轮构建/烧录/观测和每次源码差异分别点击批准。可以取消、查看理由/完整 diff/测量、查看历史及下载 JSON 报告。

服务仅在本机监听，POST 校验 Host、Origin、CSRF 和输入大小，不从网页接受任意工程路径，也不加载外部页面资源。浏览器界面属于当前 PC 用户的可信人机界面，不是多用户部署服务。

点击停止会向本地命令 runner 发出取消信号，尝试终止其进程树并阻止后续步骤；原生模型请求保留配置的 I/O timeout，返回后不再推进。终端 Ctrl+C 关闭服务时拒绝新操作，等待后台清理和已有运行报告保存后退出；保存失败会返回明确错误。已有 PASS/FAIL 证据不会因关闭服务被改写。自定义模型/reader 回调必须遵守截止时间，否则关闭也可能等待其返回。

终止本地 SSH 不证明板端 OpenOCD 或 FPGA 加载已停止，可能中断时报告继续保留 hardware_state_uncertain。关闭浏览器窗口不会停止服务；请用界面停止或在启动终端按 Ctrl+C，并等终端完成清理。

## 11. 持久化报告和恢复

默认报告目录为启动命令所在目录 `.zhidiao/runs`，可用 `--report-dir` 修改。报告原子保存并记录 run_id、引脚、目标、源码/固件摘要、工具结果、模型决策、待审与已完成状态。该目录在 Git 忽略列表中；位于 STM32 工程内的自定义报告目录必须放在 `.zhidiao` 下，避免报告写入改变源码摘要。

报告中的 hardware_state_uncertain=true 表示中断后远端烧录或 FPGA 加载状态需要人工确认。POSIX 请求文件权限 0600；Windows 使用本地目录 ACL。

```powershell
py -3.13 -B -m zhidiao_agent report ".zhidiao/runs/run_EXAMPLE.json"
```

上面的 run_EXAMPLE 为占位符，替换为真实报告文件名。重新运行相同任务时可加 `--resume-report <实际报告路径>`：恢复前重新核对工程、配置、目标、源码和白名单；保留已用次数和已消耗的时间预算（包括检查点后的停机时间），创建新 run_id 并关联 parent_run_id。所有批准重新取得，JSON 中的旧 fingerprint 不会变成新的执行许可。报告保存失败时停止推进，不在缺失审计记录的情况下继续下一操作。

只允许从安全检查点继续。标记为执行中、写源码中或已经终态的记录只能查看，不能自动重放；中断的硬件操作必须人工确认板端状态。省略 agent-run 的 task 参数并提供 --resume-report 时，使用报告中的原任务；显式提供不同任务会拒绝恢复，应开启新 run。图形界面也可查看历史并申请从允许的检查点恢复，仍需再次同意源码发送、确认目标和重新审批操作。

## 12. 仍需硬件侧完成的验收

- UART RX/FIFO/AXI/Linux 真实 reader，以及时间戳、编码、overflow/truncated 和超时约定。
- 新正式 reader、配置身份防护、PA1 绑定和 real Agent 在部署 PC 的回归，包括停振、拔线、SSH 超时、拒绝审批及真实 FAIL→修改→PASS。
- 原生 BusyBox 的观测和加载选项兼容性，真实 `/dev/xdevcfg` 加载与 prog_done 路径。
- RAM rootfs 中 authorized_keys 的重启恢复，选择启动镜像方案时的 measurement-v3 开机集成，以及冷启动验收。
- GBK、多文件编辑事务、复杂外部工程依赖和 GPIO 周期之外的明确目标契约。

部署持久化属于 Deployment 层。不能通过写死 root 密码、关闭主机校验、把 requires_approval 改成 false 或增加任意 shell 工具解决。
