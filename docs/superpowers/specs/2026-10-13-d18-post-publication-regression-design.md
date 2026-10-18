# D18：可信发布后回归观测（原A57欠项）

状态：Task1–5已有本地实施证据；审查前冻结版本完成3446离线通过/14原有跳过、35Edge及新产物验证。2026-10-14唯一整项只读审查完成，I1/M1已复现并最小修复，M2同步状态；修复后完整门禁、产物重新绑定与整单元签收仍待完成。旧/新proof绑定各自源码、不相加；接续原实施计划§9第7项，不重开TS18材料审查，不替代真实质量/上线证据。

## 设计时已核实的边界（新增005前的来源基线）

- `rule_publication.py` 的 `publish_in_transaction` 先插入不可变 `rule_releases`，验证新快照，再更新版本指针和必要业务审计；`CandidateReviewStore.publish` 在同一事务保存候选发布状态、操作回执与 `candidate_published`。
- `CandidateReviewStore._immutable` 核对候选、Agent运行、原回归工具步骤和报告；`_review_state` 核对审核/发布回执。这是发布来源验证入口，不等于发布后观测。
- `agents/regression.py:FixedRegression` 执行候选预览；报告绑定 `baseRuleVersion`，不能改个名称当新版本的复查。旧报告和旧审核授权保持不变。
- `runtime._verified_repair_corpus` 只接受显式服务器输入的冻结dev/regression数据，单题、1–100例；正式runtime拒绝synthetic来源。`eval.manifest.load_repair_corpus` 拒绝holdout。继续复用这些边界，不扫描玩家数据、不生成标签。
- `metrics._summary` 当前没有发布后来源；后端/前端协议2都只支持unknown/null。004仅统计索引；现有迁移默认1、最高4，旧发布产物只认原注册前缀。

## 方案裁定与技能使用

已按brainstorming进行来源检查和方案取舍，再按writing-plans形成实施计划。用户已明确授权推荐方案自主执行、不要阶段提问，故不重复要求设计/计划确认；不执行技能中的提交、公开、采购或跨目录配置。当前heartbeat不发常规进度通知。

1. 把候选报告/失败Agent数当发布后失败：拒绝，测的对象和时间都不对。
2. 仅追加松散审计JSON、由调用方上报passed：拒绝，容易漏掉崩溃分母，来源/幂等/终态约束分散。
3. **选显式005的有界观测账本，加独立无外网复查器**：多一份迁移，但能持久记录先开始后执行、不可变计划、唯一请求、终态一次落盘；兼容成本必须实测。不增加队列/Redis/定时服务，不放到玩家问答请求里。

## 最小流程与权限

管理员显式请求 → 验证真实发布回执及冻结语料 → 保存不可变观测计划 → 短事务结束 → 对已发布的指定版本运行固定检查 → 一次终态落盘 → 私有统计聚合。

- 新内部调用 `PostPublicationRegression.run(runtime, request)`；闭合请求只含 `operationKey/candidateId/publishedRuleVersion`，不收passed、expectedLabel、语料路径、模型名或代码路径。
- 同既有管理员鉴权/StrictJSONRoute，新增有界POST `/api/feedback/admin/post-publication-regressions`；每分钟5次。调用是显式管理员操作，不自动随发布/游戏请求执行，不开放给Agent工具。
- runtime的已验证冻结repair_corpus是唯一语料输入。无语料、holdout、未审核、跨题/题目版本不匹配、来源不完整时拒绝开始，不凭空制造成功样本。统计仍显示缺观测，不代替真实人审。
- 从候选的不可变记录、审核/发布操作回执和不可变新规则快照交叉验证；不能只信status='published'或一个audit JSON。既有 `_immutable/_review_state` 的历史验证逻辑可提取为有名称的窄入口，不能弱化原审批或调用会依赖当前候选预览的 `_detail`。
- 已回滚的历史发布版本仍可显式复查，标的是历史指定版本，不切当前指针；暂停/来源撤销的处理沿既有授权语义：开始前重新校验，不能用复查绕过撤销或授权发布。执行前和保存结果前重新核对固定来源身份及发布绑定。
- 管理员令牌只用于鉴权，报告/日志/导出不保存令牌。错误码固定，不反射SQL、私有原文或路径。

## 005账本及恢复语义

新增 `post_publication_runs` 表（最终DDL在Task1原生测试中精化）：

- 唯一operationKey/runId；绑定candidate、发布操作、题目、puzzleVersion、实际publishedRuleVersion、发布时间、服务器startedAt/deadlineAt、来源流量类别和evidenceKind。
- 不可变planJson/planDigest，包括suite源码摘要、datasetDigest、完整有序case标识/摘要及plannedCaseCount。没有题目原文、背景、回答、模型输出或审核理由。
- 状态running/passed/failed/incomplete；终态resultJson/resultDigest/finishedAt只允许从running写入一次。禁止改计划、终态覆盖或删除历史；FK/类型/长度/时间/计数CHECK，按startedAt索引。
- 复查前成功插入running后才执行检查；同key同payload重放返回原记录，不再次执行；同key异payload拒绝409。并发同key只有一份计划。不得声称崩溃后远程调用exactly-once。
- 正常异常/超时/清理失败保存incomplete，保留整个计划分母和已执行结果。进程硬停后running仍可查，期限已过显示pendingExpired，不伪装failed或passed、不自动补测；显式新key才能重试并计新一次。
- 005注册报告含coverageStart/noHistoricalBackfill和新索引/表身份；旧001–004的SQL/checksum不改。显式目标5才写；默认启动/迁移仍不升5，真实库不迁移。
- verifier接受正确1–5前缀，>=4仍验证004，>=5验证005全结构/报告，未知6/断号/漂移拒绝；005失败事务只撤销005。旧有效1–4游戏/Agent可运行；005缺失仅新复查不可用。
- 原冻结4版产物不能读5库，必须诚实标为不兼容；更新恢复矩阵、当前新产物与拒绝证明，不冒称旧归档支持5。

