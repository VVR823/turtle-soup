# D18实施计划：发布后可信观测

> 主代理inline执行，无新增阶段确认。Task1–3本地完成；Task4统计/v3展示、压力/规模/35Edge及Task5恢复/当前包矩阵已验证。当前完整3446离线通过/14原skip、type/lint退出0；新前端构建/HTTP/来源绑定与两个容器输入通过（不是Docker）。原377前后身份与扩展380交付身份分开，不倒改证据。Task4/5整单元签收仍待唯一独立审查/必要修复与原A01–A60最终盘点，详见D18 ledger；不是整体或外部门禁完成。

**Goal:** 补齐原A57的后续回归失败数，并保证发布后版本、完整尝试分母、来源和流量隔离可验证。

**Architecture:** 显式005账本；服务器冻结语料+固定无外网复查；管理员显式请求；统计协议3读取同快照。旧版本游戏不自动迁移，不在问答热路径执行，不借此部署/读取真实数据。

**Spec:** [D18设计](../specs/2026-10-13-d18-post-publication-regression-design.md)。执行前每Task重读对应真实源和已有测试夹具，不猜文件/API。新文件若与未归属修改重叠，先保留并核对。

## Task1：注册005及不可变观测账本

Files：新增 `backend/app/post_publication_contracts.py`、`backend/app/post_publication_store.py`、`backend/tests/test_post_publication_migrations.py`、`backend/tests/test_post_publication_store.py`；修改 `backend/app/migrations.py`、`backend/app/scripts/migrate_data.py` 及相关隔离迁移测试。

1. 先读旧001–004 checksum、verify_schema/migrate和CLI现有拒绝/演练边界。记录旧tuple/checksum身份。
2. RED：5未注册；正确4→5、默认仍1、重跑1–5只读；断号/未知6/错误checksum/表触发器索引漂移；DDL/报告/commit故障回滚；用户原库不写。
3. 定义闭合plan/result，严格数字/UUID/版本/摘要/大小/全计划case唯一性/状态一致性，False不能当schema或计数。账本事务先记录running；immutable触发器和唯一key。
4. RED：重放不改时间/内容、同key异payload拒绝、并发只一份、终态不覆写、删除拒绝、timeout/硬停分母保留。最小实现后原生命令GREEN，保存新目录XML。

## Task2：已发布来源和真实固定执行路径

Files：新增 `backend/app/post_publication_regression.py`、`backend/tests/test_post_publication_regression.py`、`backend/tests/test_post_publication_provenance.py`；必要窄入口修改 `backend/app/candidate_review.py`。复用 `baselines.py/rule_contract.py/runtime.py/eval/manifest.py`，不改候选报告意义。

1. 读 `_immutable/_review_state` 完整源码及 `test_candidate_review_publication.py/proofs.py` 夹具，复用真实批准→发布事务，不手造published状态代替happy path。
2. RED：只批准未发布拒绝；候选状态/操作回执/审核/新rule binding任一损坏拒绝；旧报告不能充新观察；snapshot题目/语料版本错配、holdout、缺corpus、synthetic正式runtime拒绝。
3. RED：同一题旧版预览通过但新发布版出现反例，必须观察新版本；实际context历史不能用gold；无deterministic结果unsupported不PASS；完整planned分母包括所有error/not_attempted。
4. source identity与deadline校验前/中/后篡改、cleanup失败、runtime关闭、保存失败保留可查pending/完整计划；强制封网和不构造真实gateway证明0provider。
5. 最小实现；必要抽取历史发布验证，所有原候选批准/发布/撤销/回滚测试仍通过，不弱化原权限。保存native RED和GREEN，不把夹具初始化错误算产品RED。

## Task3：显式管理员入口及幂等

Files：新增 `backend/app/routers/admin_regressions.py`、`backend/tests/test_post_publication_http.py`；修改 `backend/app/main.py`、固定审计路由模板注册对应文件。

1. 读原 `routers/admin_candidates.py`、`routers/metrics.py`、request guard/StrictJSONRoute鉴权和审计模板。
2. RED：无/错token401；额外字段/重复key/未知path422；禁止客户端传语料/model/result；频率限额429；同key重放0额外执行、同key冲突409；源缺失固定错误，无私有文本泄漏。
3. endpoint只调Task2已绑定服务；无新Agent tool、后台进程或问答自动hook。异步/并发所有权按现有原生路由方式实现，不在SQLite锁内执行检查。

## Task4：协议3完整统计和管理展示

Files：修改 `backend/app/metrics_contracts.py/metrics.py`、`src/lib/metrics-contract.ts`、`src/components/MetricsPanel.tsx`、对应现有测试；新增 `backend/tests/test_post_publication_metrics.py`。

1. RED：全状态计划分母、失败/不完整区别、已过期pending子集、startedAt窗口、publishedRuleVersion筛选、回滚历史、test/synthetic排除、缺005/坏来源unknown而非0。
2. 统计应在原同read snapshot、3秒deadline内批量聚合，显式新schema3；cursor仍1，v2明确unknown兼容边界；DTO缺/多字段/错计数不能宽松接受。
3. RED前端闭合对象/窗口过滤/token清除/迟到响应，unknown/0活动不显示准确率；小屏仍局部横滚，不能重引入TS17I1宽页。
4. 更新query-plan与合成规模检查：包含新增账本的混合状态流量，真正EXPLAIN索引与完整reader测量；不相加旧次数/预填性能提升。

## Task5：当前新产物/恢复兼容及整单元验收

Files：针对 `scripts/backend-release-policy.mjs`、发布smoke/probe、`backend/app/scripts/snapshot_recovery.py` 与现有恢复测试确定最小改动；更新 `docs/metrics-reference.md`、迁移/恢复/发布材料。旧TS17 proof一律另存不覆盖。

1. 005完整最新数据备份/恢复保留running/terminal账本、新业务行；冻结旧4产物对5拒绝证明，新产物对5兼容及1–4功能格实测。未知格保持UNKNOWN。
2. 当前完整offline、type/lint、一次owned真实浏览器统计流程/375px，实际XML/终态/正常关闭后才记录通过。串行运行重门禁，原239哈希/HEAD/index先后核对；不访问真实行原文、不迁移真实数据。
3. 保存新source/test/lock identity和发布清单，旧c34身份只属于旧源；更新学习/简历仅明确新本地能力及代价，不编真实效果。
4. 对Task1–5全部完成的一个冻结单元派**一位**独立只读审查者（reasoning high/inherited model，除非工具或用户另有明确模型要求），真实5项ReviewFocus+完整Declined裁定；quota中断恢复同id，不按Task多派。
5. 收到真实报告→逐项核实→一次必要修正→相关原生验证及最终原范围盘点。原A57签收只限确证本地项；A58–60/全18外部门禁继续分开，不自动宣布整体100%。

## 执行日志与恢复点

使用 [D18 ledger](2026-10-13-d18-progress.md)。每项开始/真实RED/真实GREEN/最终状态和保存路径记实际证据，不运行已验收TS18学习用例。不修改Git历史、不部署、无需用户点继续。当前周额度接近上限时保存原恢复点，在同聊天小时调度实际恢复后接续，不兑换其他卡或绕过审批。
