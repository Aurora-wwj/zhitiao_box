# 板端初始化：路径变量、SSH公钥恢复与v5手动加载

最终v5位流在build/fpga，板端约定 `/sd/pl/zhidiao_observe_v5_led.bit`，SHA为fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6。由部署者上传到该路径并核对SHA；本次未连接板卡、复制文件或修改开机流程。

## 当前部署的初始化顺序

当前v5 PL在初始化阶段加载完成，再启动Agent及LED；Agent沿用`observer.prepare_policy=check_only`，保持原有build／flash／UART／PL四接口执行顺序。启动前由部署者确认初始化加载已完成，LED开始工作时相应寄存器已存在。

在部署PC的PowerShell中依次完成：设置路径变量 → 恢复并验证SSH公钥登录 → 校验并手动加载v5 → 启动Agent。以下板端命令由部署者手动执行，不加入模型工具或Agent自动流程。

## 1. 路径变量设置

现有独立Agent目录的路径变量设置为：

```powershell
$env:PYTHONPATH = "E:\zhidiao-agent\src"
```

该绝对路径对应现有独立Agent目录。本GitHub仓库采用`src/agent/src`布局；进入仓库的`src/agent`目录时使用：

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
```

路径须与实际代码位置一致；环境变量只对当前PowerShell会话生效。

## 2. SSH公钥恢复（三条命令）

前提是已通过可信板端控制台核对主机公钥指纹并建立本机known_hosts，PC上已有自己生成的`id_zhidiao_rsa`和`id_zhidiao_rsa.pub`。前两条使用密码方式连接，会按提示输入板端root密码；密码和私钥内容不写入仓库。命令中的单引号保持原样，使第一条的`$HOME`在板端展开。

第一条：检查板端HOME、SSH目录与authorized_keys状态。

```powershell
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAuthentication=no root@192.168.10.2 'echo HOME=$HOME; ls -ld /home/root/.ssh 2>/dev/null; ls -l /home/root/.ssh/authorized_keys 2>/dev/null || echo AUTHORIZED_KEYS_MISSING'
```

第二条：将PC上的公钥写入板端，并恢复目录权限及归属。此命令按当前单公钥部署覆盖authorized_keys；如已有其他授权公钥，需先备份并保留。上传的是`.pub`公钥，私钥留在PC。

```powershell
Get-Content "$HOME\.ssh\id_zhidiao_rsa.pub" | ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAuthentication=no root@192.168.10.2 'mkdir -p /home/root/.ssh && cat > /home/root/.ssh/authorized_keys && chmod 700 /home/root/.ssh && chmod 600 /home/root/.ssh/authorized_keys && chown -R root:root /home/root/.ssh && echo ZHIDIAO_KEY_RESTORED'
```

第三条：使用私钥验证非交互登录，保留严格主机身份检查。

```powershell
ssh -o BatchMode=yes `
  -o StrictHostKeyChecking=yes `
  -o UserKnownHostsFile="$HOME\.ssh\known_hosts" `
  -o HostKeyAlgorithms=+ssh-rsa `
  -o PubkeyAcceptedAlgorithms=+ssh-rsa `
  -i "$HOME\.ssh\id_zhidiao_rsa" `
  root@192.168.10.2 "echo ZHIDIAO_SSH_KEY_OK"
```

三条依次执行，前面步骤无错误，最后一条SSH成功退出并输出`ZHIDIAO_SSH_KEY_OK`，即表示本次SSH公钥登录恢复完成。`ZHIDIAO_KEY_RESTORED`表示公钥写入步骤完成；它不能代替第三条的登录验证。SSH恢复成功后继续准备PL。

## 3. v5比特流文件校验与手动加载

先核对SD中的位流文件：

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

文件SHA匹配后，在启动Agent及LED前手动加载。下面命令使用当前已确认的`/dev/xdevcfg`字符设备；加载会重置PL。提供的image_fixed.ub中`/bin/busybox`指向BusyBox 1.24.1，未包含`timeout` applet，因此当前手动初始化使用`cat`写入，不依赖该applet。

```powershell
ssh -o BatchMode=yes `
  -o StrictHostKeyChecking=yes `
  -o UserKnownHostsFile="$HOME\.ssh\known_hosts" `
  -o HostKeyAlgorithms=+ssh-rsa `
  -o PubkeyAcceptedAlgorithms=+ssh-rsa `
  -i "$HOME\.ssh\id_zhidiao_rsa" `
  root@192.168.10.2 `
  "test -c /dev/xdevcfg && cat /sd/pl/zhidiao_observe_v5_led.bit > /dev/xdevcfg && cat /sys/class/xdevcfg/xdevcfg/device/prog_done"
```

命令成功退出且最后输出`1`表示本次写入后配置完成。该手动命令没有板端执行超时；若未正常返回、SSH中断、加载失败或prog_done不是`1`，先核查板端加载状态，再启动Agent或决定是否重试。只有SHA校验、加载成功和配置完成分别确认，才进入当前`check_only`工作流；不要把单独读到旧的prog_done=1当作已加载该文件。

本次仅整理操作说明，未在云端执行SSH、公钥恢复或该手动加载命令；具体板端执行结果由部署者保留。

初始化阶段预加载不表示已完成断电后的自动加载／SSH公钥持久化验收；冷启动恢复边界仍保留。

## 现有受审批加载／检查能力

正式加载与检查脚本已经存在于 `src/agent/src/zhidiao_agent/tools/pl_prepare.py`：PLPreparation按照部署配置生成固定SSH脚本，在Controller批准的工具计划内调用，不是第五个公开硬件工具。UART／PL采集脚本分别在同目录pl_uart.py、pl_observer.py及remote.py生成，不需要再往SD卡放一套Python Agent。

部署者在src/agent目录建立自己的deployment.local.json：

1. 使用deployment.example.json中的v5路径、SHA、寄存器和UART配置。
2. 默认observer.prepare_policy=`check_only`，只查文件SHA与prog_done，**不能证明当前运行的镜像就是该文件**。
3. `load_verified`作为现有可选能力保留：目标Linux需已确认支持可写字符设备`/dev/xdevcfg`、配置中的prog_done路径，以及加载器要求的BusyBox `timeout -s KILL`。提供的BusyBox 1.24.1镜像缺少该applet，当前部署保持手动初始化＋`check_only`，不直接切换此策略。具备全部依赖时，程序会检查已批准镜像SHA、在限定时间内加载并等待prog_done；这会重置PL，必须在原有工具审批中确认。启用LED时仍须在启动Agent前确认v5已加载。新Linux若仅支持FPGA manager，当前加载器不适用，不能猜测替代节点。

先预览现有工具计划，再按提示批准执行：

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
py -3.13 -B -m zhidiao_agent real-test --config deployment.local.json --expected-period-ms 1000 --tolerance-ms 50 --preview-only
```

确认计划中的加载行为、范围和预算后，去掉--preview-only由CLI收集审批。这里会执行真实PL测试，不只是加载。不得伪造审批、复用历史fingerprint，或在模型输入中加入任意devmem／shell。

只读文件检查入口是check_files.sh；实际远程准备、USB、寄存器可读性检查沿用deployment-check。文件／prog_done检查、镜像加载完成与DUT物理PASS是不同证据。UART FIFO reset和MMIO读取仍只由现有受控工具执行。
