# A36–A38 公开边界与反馈持久化

2026-10-15。当前398文件/55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32无漂移。以下8个现有模块完整读并逐字节绑定，从[当前完整XML](../.cache/a46/review-final.xml)按完整classname核对146通过/1明确平台跳过；均已在3014后端/3515离线总数中。没有将文件名前缀误配的临时统计当成绩，也没有重跑全套。

| 模块 | 通过 | 跳过 | 主要断言 |
| --- | ---: | ---: | --- |
| test_public_search_boundary | 13 | 0 | 私有搜索词不命中；合法揭晓/终态恢复保留汤底 |
| test_feedback_storage | 26 | 0 | 并发提交/审核CAS、真实turn关联、审计/commit失败回滚 |
| test_feedback_import | 24 | 0 | 重复旧ID分行溯源、重导幂等、坏行/源变化/预算原子拒绝 |
| test_feedback_import_cli | 13 | 1 | 隔离新输出、源DB/WAL/SHM不变、坏行exit2、不覆盖 |
| test_feedback_http | 19 | 0 | 私有管理权限、审核/隐私显式版本、关闭旧merge、公开安全错误 |
| test_feedback_privacy | 12 | 0 | 人工完整脱敏许可/CAS/撤回，原输入保留，零模型调用 |
| test_repair_tools | 16 | 0 | 闭合工具分派，无shell/SQL/publish/web_search任意副作用 |
| eval.tests.test_dataset_cli | 23 | 0 | 私有材料不因公开开关变公开，holdout不可repair-export |

唯一skip为test_cli_source_file_symlink_alias_cannot_import_outside_its_copy，实际原因OS symlink privilege unavailable; no ACL changes。不提升权限、不把跳过写通过；同文件另有实际path-resolution alias在backup前拒绝的通过用例，但不冒充操作系统symlink实测。XML SHA256=d297ae1a7a0628f0c1e9120ffcc510086c4cedaa3b21c65aebd10cb94f78ba90。

## A36：提前不泄漏，合法揭晓不是泄漏

[公开边界测试](../backend/tests/test_public_search_boundary.py)真实ASGI搜索私有bottom/bottomSummary/checkpoint/事实主体/对象时，与无命中响应逐字节一致，已解锁隐藏汤也一样。只按公开title/surface/tags大小写无关检索；另一汤面确实出现该词时仅命中该公开汤，不反推私有汤。列表/开局/playing恢复不含私有记录，模型输出非法和404普通错误也不含题库原文。

同测试明确保留合法例外：有站点鉴权的evaluate可看本局bottom，结束GET恢复同一evaluation，重复evaluate返回同字节；没有口令仍401。不是将所有bottom字段一律删掉。内部审计/模型用量中的reasoning/异常/凭据边界另见[A34–A35](acceptance-a34-a35.md)，公开目录不含管理员事件或内部事实证明。

公开导出是权限边界，不承诺自动正则脱敏：完整读取的[dataset CLI测试](../backend/eval/tests/test_dataset_cli.py)证明私人dev/regression只能私有repair export；holdout不允许，--public-synthetic不能给私有材料换身份。只有材料本已public_synthetic/public_authorized且再次明确公开合成确认才可导出。导出内容仍含其已授权样例问答；未实际公开上传，也不将完整私有RunReport当公开材料。管理员私有反馈/原Trace不属于公开导出物，不能因在本地能读就公开。

### 实际GamePage HTML文本探针（本轮新增本地诊断，不进入3515）

原同源测试没有专门的HTML节点注入断言，故新增仅.cache内的[两项探针](../.cache/a46/a36-public-text.probe.test.tsx)与[隔离配置](../.cache/a46/a36-public-text.vitest.config.mts)。配置替换默认include，不追加395项；保留envDir=false/原jsdom setup，全部fetch为显式合成stub，未启动HTTP服务/浏览器/模型。

实际命令：`node node_modules/vitest/vitest.mjs run --config .cache/a46/a36-public-text.vitest.config.mts --reporter=json --outputFile=.cache/a46/a36-public-text-result.json`，03900f原生exit0。[JSON](../.cache/a46/a36-public-text-result.json)实读success=true、2通过/0失败/0pending，仅此1文件；[输出](../.cache/a46/a36-public-text.log)保留。

