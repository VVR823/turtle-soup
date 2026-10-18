# Agent 修复工具接口（TS13 本地工程完成）

这是本地后端内部接口，不是玩家 API，也不是已上线的自动修复功能。Unit1–4及唯一阶段审查/一次Important修复已完成：399相邻、2230离线通过/10skip、29 Edge页面通过，build/lint/type/diff和原239数据保护门禁已核验。真实独立题集、模型质量、人工审核、生产003迁移和发布未验收，详见[当前阶段证据](ts13-status.md)。

## 输入与身份

模型输入为严格 JSON：`action="tool"`、下表固定 `tool` 和其 `arguments`。最大32KiB，禁止额外字段、重复JSON键、NaN和Infinity。Python DTO也重新校验，`model_copy`不能绕过检查。

服务器另传 `ExecutionIdentity(runId, operationKey, leaseToken, seq)`；前三项为规范UUID，seq为0到9223372036854775807的真实整数。模型参数不能指定身份、文件路径、命令、测试题集、模型工厂、预算、权限或报告正文。

| tool | arguments | 实际返回 |
| --- | --- | --- |
| get_turn_trace | turnId：当前任务绑定UUID | TraceResult：当前已审核脱敏输入和版本；claimsOnly=true，玩家说法不是标准答案 |
| retrieve_truth | soupId、puzzleVersion、query：非空1–500字符 | TruthResult：当前事实范围内最多8条；每条excerpt最多256字符，truncated明确标记 |
| find_rule_conflicts | baseRuleVersion、draft | ConflictToolResult：重复、冲突、可替换、需人审或未发现已知冲突；answerSupported和contextIndependentConfirmed始终null |
| run_regression | draft | RegressionReport：固定安全检查及服务器显式绑定的兼容dev/regression题集；无合格题集时incomplete，不能假通过 |
| save_candidate_rule | draft、regressionReportId：实际已存报告UUID | CandidateRecord：pending；只接受同任务/同草案/同版本/同测试套件的已完成通过报告，不批准、不发布 |

`CandidateDraft`固定schemaVersion=1、type=exact_qa、operation=add或replace、normalizationVersion=exact-v1。包含soupId/puzzleVersion/baseRuleVersion、question（非空1–500字符）、五类answer、1–32个唯一factIds和非空1–1000字符evidenceSummary。仅replace必须有targetRuleDigest；canonicalQuestionKey由程序计算，不能额外指定。草案不含人工确认、审核凭证、通过报告或“答案已被证明”字段。

## 存储与执行

`AgentStore(runtime, *, authorize_create, clock=time.time)`要求显式Runtime和创建授权函数。授权必须返回真实True。构造不初始化数据库、迁移或模型；每次操作显式绑定该Runtime并要求已完成003。生产默认初始化仍为002，迁移默认仍为001。

| 方法 | 参数 / 结果 / 约束 |
| --- | --- |
| create | request_id、feedback_id、expected_feedback_version、allowed_tools、suite_manifest_digest均由服务器提供；返回queued RunRecord。源反馈/脱敏许可/版本在同事务检查；持久化未终结队列上限10 |
| read | run_id → RunRecord；读取仍重新校验当前许可和版本 |
| claim | run_id、expected_row_version → running RunRecord；新服务器租约，首次开始后总180秒期限不刷新 |
| heartbeat | run_id、lease_token → RunRecord；同所有者续租，30秒且不超过原总期限；不刷新预算 |
| reserve_step | identity、action → StepReservation(step, newly_created)；同事务确定是否首次创建，新工具意图先消耗一次预算，上限8 |
| plan_step | identity、action → StepRecord；兼容仅保存意图的调用，不执行工具 |
| complete_tool | identity、三个只读工具的严格成功DTO → StepRecord；完成事务中重新核实际源内容/权限/租约，不接受任意JSON成功 |
| complete_regression | identity、服务器固定执行器的RegressionReport → StepRecord；核实际意图/报告ID/任务/草案/上下文/版本/套件绑定，保留incomplete或failed报告 |
| fail_step | identity、固定ToolFailure.code → failed StepRecord；失败占用的工具预算不退回 |
| save_candidate | identity、draft、regression_report_id → immutable pending CandidateRecord；同内容幂等，改变内容/报告拒绝，不改活动规则指针 |
| finish | identity、FinishAction →终结RunRecord；本任务pending候选进入awaiting_review；无候选且有非空needsHumanReason则needs_human；不是人工批准 |

