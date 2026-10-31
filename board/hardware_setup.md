# 部署前提

Windows PC需安装Keil并连接Zynq：参考PC192.168.10.1/24，Zynq192.168.10.2:22，用户root。
仅使用经过验证的host key与非交互认证；旧Dropbear可能需要+ssh-rsa，示例已配置。不要公开Dropbear主机私钥或SSH私钥。
SD目录：/sd/pl、/sd/firmware/<run_id>/firmware.hex、/sd/tools/openocd。SCP后比较SHA，再program/verify/reset。
新增v5与LED在最终报告配置中出现，当前二进制与XDC仍待取得；不得对未知PL镜像盲写MMIO。
SSH authorized_keys与PL冷启动自动加载未验证持久化，上电后需人工准备；本包不修改启动文件。
