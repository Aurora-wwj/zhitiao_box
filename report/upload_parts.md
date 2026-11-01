# 大附件分包与重组

附件下载工具单文件上限32MiB。FPGA四分包和Zynq_Linux_Test两分包现已收到、校验并整理；SD启动／部署材料已通过Zynq_Linux_Test两分包完整接收核验，本轮直接复用。以下仅用于后续大附件，不需要重复提交已经收到的包。

在Windows的zhitiaohe项目目录拉取main，使用Python3.13：

```powershell
git pull --ff-only origin main
py -3.13 sim/prepare_upload_parts.py split "D:\实际目录\Zhidiao_PL.zip" --output ".\fpga-parts"
```

输入路径换成自己的实际路径，输出目录必须不存在或为空。输出part-0001.zip、part-0002.zip等普通ZIP，每包有效载荷29 MiB，含元数据仍小于30 MiB。上传fpga-parts内的全部ZIP，不要再次压成一个大包。

SD用另一个目录，分别提交两组，避免同名part混淆：

```powershell
py -3.13 sim/prepare_upload_parts.py split "D:\实际目录\Zhidiao_Linux_microSD.zip" --output ".\sd-parts"
```

工具不修改原ZIP、不解压或执行内容，仅切分字节并记录整体／分块SHA。分包仅用于向本次整理提供材料，不是GitHub发布源码，生成文件已加入.gitignore。

若文件名为Zynq_Linux_Test.zip或其他名称，替换输入路径；每组使用新的空输出目录。该测试包的两份已经收齐，不能与FPGA或其他SD包混组。

收到所有分包后，重组示例：

```text
python sim/prepare_upload_parts.py join part-0001.zip part-0002.zip --output restored.zip
```

实际数量超过两份时列出全部文件，顺序不限。工具校验分包身份、索引、各块SHA、总长度与整体SHA；缺失、重复、混组或损坏会拒绝。已存在的输出不会被覆盖，失败清理本次创建的残件，不使用manifest文件名构造输出路径。

5项离线回归覆盖正确复原、小ZIP格式／大小、缺失／重复／混组拒绝、损坏拒绝和原文件保护。分包工具测试不代表尚未取得的FPGA／SD内容已核验。
