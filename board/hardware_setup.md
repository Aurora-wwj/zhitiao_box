# 部署前提

Windows PC需安装Keil并连接Zynq：参考PC192.168.10.1/24，Zynq192.168.10.2:22，用户root。
仅使用经过验证的host key与非交互认证；旧Dropbear可能需要+ssh-rsa，示例已配置。不要公开Dropbear主机私钥或SSH私钥。
SD目录：/sd/pl、/sd/firmware/<run_id>/firmware.hex、/sd/tools/openocd。SCP后比较SHA，再program/verify/reset。
v5位流、XDC和LED已从FPGA原件核对，见build/fpga与board/wiring.md；不得对未知运行PL镜像盲写MMIO。
当前v5 PL在初始化阶段加载完成，再启动Agent与LED；Agent使用check_only，保留现有四接口顺序。路径变量设置、三步SSH公钥恢复及v5文件SHA校验／手动加载统一见[板端初始化说明](zynq/pl_preparation.md)，最后输出ZHIDIAO_SSH_KEY_OK表示本次公钥登录恢复完成。
SSH authorized_keys与PL冷启动自动加载未验证持久化，上电后需人工准备；本包不修改启动文件。

Zynq_Linux_Test两分包已完整接收核验SD启动部署材料。Linux为ALINX配套预构建PetaLinux2017.4／4.9.0-xilinx／BusyBox1.24.1，按[rootfs定制说明](../build/linux/readme.md)和[SD部署](zynq/sd_deployment.md)复现网络修改、FIT重封装及部署，不要求新增完整PetaLinux源工程或重新生成BOOT.BIN。历史fixed内有静态IP和设备专用私钥，私钥不复用或公开。队伍报告原系统冷启动网络／SSH／USB／SWD已验证，云端生成的新产物仍需独立上板；免密公钥持久化和PL开机自动加载分别记录。新HDF内含bit与黄金v5相同。
