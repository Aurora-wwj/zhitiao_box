# 真实证据索引

当前主证据来自用户最后上传的网页导出zhidiao-run.json，run_id为run_5d8e004954664f6c8f8ff0f85d31959b；公共匿名版在data/final_run_sanitized.json。此前Agent包中的同run归档保留为来源记录，不作为新增运行；原始SHA、公开SHA、导出差异见data/report_sources.json，处理范围见data/sanitization.md。
两轮四工具均 success=true，第一轮 PL passed=false（601.7169 ms），第二轮 passed=true（1001.08682 ms）；fresh_edges 均为 2。
第一轮 UART partial_tail=true、truncated=false；第二轮无半行。模型请求名 gpt-5.6-sol，协议 openai-responses；这记录请求配置，不认证远端模型权重。
main.c SHA 79f6deb58231d3bc2cef887154c136a74e0da9e839a26ea41fd9468e205633cd。
HEX SHA b6aca82331978cca76e967fd7d08f3d33994672215ff3e6a50f0173662b9f70f。
运行 JSON 含审批、diff、before/after 与实测；本地整理未重新烧录。公开报告不能恢复历史权限。

网页导出总耗时81.18937509999523s，此前归档81.16940819999581s，两原件的JSON差异只有elapsed_s，约0.0199669s；测量、审计、审批与源码均相同。导出时间和截图数量不等于新增实测次数。

| attempt | 工具执行 | 完整周期／ms | 原始误差／ms | 网页周期／ms | 网页误差／ms | 判定 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | build／flash／UART／PL均成功 | 601.7169 | 398.2831 | 601.717 | 398.283 | FAIL |
| 2 | build／flash／UART／PL均成功 | 1001.08682 | 1.08682 | 1001.087 | 1.087 | PASS |

第一轮末条ZHIDIAO_O为正常采集截止半行，partial_tail=true、truncated=false；第二轮两条完整ZHIDIAO_OK与截图相符。UART内容不替代PL判定。

完整审阅diff提取至data/final_source_change.diff，保留HAL_Delay(300)→500和assert_failed文档注释的一处变动，未改黄金main.c。原diff与LF公开副本分别记录SHA；不能将摘录当作完整改动。

四张原PNG见data/screenshots/README.md，逐项SHA校验。主案例图与JSON按run_id、数值和日志关联；PL-only单轮1000.192ms图仅有截图，不能计作完整四接口闭环。审计图中历史下拉所选run_2178…与当前JSON的run_5d8e…不是同一个界面字段，当前版本已添加分别标识。截图为旧版本实测原件，不伪装成本次界面更新后的重新上板。
