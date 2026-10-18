# TS17 Latest Data Recovery Rehearsal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans, native inline TDD, same TS17 ledger and ONE whole-stage reviewer only after all LOCAL units. No phase confirmation/Git writes.

**Goal:** 证明升级后的新增业务记录可以经过停写/最新备份/新目录恢复/规则回退仍不丢不重；未知兼容旧release保持维护。

**Architecture:** 消费前一子计划的snapshot_recovery.backup/restore；独立LOCAL停写前置检查读取真实Runtime资源报告，不凭closed一个boolean认证。合成演练用真实API与既有实际Agent/人工确认替身业务fixture，恢复后重放同operation keys并核对数据库事实；没有生产操作或真实质量背书。

**Tech Stack:** Python/sqlite3/pytest、现有FastAPI TestClient/FakeModel、实际Agent/CandidateReviewStore/版本化发布与回滚。无新依赖。

**Spec:** docs/superpowers/specs/2026-10-12-ts17-local-release-design.md；原A58/C24/IR04。读取同阶段snapshot-recovery子计划与ts17-progress.md。

## Global Constraints

- 前一原语门禁LIVE时只做此计划，不改产品/测试。它完整门禁终态并签收后才进入本子计划RED。
- 所有路径是Settings.for_test隔离数据；生产Ready始终false，其他writer状态未知/active/缺项不放行。
- 不用旧备份覆盖最新源；backup/restore只到新目录。原239文件/HEAD/index保护不变。
- 不自动升级schema。应用默认需要002，Agent需要003，统计需要004；schema1可备份但当前应用startup应拒绝，不能当“兼容”。原默认/预算不变。
- FakeModel及Synthetic admin confirmations只能证明机械数据/门禁，不是模型答对或真人已审核；候选需实际生成/回归/确认/发布，不能手工插成功行。
- 不自动重启旧merge/cleanup/cron。原始旧HEAD未经当前schema兼容验证不能标支持；TLS/SSH/真实cron/生产上线单独HOLD。

## Review Focus

1. Runtime.closed=true但仍有blocked owner：Task1真实blocked adapter/worker shutdown反例拒绝。
2. 外部writer inventory少cron/timer/manual/direct DB或unknown：Task1每类缺项/active/unknown测试拒绝；声明只能证明LOCAL夹具范围，非服务器实际状态。
3. 故障后错误选择发布前artifact：Task2先实际产生旧备份，再新增记录，恢复必须消费最新artifact与新receipt，否则新ID/消息断言失败。
4. 恢复后重复create/turn/evaluate/publish/rollback：Task2真实同key重放与SQL记录数量/次数/版本断言。
5. 未知旧release/schema1startup：Task3拒绝且不改库，保持维护/前滚而非伪造兼容矩阵。

## Task 1: LOCAL owned-resource quiescence gate

**Files:** create backend/app/scripts/recovery_quiescence.py; create backend/tests/test_recovery_quiescence.py.

**Interfaces:** `require_local_quiescence(runtime: Runtime, external_writers: dict[str,str]) -> dict` raises snapshot_recovery.RecoveryError. REQUIRED external keys exactly api/cron/timer/legacy_merge/legacy_cleanup/manual_scripts/direct_database; allowed states stopped/disabled. Function does NOT stop any process or discover server topology. Report fields localOnly=true/productionReady=false/ownedResourcesStopped=true/externalInventoryDeclared=true/quiescenceVerified=false: external states are caller-declared, not proven global truth.

- [x] Step1 首个测试动态import明确失败；原生Runtime开着拒绝，实际aclose后无资源可通过；逐writer缺项/active/unknown拒绝。Settings.TESTING非true时拒绝（只构造Settings不访问路径/生产），无隐式get_runtime/load_settings。
- [x] Step2 `node scripts/test-backend.mjs backend/tests/test_recovery_quiescence.py -q --junitxml=.cache/ts17/quiescence-red.xml`，实际43FAIL；extended quiescence-complete-red实际46FAIL，均missing product API。
- [x] Step3 最小实现：runtime.closed必须true；pending_agents.snapshot().queued=0；若gateway存在其实际snapshot closed=true/active=0/waiting_online=0/active_online=0/active_agent=0/timed_out_but_running=0/cleanup_failed=0；若worker存在actualsnapshot admissionClosed=true/coordinatorAlive=false/heartbeatAlive=false/activeRunId=null/cleanupConfirmed=true，并实际agent_shutdown成功；已分配http sync/async clients的is_closed=true；audit_store存在时audit_shutdown.residualJobs=0/unpersistedCount=0及actualstatus.activeIO/memoryCount=0、admission_closed under owner lock（permanentGap保留警告，不误作还在写）；缺报告拒绝，不构造“成功”默认值。
- [x] Step4 实际Event阻塞的本地adapter按test_agent_shutdown/configured接口创建，将返回worker绑定到active.agent_worker（configured本身不做这个绑定）；实际Runtime.aclose有界返回但cleanupConfirmed=false且active_agent=1，必须拒绝。finally释放自己Event并核对资源关闭后才能接下一测试，不强制杀第三方请求。metadata只固定资源计数，不能写activeRunId/玩家内容/keys进报告。实际审计IO在途另有native反例。
- [x] Step5 `node scripts/test-backend.mjs backend/tests/test_recovery_quiescence.py backend/tests/test_agent_shutdown.py backend/tests/test_release_recovery.py -q --junitxml=.cache/ts17/quiescence-green.xml`；实际106PASS/4symbolic-link权限SKIP/10.46s，0fail。**只签selected gates，不称当前full suite已通过；整阶段全套仍待各单元结束后执行。**

