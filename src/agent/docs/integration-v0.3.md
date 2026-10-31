# v0.3 真实编译与烧录接线

> 本文保留 v0.3 阶段记录。当前真实接口状态、部署参数和用户入口以 [v0.4 手册](integration-v0.4.md) 为准。

更新：2026-10-26（补充远端 SHA-256 校验及认证状态澄清）。公共硬件返回契约继续为 **0.2**；v0.3 是联调部署说明版本，不是一次返回格式升级。

本轮新增 `DeploymentConfig`、可注入命令执行器，以及真实 Keil/SSH/SCP 实现。原四个工具接口、`OperationResult` 和默认 mock CLI 保持兼容。

后续软件扩展已增加 Orchestrator、人工批准的源码编辑和 UART/PL 数据适配层，见 [软件模拟闭环说明](orchestrator.md)。本手册中的部署验收和真实流程限制仍然适用；默认真实 UART/PL 访问尚未绑定。

## 1. 已实现与尚未验收

| 部分 | 本轮状态 |
| --- | --- |
| `build_firmware()` | 实现 Keil 工程/target/output 解析、rebuild、日志检查、有效且刷新的 HEX 检查 |
| `flash_firmware()` | 实现远端工具检查、独立运行目录、SCP 上传、远端大小及 SHA-256 比对、OpenOCD program/verify/reset 结果检查 |
| 人工审批 | 每次真实编译/烧录先预览，输入完整操作摘要确认后执行；一次有效，输入变化须重审 |
| 超时 | 编译进程限时；烧录的各阶段共用一次总时间预算；超时终止已启动的本地进程组/树 |
| 认证 | SSH key 或 SSH agent，`BatchMode=yes` 禁止交互式密码；严格校验已核实的主机密钥 |
| UART / PL | 仍返回 `BACKEND_UNAVAILABLE`，等待 PL UART RX/FIFO/AXI 和 PL 测量接口 |
| Controller 真实自动流程 | 继续被 `requires_approval=True` 阻止，不开放全流程自动执行 |
| AI decision/edit loop | 已有人工审批的软件模拟闭环，真实硬件闭环仍待接入 |

**验证范围**：后端测试通过注入的 runner 模拟 Keil、SSH、SCP 和 OpenOCD；执行器另有真实 Python 子进程的退出码、输出限制和超时测试。云端没有 Windows Keil 和开发板，不能将测试通过表述为新版封装已完成实机验收。团队提供的 PDF 说明底层工具链已实测，但新封装仍须在部署 PC 回归。

2026-10-25 基线通过 94 项测试。2026-10-26 的 SHA-256 更新在 Linux / Python 3.13.5 上通过全部 **100 项测试**，包括匹配、同大小不同摘要、非法输出、计算失败及超时分支。mock CLI 和离线示例均已验证返回 PASS；此前另用本机 `ssh -G` 验证带空格的 known_hosts 配置解析，不建立连接。Windows 执行结果以新提交对应的 CI 或部署 PC 回归为准。

## 2. 部署前提

1. 在真正连接开发板的 Windows PC 上运行，使用 Python 3.13+。
2. Keil 已安装、授权和人工验证，可编译指定工程。只使用可信工程：工程构建钩子和编译器自身能执行其他程序，路径白名单不是操作系统沙箱。
3. PC Ethernet 为 `192.168.10.1/24`，Zynq 为 `192.168.10.2/24`，板端 SSH 端口 22，用户 root；参数均可配置。
4. 本机 `ssh`、`scp` 能从 PATH 找到。默认 `scp -O` 需要支持该选项的现代 OpenSSH 客户端，以兼容不提供 SFTP 的旧 Dropbear。
5. **先独立配置 SSH key/agent 登录**。队友最新解释确认：实机当前仍由人手动输入密码；v0.3 的“非交互认证”是最终要求，不是已经配置完成的实测结论。当前后端支持 key/agent 并拒绝密码提示，但不会自动给开发板配置公钥；该部署工作仍需完成并验证。加密私钥需要预先加载到本机 SSH agent。认证自动完成后，烧录前的人工审批仍保留。
6. 与硬件负责人通过可信渠道核实 Zynq 主机公钥指纹，放入指定 `known_hosts` 文件。不能直接信任未核对的扫描结果，不能关闭主机密钥校验。SSH 端口变更时 known_hosts 条目也需对应。
7. `/sd/firmware` 已存在，OpenOCD 及完整 scripts 已部署，板端 PATH 中可用 `sha256sum`（GNU 或 BusyBox 实现）。预检查发现缺失时返回 `UPLOAD_FAILED`，不会降级为只检查大小。程序只在固件目录创建独立 run_id 子目录，不修改 `BOOT.BIN`、`image.ub`。

