# A58–A60：恢复、交付材料与外部门禁

2026-10-15，原要求未缩减。本页区分已核本地证据、尚未测格和需要真实环境/授权的部分；不是生产维护、公开或真实模型演示签收。当前398源码/55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32，本轮应用与永久测试不改、不新建审查、不重复已验收门禁。

## A58本地证据：108已有通过，4实际权限跳过

五模块本次完整读，精确classname与[当前完整XML](../.cache/a46/review-final.xml)绑定：108现有PASS/4skip，全部在3014后端/3515离线及原14skip内，不能相加。0c7694实际退出0；XML SHA256=d297ae1a7a0628f0c1e9120ffcc510086c4cedaa3b21c65aebd10cb94f78ba90。

| 模块 | 已有通过/跳过 | 实际范围 |
| --- | --- | --- |
| [release_recovery](../backend/tests/test_release_recovery.py) | 49/4 | 001–005一致备份、WAL/辅助文件、NEW路径、篡改/重定向/容量拒绝 |
| [release_recovery_business](../backend/tests/test_release_recovery_business.py) | 6/0 | 最新真实合成业务守恒、旧备份反例、恢复后回执/规则回退、受控cron/timer停止 |
| [recovery_quiescence](../backend/tests/test_recovery_quiescence.py) | 46/0 | 实际资源收尾/在途拒绝、完整外写入者声明，不替生产盘点 |
| [post_publication_recovery](../backend/tests/test_post_publication_recovery.py) | 1/0 | 005四状态/出生证据/业务行/同窗13计数完整恢复，pending不自动执行 |
| [packaged_backend_compatibility](../backend/tests/test_packaged_backend_compatibility.py) | 6/0 | 新进程仅包内导入，恢复schema1拒绝/2–5核心及metrics边界，固定旧4包拒绝5 |

4个skip是平台不允许创建native symlink，不能冒充重定向测试成功；3项实际NTFS junction反例在49通过内。没有为绿测试修改权限或ACL。

[恢复实现](../backend/app/scripts/snapshot_recovery.py)及[停写门禁](../backend/app/scripts/recovery_quiescence.py)完整读：绝对隔离路径，拒绝源/子路径/现有目标/报告覆盖，64MiB总量/2000文件先限额；先复制到自有scratch再SQLite backup，包含未checkpoint的已提交WAL，不写源SHM。摘要精确集合、辅助字节、完整性/FK/版本均校验，未知文件/目录/坏schema或复制被破坏不能输出成功。restore先验再创建NEW目录，绝不覆盖当前或旧备份。

实际latest-business演练：先旧局并备份，再产生升级后新问答、评分、关联反馈、真实本地Conditional/Fake Agent候选、批准/发布审计；最终4局/4turn/8消息/1评价/1反馈/1run/1候选/2release。故障后备份最新提交状态，NEW恢复逐表逐行相等，开局/提问/评价及批准/发布原operation重放不丢不重。合法旧备份只有1局，独立业务oracle明确检出丢新ID；不能用SQLite integrity通过掩盖数据倒退。规则回滚只改指针/回执/新增审计，其余游戏/反馈/任务/候选/release完整保留。

恢复原语没有自行发现生产全体写入者。LOCAL门禁核Runtime.closed之外，还核模型active/waiting/timeout/cleanup、worker与心跳/真实shutdown receipt、HTTP客户端、内存pending、审计activeIO/memory/residual/unpersisted；实际blocked worker和审计job未退出时拒绝。外部声明必须精确包含API/cron/timer/legacy_merge/legacy_cleanup/manual_scripts/direct_database；未知/遗漏/额外项拒绝。受控cron/timer确实回调旧禁写shim并join退出，但这不是查看了服务器真实任务。所有成功回执仍quiescenceVerified=false/productionReady=false。

[包内探针](../scripts/tests/probe-backend-compatibility.py)已完整读：新Python进程导入30+模块只来自指定artifact，0网络尝试，Fake只调用一次且原UUID重放不再扣问次数，资源正常关闭。schema001拒绝写入，002/003 metrics503，004 wire3且005来源unknown，005 wire3/partial；固定旧schema4包对5拒绝且包/输入不变。[详细矩阵](release-recovery.md)的恢复后完整动态Agent/候选功能未测格仍UNKNOWN，不根据schema数字补通过。原始HEAD也未被证明兼容新库；需要该功能的生产切换不能开放。

