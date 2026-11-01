# 部署前提

Windows PC需安装Keil并连接Zynq：参考PC192.168.10.1/24，Zynq192.168.10.2:22，用户root。
仅使用经过验证的host key与非交互认证；旧Dropbear可能需要+ssh-rsa，示例已配置。不要公开Dropbear主机私钥或SSH私钥。
SD目录：/sd/pl、/sd/firmware/<run_id>/firmware.hex、/sd/tools/openocd。SCP后比较SHA，再program/verify/reset。
v5位流、XDC和LED已从FPGA原件核对，见build/fpga与board/wiring.md；不得对未知运行PL镜像盲写MMIO。
当前v5 PL在初始化阶段加载完成，再启动Agent与LED；Agent使用check_only，保留现有四接口顺序。文件SHA校验与PYTHONPATH参考命令见[PL初始化说明](zynq/pl_preparation.md)。
SSH authorized_keys与PL冷启动自动加载未验证持久化，上电后需人工准备；本包不修改启动文件。

Zynq_Linux_Test两分包已收到：fixed镜像内有静态192.168.10.2/24配置和主机私钥，后者不得复用或公开；镜像存在某文件不证明当前板卡使用该镜像或冷启动验收通过。OpenOCD源码／构建入口、文件检查、现有受控PL加载说明见board/zynq与build/openocd。完整BOOT／Linux来源、构建配方仍缺。