实际渲染原GamePage的playing/given_up两状态：玩家script字符串、模型img/onerror字符串逐字出现在textContent，却没有任何带该注入标记的script/img节点；仅合法结束状态显示iframe形态的合成汤底，也仍为文字而非iframe。只有一次stub GET、零POST。这是React DOM节点隔离证据，不宣称全站浏览器漏洞扫描、CSP或真实用户攻击测试。probe SHA256=e3faad038e90b6c4ad0c798938858d72af8d9c8e2aabbb759d779319d4ad198a；配置=e78bb41d0a7d682ffef7a0b0379b9ea5f1658a06440d0ef4e7bbf002b099fb2d；JSON=1ec43b31e22057bdc954eea51bc783381d2fbe2840b12cc0e5d53b1b9279ab39。

玩家/模型文本不是Python/工具选择权限：[闭合分派测试](../backend/tests/test_repair_tools.py)真实未知shell/SQL/publish/web_search输入全部拒绝，数据库快照不变/模型调用零。[ToolExecutor](../backend/app/agents/tools.py)只分派强类型白名单，并核run/lease/原scope/许可；原GamePage文本不进入此分派入口。不能声称模型在语义上永远不会听信注入，只证明输入不能直接成为任意代码/越权工具副作用。

## A37：并发与重复旧ID不会覆盖别的问题

[SQLite测试](../backend/tests/test_feedback_storage.py)实际Barrier并发20提交→20唯一记录/20业务事件；一边新提交一边审核保留两条，旧行rowVersion只增一次；两位审核者同版本只有一个成功，另一个409。row、必要audit或commit各注入失败均完整回滚。HTTP approve/reject要求expectedRowVersion，不能靠旧列表盲盖新决定；审批不自动给safeForModel。

提供turnId时核原session/soup/question/HostResult展示回复/题库/规则/引擎及已完成状态，错问题或错汤不能借别人的Trace；缺turn允许反馈但unverified，不伪造关联。[导入测试](../backend/tests/test_feedback_import.py)实际同legacy id、不同问题仍两独立UUID5记录；完全相同的两物理行也各留一条来源，重复运行同一源才去重。sourceFileDigest/lineNumber/lineDigest/originalIdDigest与legacyHistory可追溯，不以旧feedbackId单键覆盖。

## A38：002门禁、显式导入、数据库权威

[feedback store](../backend/app/feedback_store.py)在短事务中核002 checksum；缺M2拒绝且不回退写feedback.jsonl。[import](../backend/app/feedback_import.py)显式BEGIN IMMEDIATE并verify_schema(required_version=2)，逐行身份/同内容匹配，必要审计同事务；源100MiB/5000行边界与读期间变化都在提交前拒绝。002逐语句失败/固定001保护另由[A34–A35](acceptance-a34-a35.md)27迁移用例支撑，不再重复运行。

重导不会重置后续人工approved/rejected、授权/撤回或rowVersion；源关联/隐私摘要损坏则冲突拒绝，不借“幂等”掩盖坏数据。坏JSON/UTF8/部分尾/日期/未知字段/超长行给行号、digest和固定code，保留源字节；正常行可导入但needsReview，CLI真实exit2，不能把部分导入称完整成功。insert-audit和真实commit失败均回滚，原源文件不删改。

[CLI测试](../backend/tests/test_feedback_import_cli.py)只接受明确新目标/新report，拒绝已有目标/覆盖/源目标重叠/真实运行目录及祖先；dry-run不留下目标。未checkpoint的源DB/WAL/SHM摘要前后保持。日常提交/审核/list/隐私操作都读写DB，HTTP提交不创建JSONL文件；旧merge入口410，旧verified_qa_pairs文件不偷偷写回。显式离线导入有界扫描历史，与每次线上请求全量JSONL读改写是两回事。

结论：A36–A38本地具体行为和新增2项DOM诊断已有实际证据，平台symlink限制独立保留。无应用/永久测试修改、无新独立审查/全量回归，无真实数据导入、云调用或公开操作；继续A39–A40版本发布/停用和冻结许可/旧Trace门禁。