## Task 2: Latest committed business state survives fault and replay

**Files:** create backend/tests/test_release_recovery_business.py; testing helper only if shared fixture setup grows, no test-only methods added to production classes.

**Consumes:** snapshot_recovery.backup/restore, Task1 require_local_quiescence, actual create_app/settings Runtime, existing test_candidate_review_store.proposal(active), test_candidate_review_mutations.approve_intent(detail), CandidatePublish/CandidateRollback.

**Produces:** 原生测试证据；不是新公网/Agent能力或生产恢复控制器。

- [ ] Step1 TestClient+soup synthetic创建旧会话/问答并正常关闭，保存发布前artifact；随后在同隔离源的新app创建新会话/问答/evaluate/反馈，用实际proposal生成run/steps/candidate并approve_intent/publish（admin确认为synthetic）；原nativefixture保持来源/corpus完整，不用直接INSERT伪造已完成业务。
- [ ] Step2 使用实际requestId/operationKey保留create/turn/evaluate/publish响应与数据库独立SELECT basis：全部旧/新session IDs、message id/role/content/turn_id、questions_asked、turns/evaluations、feedback、agent_runs/steps/candidates、规则release/runtime_meta幂等receipt；排除后续新HTTP观察审计时序差异，不比较会必变的整库dump。
- [ ] Step3 故障：退出owned TestClient/aclose，核对实际runtime model/agent/audit报告；模拟受控cron/timer线程停止并join，实际旧merge/cleanup再次调用应LegacyWriterDisabled、不删历史。全LOCALinventory闭合后过Task1门禁再备份LATEST。源/旧artifact摘要保持，最新artifact包含全部新增业务；恢复到新目录。
- [ ] Step4 恢复当前工作树code，API GET /api/session/{id}确认旧/新消息及次数；同requestId重发/api/chat，同session重复/api/evaluate；同operationKey重放publish与CandidateRollback。新回滚只切规则指针，不删旧版本、旧局绑定或候选/任务审计。replay不增次数/消息/turn/evaluation/发布/回滚业务事件。新HTTP attempt审计可增加，不能当重复业务。
- [ ] Step5 可观测失败测试：故意消费OLD artifact的恢复副本，必须被独立最新ID/assertion鉴别为不完整（测试应断言validator拒绝，不是让pytest故意失败）；未知inventory/未关闭owner/错release兼容不放行。先写验收测试看到新增闭环缺失的真实RED，再实施测试helper/最小必要product guard；若既有业务已经通过，如实记existing behavior，不声称修复。
- [ ] Step6 `node scripts/test-backend.mjs backend/tests/test_release_recovery_business.py backend/tests/test_candidate_review_publication.py backend/tests/test_game_transactions.py backend/tests/test_rule_rollback.py -q --junitxml=.cache/ts17/business-recovery-green.xml`；Expected0fail；selected绿不签整个A58（真实cron仍HOLD）。

## Task 3: Honest compatibility matrix and recovery runbook

**Files:** create docs/release-recovery.md; extend backend/tests/test_release_recovery_business.py.

- [ ] Step1 参数化schema1/2/3/4实际快照恢复；当前create_app实际启动/read/write：1拒绝且源未变；2/3/4当前默认核心游戏可实际验证。Agent/metrics只依据003/004实际请求和已有feature gates填写支持；未运行格UNKNOWN，不凭version数自动填绿。
- [ ] Step2 文档矩阵release identity为实际working-tree digest而非虚构新Git提交：已测当前版本、未经验证原始旧HEAD=UNKNOWN。Unknown禁止切回开放写；保留最新artifact、维护、关闭故障能力并在副本前滚。backup report.quiescenceVerified=false永不改写成生产认证。
- [ ] Step3 A58各LOCAL事实与production inventory/TLS/SSH/HOLD分别列证据；链接原语/业务/资源原生命令，metadata报告不放private内容。交付并非上线授权，不能执行部署模板。

## Preflight and self-review

Execution evidence 2026-10-12：Task1 selected106PASS/4linkpermissionsSKIP; Task2+Task3 schema-startup部分及既有邻接回归实际105PASS/0SKIP/41.09s，business-recovery-current.log/xml。Task2已经实际生成4sessions（3API+1既有实际反馈来源业务方法）、4turns/8messages、evaluation/feedback/run/candidate/steps/publication/rollback并验证oldartifact选择拒绝与receipt重放；已验证受控cron/timer禁写/停止。Task3 runbook与Agent/metrics矩阵格、整个LOCAL TS17全套/Edge/唯一review仍未交付。当前工程不是生产Ready，不给A58全项打勾；两个已纠正测试harness错误及真实RED分开保留ledger。

Task1与Task2共享exact require_local_quiescence字典键/范围；外部declared状态由Task2受控线程/真实旧入口测试证明LOCAL，生产状态仍unknown。Snapshot工具不负责业务语义，Task2独立SELECT与API重放核验。Task3不能默认当前代码向后兼容schema1或原始旧JSON代码能用新版库。Runtime.closed单独不充分，报告actual字段已从源码核对。前一子计划还在fullgate时只保存此计划，无并发源码修改。