结论：本地一致恢复、最新新写入守恒和有限代码兼容有真实证据；A58真实全写入者盘点/暂停记录、实际维护前恢复演练与生产迁移仍HOLD。不能将本地实现完成写成A58整体通过。

## A59：本地code-only包已核，生产维护未执行

本轮实读[当前交付回执](../.cache/a46/review-final-delivery-artifacts.json)及manifest身份，4ac3f0退出0；reusedArtifacts=true/rebuilt=false，不假称本轮重建。backend85规范文件/84复制源+自有合成seed，manifest f4f5ef17d8759b17a105ce49082f1ef6638c41ad03c73466bd3c33980241a0b6；frontend2045规范文件/24源及86相关输入，manifest a8eee997140668e1b46fe2c8c06d7a8022231affa969b5969b569b8917f714fd。八个必要eval proof模块在包内，旧archival raw/driver/私有case不带入。当前smoke确有模块来源/固定suite依赖/健康/原UUID重放、4页面/13静态/1public及正常关闭；不是Docker/Linux部署。完整证据见[当前单元验证](a46-local-verification.md)。

完整读[后端打包反例](../scripts/tests/backend-release-policy.test.mjs)和[前端打包反例](../scripts/tests/standalone-release-policy.test.mjs)，含合成canary、dotenv/数据/旧包/venv/私有case不复制、NEW目标、篡改/重封seed/重复JSON/junction/集合变化拒绝。[当前103项Node日志](../.cache/a46/review-final-harness.log)及[exit0回执](../.cache/a46/review-final-harness-exit.json)已实读；不把103说成103个镜像验证。固定allowlist不能证明允许源码/产物正文绝无密钥或已有公开许可。

生产仍须[本地指南中的8项阻断清单](howto-local-release.md)：独立授权维护窗、真实SSH host key/TLS/代理CIDR、最小权限/私密env与数据目录、全部写入者停写、LATEST恢复和兼容格、切换后健康/功能检查、真实旧局例外及模型/标签来源。未知SSH指纹不自动接受，不设关闭校验。旧deploy脚本仍有安装/覆盖/删目录逻辑，是[历史退役资料](../deploy/README.md)，本轮只读头部、没有运行或保证其代码本身已fail-closed。当前containerBuildVerified=false/productionReady=false；A59整体HOLD，不部署。

## A60：材料可用，公开与真人演示未成立

已完整读[九模块卡](learning/core-module-cards.md)、[学习路线](learning/project-learning-map.md)、[安全练习](learning/practice-checklist.md)、[三方向简历证据](resume-evidence.md)、[项目展示/七段演示清单](showcase.md)和[公开前盘点](publication-preflight.md)。架构/评测/恢复与版本限制有链接；[简历入口](../RESUME.md)不让旧97.7%/1565/255或独立实现草稿直接投递。AI辅助、需求/体验/验收贡献与本人独立技术能力分开，练习保持未代勾。

本轮发现并修正真实材料漂移：CM08及练习还称当前wire2/采集未接入，改为wire3/005、缺来源null、完整四状态及test排除，旧v2失败与报告作为历史保留；路线/展示/RESUME当前检查点同步398/3515/35UI、D18/A46本地单元已闭环，不再等待已通过门禁。未改历史XML/数值或编造真人实践。7277c7实际退出0核CM01–CM09完整9卡及15当前测试选择器（7具名/8整模块）都存在并在当前完整XML，未重新运行学生练习、没有代签本人掌握。

本地现存Fake/合成浏览器流程不是至少1条真实模型Agent轨迹、8个人工参考任务或真实七段视频。干净公共clone、全文件/历史内容与来源许可检查、允许展示的数据、公共仓库授权仍缺；公开盘点是明确的旧356历史有限元数据检查，不能沿用它签当前398内容/许可。当前尚无真实模型资格/调用/视频、公开仓库或生产切换证据，本轮不买额度、不上传、不部署，也不读取私有玩家材料来猜授权。

结论：A60本地求职/学习材料已更新并核实际入口；A60整体仍HOLD。核心工程总门禁保持3515/14skip+35UI，不将本轮资料核验算新增测试。继续原C01–C24/IR01–IR24/OV1–OV3/SG1/5约束及命令/制品逐项核对；原18阶段/A60全范围不缩减。