`ToolExecutor(store, *, regression=None).execute(identity, value)`只按五个固定分支执行。可选regression必须为属于同一Runtime的FixedRegression，不能由模型JSON指定。先原子保存意图，再在短读取事务结束后计算，最后重新检查许可/租约并保存。旧completed/failed步骤在当前许可检查后重放；旧planned步骤返回`agent_step_uncertain`，不能把不确定的旧执行再当成一次免费尝试。同租约心跳可增加rowVersion，不会误拒绝结果；所有者变化/超期/撤权则拒绝迟到写入。

执行失败输出固定`agent_tool_failed`，不泄漏原始异常/路径/私密输入。撤权后连失败记录也不能写，原planned意图和已占预算保留。业务事件与变更同事务，审计失败回滚该变更。

## 当前固定安全回归

代码身份同时核磁盘与进程实际加载代码：固定模块的实际函数代码与编译源相符、文件不能晚于包加载时钟修改，完整源字节在进程内冻结；运行前后再次检查。正常热修改需要新进程，不能新建执行器就为旧实现签发新源码身份。只编译核对、不执行新源；不是本机恶意 Python/OS 的隔离沙箱。此要求只作用于显式修复回归，不在玩家问答路径增加文件扫描。

`FixedRegression(runtime, *, corpus=None, clock=time.monotonic, utc_clock=time.time)`仅接收显式Runtime、服务器选择的FrozenDataset和服务器时钟。题集完整验封且只能dev/regression、1–100个案例，holdout/复制篡改/超限拒绝；运行时再次验封，整个catalog必须与实际同一汤底、完整p1/r1快照一致。`run(draft, *, run, identity, soup, rule_snapshot)`核完整冻结源/身份；suite_manifest_digest绑定固定注册执行依赖代码字节、探针策略和题集datasetDigest，不由模型选择。

固定五项检查实际执行：拒绝未知/越权工具和重复JSON；拒绝假事实ID；保留否定词区别；自有FakeModel正常协议；自有固定重复键坏协议必须被模型网关拒绝。没有题集时保留第六项`needs_corpus`。不读取真实模型，也不使用或关闭应用原网关；隔离原请求审计上下文，假调用不会混入真实请求用量。每个自有假网关有独立清理记录。

检查窗口最多5秒，且不超过任务原期限；原宿主45秒网关调用被自有有限网关夹紧到回归剩余窗口。固定CPU检查是协作式限时，不是强行终止任意Python或远端推理。报告保留完整计划分母、实际尝试/通过数、失败/截止原因、耗时、截断和cleanupConfirmed；输出最多32KiB。未知清理结果不能装作成功。

`CandidatePreview(draft, *, context, soup, rule_snapshot).apply(question, baseline_result)`只在原宿主结果算出后试改精确候选，不隐藏reminder/system_error/win或改其他问法；contextIndependent=false、matchedCheckpoint=candidate_preview，原规则/cache/活动指针不写。不是Published RuleSnapshot或人工凭证。

有兼容题集时逐个运行实际原宿主+本地预览，只用自有固定FakeModel。上下文案例按真实顺序携带实际前轮answer/kind/免费标记，而不是标准答案或仅显示文本。反例全部保留，题集标签不改写。至少覆盖候选问题；replace还必须有其他问题的独立案例，否则needs_corpus。全计划通过/未超时/清理确认才能complete；合成夹具明确标记synthetic_fixture。当前实际110条私有AI草案仍待独立人工审核，不是可用标准答案。这里的机械通过不能证明任意中文正确、真实模型效果或替代人工发布确认。

## 可复现的本地检查

在仓库根目录、已安装本项目锁定离线测试依赖时运行：

```powershell
node scripts/test-backend.mjs backend/tests/test_repair_tools.py backend/tests/test_fixed_regression.py -q --tb=short
```

复用执行器每次重新核题集与固定代码指纹，资产变化必须重新绑定任务，不能沿用旧报告身份。

该组合仅使用临时数据库和明确标识的合成夹具，不调用真实模型；测试数量以当前命令输出为准。缺依赖时先遵守[测试隔离说明](testing.md)，不要改用生产路径或下载新环境绕过限制。

## 相关

[大白话解释](agent-tools-explanation.md) · [自主进度](autonomous-progress.md) · [绑定设计](superpowers/specs/2026-10-09-ts13-tools-design.md) · [实施清单](superpowers/plans/2026-10-09-ts13-tools.md) · [评测数据](evaluation-data.md)