`allow_legacy_rsa=true` 只对这次 SSH/SCP 调用启用旧服务器所需的 RSA 主机密钥和 RSA 公钥签名兼容，不改全局 SSH 配置；可信新服务器可设为 false。

## 3. 配置文件

将仓库 `deployment.example.json` 复制为被 Git 忽略的 `deployment.local.json`，按实际机器编辑。

关键字段：

| 字段 | 用途 |
| --- | --- |
| `allowed_roots` | 本机允许访问的工程/固件根目录，必须使用当前系统绝对路径 |
| `keil_executable` | 例如 `D:\Keil_v5\UV4\UV4.exe` |
| `project_file` | 相对传入工程目录的 `.uvprojx` 路径；省略时目录内必须只有一个工程 |
| `target` | Keil target 名；省略时工程必须只有一个 target |
| `known_hosts` | 已核实主机密钥文件的绝对路径，必需 |
| `identity_file` | 私钥路径，可为 null 使用默认 key/agent；不读取或打印私钥内容 |
| `build_timeout_s` / `flash_timeout_s` | 单次编译/烧录的时间预算，分别在 0–1800 秒之间，不含 0 |
| `host` / `port` / `user` | Zynq 连接参数 |
| `mount_root` | 默认 `/sd`，其余固定路径由 `BoardPaths` 派生 |

配置文件不包含密码、API Key 或私钥正文。Windows 路径在 JSON 中需要转义反斜线；示例已提供正确写法。

## 4. 先预览，再单项执行

在 PowerShell 项目根目录运行：

```powershell
$env:PYTHONPATH = "src"

# 只读取本机配置及工程信息，生成计划，不调用 Keil、不连接 Zynq。
py -3.13 -B -m zhidiao_agent real-build "E:\Project\GPIO1" --config deployment.local.json --preview-only

# 展示相同类型的计划，然后在当前进程中等待人工输入 APPROVE <完整 fingerprint>。
py -3.13 -B -m zhidiao_agent real-build "E:\Project\GPIO1" --config deployment.local.json
```

编译返回真实的 `artifact_path`，不再拼接 mock 专用的 `Objects/firmware.hex`。Keil XML 中的输出配置是产物位置依据。必须启用 `CreateHexFile`；拒绝多工程/多 target 歧义、目录外产物、缺失、无效或未刷新的 HEX。0 个 error、18 个 warning 不被单独判作失败；综合检查退出状态、日志及产物。

```powershell
# 使用上一步返回的真实 artifact_path，以下只是 PDF 的示例路径。
py -3.13 -B -m zhidiao_agent real-flash "E:\Project\GPIO1\MDK-ARM\GPIO1\GPIO1.hex" --config deployment.local.json --preview-only

# 人工确认此操作会上传并 program/verify/reset STM32，输入提示中的批准文本后才执行。
py -3.13 -B -m zhidiao_agent real-flash "E:\Project\GPIO1\MDK-ARM\GPIO1\GPIO1.hex" --config deployment.local.json
```

`--preview-only` 不保留跨进程批准；正式执行命令会重新生成运行编号和预览。没有 `--yes` 开关，重定向 stdin 不会自动批准；取消或输入错误均不执行命令。

预览只产生内存状态，不创建远端目录或构建日志。摘要绑定源码/工程输入或固件内容和完整操作参数；批准只在当前进程可用，使用一次即失效。

## 5. 执行与故障语义

