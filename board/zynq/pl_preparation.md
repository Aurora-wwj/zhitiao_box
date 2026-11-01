# PL加载／检查复用现有审批路径

最终v5位流在build/fpga，板端约定 `/sd/pl/zhidiao_observe_v5_led.bit`，SHA为fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6。由部署者上传到该路径并核对SHA；本次未连接板卡、复制文件或修改开机流程。

## 当前部署：初始化阶段加载v5

当前v5 PL在初始化阶段加载完成，再启动Agent及LED；Agent沿用`observer.prepare_policy=check_only`，保持原有build／flash／UART／PL四接口执行顺序。启动前由部署者确认初始化加载已完成，LED开始工作时相应寄存器已存在。

在部署PC的PowerShell中，按现有板端初始化流程准备v5，并使用以下命令核对SD中的位流文件：

```powershell
ssh `
  -o BatchMode=yes `
  -o StrictHostKeyChecking=yes `
  -o "UserKnownHostsFile=$HOME\.ssh\known_hosts" `
  -o HostKeyAlgorithms=+ssh-rsa `
  -o PubkeyAcceptedAlgorithms=+ssh-rsa `
  -i "$HOME\.ssh\id_zhidiao_rsa" `
  root@192.168.10.2 `
  "sha256sum /sd/pl/zhidiao_observe_v5_led.bit"
```

预期SHA-256为`fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6`。该命令只校验文件，不执行PL加载，也不单独证明正在运行的PL镜像身份；初始化加载完成需另行确认。

现有独立Agent目录的路径变量设置为：

```powershell
$env:PYTHONPATH = "E:\zhidiao-agent\src"
```

该绝对路径对应现有独立Agent目录。本GitHub仓库采用`src/agent/src`布局，进入仓库的`src/agent`目录时，使用下面原有的`(Resolve-Path .\src).Path`设置。路径须与实际代码位置一致，私人密钥和本机配置不上传。

初始化阶段预加载不表示已完成断电后的自动加载／SSH公钥持久化验收；冷启动恢复边界仍保留。

## 现有受审批加载／检查能力

正式加载与检查脚本已经存在于 `src/agent/src/zhidiao_agent/tools/pl_prepare.py`：PLPreparation按照部署配置生成固定SSH脚本，在Controller批准的工具计划内调用，不是第五个公开硬件工具。UART／PL采集脚本分别在同目录pl_uart.py、pl_observer.py及remote.py生成，不需要再往SD卡放一套Python Agent。

部署者在src/agent目录建立自己的deployment.local.json：

1. 使用deployment.example.json中的v5路径、SHA、寄存器和UART配置。
2. 默认observer.prepare_policy=`check_only`，只查文件SHA与prog_done，**不能证明当前运行的镜像就是该文件**。
3. `load_verified`作为现有可选能力保留：目标Linux需已确认支持可写字符设备`/dev/xdevcfg`和配置中的prog_done路径。程序会检查已批准镜像SHA、在timeout内加载并等待prog_done；这会重置PL，必须在原有工具审批中确认。当前初始化预加载部署使用`check_only`；启用LED时仍须在启动Agent前确认v5已加载。新Linux若仅支持FPGA manager，当前加载器不适用，不能猜测替代节点。

先预览现有工具计划，再按提示批准执行：

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
py -3.13 -B -m zhidiao_agent real-test --config deployment.local.json --expected-period-ms 1000 --tolerance-ms 50 --preview-only
```

确认计划中的加载行为、范围和预算后，去掉--preview-only由CLI收集审批。这里会执行真实PL测试，不只是加载。不得伪造审批、复用历史fingerprint，或在模型输入中加入任意devmem／shell。

只读文件检查入口是check_files.sh；实际远程准备、USB、寄存器可读性检查沿用deployment-check。文件／prog_done检查、镜像加载完成与DUT物理PASS是不同证据。UART FIFO reset和MMIO读取仍只由现有受控工具执行。