## 固定复查与失败口径

- 使用 `baselines.session_baseline/read_rule_snapshot` 得到**publishedRuleVersion**的快照，通过实际 `ai_host.handle_host_response(..., versions=..., rule_snapshot=...)` 执行，不调用 `CandidatePreview.apply`，不修改当前发布指针，不创建/计费玩家会话。源核验已证明 `decide_deterministic` 不接收rule_snapshot，单独调用它会漏掉新exact QA；它只是在生产主持路径中新exact处理之后的原规则分支。
- 使用独立owned runtime及缓存，禁用trace/任何provider入口；一旦需要模型fallback，记录unsupported而不是给Fake答案再判通过。生产主持路径的kind/answer和实际历史仍保留，不重复实现一套精确命中算法。该拒绝模型的方式必须由原生测试证明0gateway/provider分配、0原runtime/cache/指针/玩家存储变化；实现前核对真实getter和错误传播边界，不能猜测接口或把新架构写成已经实现。
- 验证冻结catalog题目内容与发布题目快照一致。catalog中的旧ruleSnapshot仅是语料来源身份，不当作执行版本；语料case的来源版本与实际复查版本分别保存。
- 计划完整包含所有有序dev/regression例（最多100）；context例按conversationId/contextIndex顺序用实际前序结果构造历史，不能注入gold历史。
- 每例状态passed/counterexample/unsupported/error/not_attempted；deterministic无结果标unsupported，不能以FakeModel固定答案混成语义通过。这里的复查只证明已发布的确定性规则在该显式语料上的表现，不是免费真实模型效果。
- 同时包含固定来源/版本绑定检查。suite由固定源码注册列表、policy版本与dataset摘要派生，沿 `verified_process_sources` 的已加载代码/源码一致性验证；构造时、执行前、结束前身份一致。无模型/客户端给的source digest背书。
- 裁定：新准入/新终态在原SQLite before_commit及runtime lock内再核发布/隐私、冻结语料、固定进程源码及完整有序case绑定。非DB语料替换沿runtime已有同一锁；历史get/幂等ack只核实际发布/隐私，不因今天换语料而重新跑旧结果。源码核验不是任意Python或OS原子隔离证明；不改变原宿主范围。父runtime停止后拒绝继续新probe，owned上下文仍负责清理，硬停/来源撤销保留pending完整分母。
- 总deadline5秒，最多100语料例；无外网、无真实模型。若因校验/执行超时未完成，所有未执行例仍占planned分母，不静默截断。cleanup未确认不得passed。
- `failed`表示已观察到counterexample；同时有error/未执行项仍公开不完整计数，不能因失败就宣称完成全部检查。无counterexample但存在unsupported/error/未执行/清理不全则incomplete；只有全部计划已执行且全部passed才passed。
- traffic取必要发布来源，TESTING或synthetic语料不能归real；evidenceKind单列synthetic_fixture/deterministic_regression。不能用来源发布是real就声称用了真人标签/真实模型。

## 统计协议3：同快照、完整分母、明确缺口

Page/Export同步升格式3，cursor仍1（固定查询口径），DB5是另一个版本。新增发布后对象，旧格式2保留可识别unknown，不能把缺字段偷偷补成observed/0。

- `state=unknown`：无005或来源验证不可用，核心观测数null并给固定reason。
- 已接入时给sourceCoverageStart、historicalBackfill=false、窗口早于coverage标partial；observedRuns/plannedCases来自窗口内所有已登记计划，包含终态失败、不完整和pending，不只成功。
- 分别failedRuns/passedRuns/incompleteRuns/pendingRuns/pendingExpiredRuns；四种状态合计observedRuns，expired是pending子集。同时 attemptedCases/passedCases/counterexampleCases/errorCases/unsupportedCases/notAttemptedCases，严格验证总分母。
- 窗口按startedAt归属，跨窗口结束仍属于原计划；规则筛选按实际publishedRuleVersion，不按候选base版本。回滚后的观测保留历史对象。
- real与排除的test/synthetic/unknown分别公开聚合；默认主数字不含测试。没有真实观测可有0次活动，但绝不能呈现为0%错误率或质量达标；不计算语义准确率。
- 继承3秒读取deadline、短read snapshot、固定31天/100组/512KiB上限。聚合只读索引化标量/有界结构，不逐行加载玩家原文、不N+1逐条验证全私有候选。来源结构破坏必须unknown/固定503，不泄漏坏JSON，也不能忽略坏行后报零。
- 管理页解释“先发布，再复查”“运行失败与答错不同”“无观察不代表零错误”；清除token/筛选/卸载依旧abort+epoch fence。不在游戏页面轮询。

## 验收及外部HOLD

必须实际发布合成候选后执行新规则路径，抓到故意错误的**新发布版**，验证崩溃/并发/重放/回滚/完整分母/流量排除/来源损坏/无外网；这是本地测试证据，不是公开网站真实修复成绩。新005/格式3要通过既有游戏、审核、Agent、统计、迁移、恢复及发布产物兼容回归；一次整单元独立审查后只修必要问题。

真实语料、人审、免费provider质量、生产迁移/部署、真实观测数量、公开视频和用户数仍外部门禁。完成本设计或本地测试都不能签收这些项。TS18旧材料/原239数据/HEAD/index保持；旧proof保留，新源码身份与产物另存，不拿c34旧身份背书新代码。