- 编译使用参数数组调用 Keil，不通过本地 shell 拼接。输出日志按本轮唯一文件读取，支持 UTF-8/GB18030；返回日志经过脱敏并限长。
- 编译源码摘要覆盖工程目录内常见 C/C++/汇编/链接/Keil 配置输入，不是对编译器、系统库或工程目录外所有依赖的隔离；只运行可信部署工程。
- HEX 检查格式、记录长度、校验和、结束记录和有效数据，拒绝陈旧固件。Keil 自动构建后旧 HEX 未刷新不算成功。
- 烧录依次执行远端工具检查/创建 run_id 目录、SCP 上传、远端文件存在及字节数检查、远端 SHA-256 计算比对、OpenOCD。
- 远端使用 `sha256sum < /sd/firmware/<run_id>/firmware.hex` 从标准输入计算摘要，解析 GNU/BusyBox 的 `摘要  -` 输出；只有摘要与批准时绑定的本地固件 SHA-256 一致才继续。
- 上传、大小检查、远端计算失败、输出格式非法或摘要不一致时，返回 `UPLOAD_FAILED`，不执行 OpenOCD。SSH 连接故障及超时仍分别返回 `SSH_CONNECT_FAILED`、`TIMEOUT`，同样停止。不会回退到只检查文件大小。
- 返回中的 `artifact_sha256` 是批准的本地固件摘要；成功解析后记录 `remote_sha256`；`upload_verified=true` 只表示两端摘要一致。`verified=true` 仍专指 OpenOCD 编程、校验和复位成功，不能被上传校验替代。
- 只有进程正常退出，且输出有 `Programming Finished`、`Verified OK`、`Resetting Target`，才设置 `verified=true`；单独的降速提示不判错。
- 烧录失败返回 `verified=false` 和已取得的脱敏日志；没有自动重试。失败的远端目录保留以供人工诊断，未实现清理策略。
- 可能的错误：`CONFIGURATION_ERROR`、`APPROVAL_REQUIRED`、`APPROVAL_REJECTED`、`PROJECT_NOT_FOUND`、`BUILD_FAILED`、`ARTIFACT_NOT_FOUND`、`TIMEOUT`、`CANCELLED`、`SSH_CONNECT_FAILED`、`UPLOAD_FAILED`、`FLASH_PROGRAM_FAILED`、`FLASH_VERIFY_FAILED`、`TARGET_RESET_FAILED`。
- 超时会终止本机子进程/SSH 连接，**不保证远端 OpenOCD 被立即终止**。超时后需人工确认板端状态，禁止自动重复烧录。

## 6. Orchestrator 的最终分层（待实现的 decision/edit loop）

```text
用户目标（GPIO 完整周期 1000 ms，误差 ±50 ms）
  → Orchestrator：理解目标，分析每轮真实证据，提出下一步和源码 diff
  → Controller / safety boundary：路径、顺序、时间预算、次数、审批、停止条件
  → HardwareBackend：build → flash/verify → read log → hardware test
  → 把证据交回 Orchestrator
  → 若物理测试不通过：AI 分析 → 展示 diff → 人工批准 → 应用修改 → 新一轮
  → PASS / 次数上限 / 拒绝或取消 / 故障停止
```

LLM 的“通过”判断不能覆盖确定性门槛：编译失败不烧录，未校验不测试；`success` 表示工具工作正常，`passed` 表示物理行为达标。AI 必须引用每轮工具及物理测量证据，不能把 mock 或 UART 自报当作 FPGA 实测。

现有 `Controller.run()` 保持原有模拟流程，`max_attempts` 只是重复同一工程的流程，不是 AI 修复次数。新增 Orchestrator 使用 `Controller.run_once()`，失败后由模型提出 diff，人工批准写入后才执行下一轮；该能力目前用于模拟后端。没有通过修改 `requires_approval` 绕过真实操作审批。

后续上层应用应显式维护 run_id、轮次、目标、证据、结构化决策和待审补丁：一次轮次执行 → 证据分析 → 提出修改 → Controller 校验并人工批准 → 应用补丁 → 再执行一次轮次。达到上限前没有批准的有效修改时，不应无意义重复相同烧录。

真实完整闭环还需：PL UART/测量后端、Controller 的真实逐步状态及恢复机制、受控源码编辑器、AI 结构化决策适配、每轮持久化报告。本轮不宣称这些已经实现。

## 7. 部署 PC 回归顺序

1. 更新代码，先运行全部离线测试和 mock，不需要密钥、Keil 或开发板。
2. 编辑本地配置，预览真实编译；核对 Keil 路径、工程、target、产物、日志路径和时间预算。
3. 批准一次真实编译，确认 artifact_path 指向本轮生成的 HEX，保存返回结果。
4. 与硬件队友完成 key/agent 非交互登录及 known_hosts 指纹核对；预览烧录。
5. 在可复位/可烧录状态下批准一次烧录，检查日志及实际 MCU 行为，保存返回结果。
6. 不执行自动完整闭环；等待 PL 侧两个观测接口就绪后继续接入。

Windows 与 Ubuntu 的 CI 都运行这些离线测试；测试通过不需要真实凭据或板卡，也不替代上述实机步骤。
