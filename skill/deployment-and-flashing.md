# 可靠固件部署

## 适用范围
适用于主机编译、SCP传输、远端OpenOCD和SWD烧录的系统。

## 使用步骤
1. 重建受批准源码，检查编译状态、0 Error(s)、新HEX。
2. 核对产物路径、大小和本地SHA。
3. 严格known_hosts与非交互SSH，旧Dropbear兼容项仅按部署需要启用。
4. 上传独立run_id目录，远端SHA必须相同。
5. 执行program verify reset exit并同时检查返回状态和成功标记。

## 验证方法与已验证效果
公开最终报告的两轮build／flash均成功，上传SHA一致；发布HEX与第二轮b6aca823…f70f一致。
复用前运行Agent对应离线测试，并在自己的板卡上重做同类测试；当前实例不替代新平台验收。

## 来源
从只检查文件大小不足以证明上传一致、旧产物可能被误烧的集成失败风险提炼。

## 失效条件
不要跳过host key、校验或审批；SSH中断不证明远端OpenOCD停止。私钥／API Key不得进入公开包，冷启动认证需自行恢复。

## 可执行的软件检查

从仓库根目录先执行 `python sim/check_release.py` 核对参考证据；再进入 `src/agent`，设置 `PYTHONPATH=src` 后运行：

```text
python -B -m unittest discover -s tests -p "test_real_workflow.py" -v
```

Windows使用Python3.13时可将python换为`py -3.13`。这些是离线验证，硬件迁移还须按report/reproduction.md重新部署并获得自己的实测报告。
## 已提供源码与新增构建观察

Zynq Linux测试包中的887份OpenOCD脚本与源码一致；OpenOCD／libusb原tar和许可现已公开，构建入口见build/openocd。原上传ARM ELF的完整静态依赖／确切配方仍缺，不直接再分发。

本机构建曾暴露libtool `-static`不等于完全静态ELF；`-all-static`需限定在Automake链接阶段，不能通过全局LDFLAGS传给直接用gcc的Jim Tcl。修正后实际x86-64构建／版本检查通过，仍需目标ARM和USB/SWD验收；静态glibc的NSS等警告保留。

fixed镜像里有主机私钥和静态IP，不等于免密authorized_keys或PL已能冷启动恢复。私钥／含密钥镜像不公开；每块板用自己生成的主机身份，按可信指纹建known_hosts，不能复用现场私钥。
