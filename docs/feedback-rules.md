# 反馈与规则升级（TS10，本地实施中）

Tasks1–5、唯一独立审查及一次Important修复已完成本地门禁：1511离线通过/10skip、29真实UI通过。以下能力是本地代码，不代表已部署，也不是已运行Agent。最新证据与限制见[TS10状态](ts10-status.md)。

## 反馈不是正确答案或授权

玩家的question/hostAnswer/expectedAnswer/reason只作为私有主张保存，“不知道”不改成“与此无关”。新反馈pending、rowVersion=0、safeForModel=false。全局手填表单未关联真实turn时sourceState=unverified；提供turnId必须核对真实对局、问题、展示回答、已保存typed结果和固定版本，不借同汤其他记录补来源。

FeedbackView/Review/Page采用严格、冻结字段。审核要求expectedRowVersion，旧页面409/feedback_version_conflict不能覆盖新决定；更新后的状态、版本、时间来自服务器。即使approved也不自动成为正确规则或云调用许可。提交/审核/必要审计同一原子事务；日志正文只含固定ID/版本/摘要/来源状态，不复制玩家文本进尝试日志或stderr。

列表默认50/max100、默认最近7天/max31天。规范cursor固定首屏时间窗口，status省略可继承；soup_id过滤以摘要绑定，下一页必须重复同一soup_id，改动/漏传拒绝422。这样200字中文ID也不会撑破512字符游标。totalInRange是本轮有限时间范围内计数，不声称全部历史/独立用户数。

## 旧文件只在显式副本演练

`app.scripts.import_feedback`必须指定绝对source/target/report。source是停写的隔离副本，已有sessions.db必须已登记002，且存在feedback.jsonl；不会替生产旧库自动迁移。先按迁移指南制备自有002副本，再对该副本演练。target必须全新且与source/report不重叠；拒绝真实运行数据、祖先目录、路径别名和配置文件目标。测试从未读取真实feedback.jsonl。

文件≤100MiB、≤5000物理行，每行≤32KiB；超过总预算整组拒绝，不偷偷接受前半批。读取使用有界块并核对文件摘要、size/mtime/inode；源变化拒绝。坏JSON、UTF8、未知字段、时间或尾行只报告行号、摘要和有限原因码，源原样保留，报告不含玩家原文。

UUID5基于完整源文件摘要+物理行号+行摘要；同旧ID不同问题、甚至重复物理行都保留独立来源。重复同文件导入幂等，不覆盖后来的审核；相同生成ID而私有负载/来源冲突整体拒绝。来源保留原ID摘要、行摘要和旧审核/合并历史，但不推导turn、不自动授safeForModel，不把mergedAnswer当成新发布规则。badRows报告不是原文件替代。

导入写入与feedback_imported审计同事务，审计/commit失败回滚。CLI使用临时DB/WAL副本读取源SQLite，不在源目录创建SHM；未checkpoint WAL/SHM字节保全有合成控制证据。dry-run仅内存演练+全新私有报告，不创建target；正常返回0，坏行需人审返回2，拒绝/失败返回1。失败留下新输出供检查，不删除/覆盖任何原来源，productionReady始终false。

这些是停写副本前提下的本地保障，不是实时/多worker备份、物理断电耐久或生产迁移签收。Windows符号链接实测目前缺权限，测试跳过，不改ACL或声称跨平台通过；路径解析边界另有独立故障注入回归。所有模型/人审/线上指标未验证，不新增费用。

## 人工许可与冻结证据（辅助实现，不执行Agent）

管理员必须显式确认reviewedForPrivacy，给出完整sanitizedQuestion/HostAnswer/ExpectedClaim（Reason可null）以及1–1000字审核理由，才能设置safeForModel=true；不能用正则“看起来干净”自动授权。原payload_json保持私有原样，source_json.privacy单独存严格PrivacyRecord、脱敏输入、摘要、UTC审核时间和审核版本。许可变更要求expectedRowVersion，CAS/更新/审计同事务；撤回增加版本、不删除原反馈。

TaskContext只允许approved、safeForModel且当前人工许可版本匹配、可靠typed turn关联的反馈。旧/手填无Trace即使手动许可也needs_human，不借其他turn。冻结时重验实际问题/显示答案/结果摘要、p1/观测r1与当前待发布基线，题库变化不隐式换事实。

脱敏输入、反馈版本、turn/soup、观测p1/r1、当前baseRuleVersion、完整事实范围和五种允许工具冻结成不可变对象。每次未来入口再次核对数据库权限、版本、范围和停版；撤回、改审核、停版、换题库或伪造scope/model_copy会停止下一步。NeedsHuman为稳定受控原因，不输出源异常、私密原输入或模型reasoning。

固定工具只有get_turn_trace/retrieve_truth/find_rule_conflicts/run_regression/save_candidate_rule，无shell/任意路径/任意工具权限。事实范围最多256条、单条payload最多32768字符、完整context最多256KiB；超限明确转人工，不静默截断成“完整证据”。事实由原可信题库证据目录生成，不来自玩家expectedAnswer。可信题库不意味着所有生成内容已完成人工隐私审查；完整云发送政策与账户资格仍是后续外部门禁。

这不是已运行Agent：没有003/run API、云调用或自动发布，Synthetic manual confirmation只验证流程，不是现实人审证明。撤回仅阻止后续入口，不能撤回已发出的外部请求；进程内任意恶意代码、直接改数据库或绕过程序不能被这些Python合同完全沙箱化。

Task3最终离线门禁为1316通过/10跳过；其中人工许可/冻结证据39项。报告为`.cache/ts10/context-final-full-gate.xml`，原239个运行文件摘要未变。此门禁不是HTTP/后台改造或整个TS10的完成证明；规则发布与页面接线继续实施。

## 规则快照与内部发布（Task4部分实现）

原schema1/p1题库与旧版本内容不改。schema2在原rulesBySoup旁保存exactQaBySoup，完整父版本、p1、来源、规范化键、事实ID和冻结审核记录都参与r1摘要。RuleSnapshot携带完整不可变JSON证明而非只有一条答案；每段最大2MiB，在主持与缓存使用前重新验证，防止model_copy修改投影。

RulePublisher必须由可信服务端代码提供authorizer；不存在默认放行或TESTING绕过。审核回执绑定候选/完整草案/报告ID与摘要/回归套件/p1/r1/人审理由/明确确认；并不意味着程序能自动判断这条回答在语义上一定正确。应用目前不创建此发布器，也没有公开发布API；仓储审核接线仍属TS15。

发布在同一BEGIN IMMEDIATE事务核对指针版本，写不可变新版本、CAS切指针、记固定业务审计和operationKey；任何一步失败整体回滚。相同操作且相同完整材料重放原结果，换请求/报告/回归套件拒绝冲突。测试中的审核材料全是自有合成记录，不冒充真实人工标注。

add不允许覆盖现有明确回答；replace只允许唯一精确QA或独立完整ConfusionPoint.q/a来源，摘要绑定完整原始字段/位置/p1/base r1/规范化，而非只认问题字符串或正则。原Checkpoint/计分事实不修改，模糊、多目标、指代或条件问题不能自动发布为通用规则。

新游戏选择新指针；旧游戏保持原版本。主持只在全句exact-v1匹配时应用附加规则，其他正常问法继续原规则或模型；游戏流程、剧情通关保持优先。缓存按r1隔离，即使内部旧调用曾以新r1但无overlay填入缓存，真实完整补丁仍优先，不让旧答案覆盖它。

Task4内部回滚、停版写入和游戏事务提交围栏已通过233项定向及完整离线门禁，完整后端1191通过/10跳过，报告`.cache/ts10/rule-final-full-gate.xml`。Task5页面接线、唯一独立审查及一次修复后的阶段本地门禁完成；最终后端1252通过/10skip、全离线1511、真实UI29，详见状态文件，不宣称上线。

新反馈的soupId/question/hostAnswer/expectedAnswer不能仅空白；有意义主张及可选空理由仍可提交。私有有界历史空白记录不删改、不拖垮列表，显示人工核对提示；不能通过或授予模型许可，仍可按服务器版本拒绝/撤回（含已approved项）。显式旧导入列为badRows并保留原文件，绝不归一成正确答案。

回滚只切到完整可核验且未停用的旧版本，不修改会话/消息/旧版本内容。可在同一事务显式停用刚被回滚的错误源版本；回滚目标不能同时被停用。重放操作不再切一次指针，换理由/参数触发冲突；审计或commit失败时，切指针与停版一起撤回。

显式停版要求expectedMarkerVersion：首次不存在为null，首行版本为0，此后每次更新加一。同operationKey重放不重复审计；停版与解除必须有明确短理由，不靠切指针自动解决全部旧局。现有正在玩这版的对局不能新增提问/揭晓；模型晚到结果也在原提交事务被拦截，不扣次数、不保存新问答，仍可读取历史、原UUID响应与释放过期预留。已有结束评估保持可显示，明确解除后可按原版本继续。

原嵌入式create_session入口也在同一BEGIN IMMEDIATE事务里选择指针和检查停版，不能绕过正常开局的限制。GET会话已返回ruleSuspended；前端缺省旧字段为false，存在却非bool则拒绝。暂停时禁用新问/揭晓/自动揭晓，但保留历史、会话指针和待处理UUID；不自动换局。管理员明确解除后，玩家手动检查/同步，未提交的原请求仅以同一UUID恢复，已完成请求不再重复扣次数。

## 当前HTTP与后台合同

- POST `/api/feedback` 接收原问题/回答/玩家主张/可选理由及turnId，返回仅`{ok,id}`。soupTitle由服务器题库生成，不接受客户端伪造。手填反馈没有turnId，不假造真实模型错答来源。
- GET `/api/feedback/admin` 需独立管理口令；`limit/start/end/cursor/status/soupId`界定有限窗口。返回`feedbacks/totalInRange/nextCursor`。后台按游标加载，不把已加载状态过滤误称全历史筛选；可选空理由/空标题合法，界限与后端一致。
- POST `/api/feedback/admin/{id}/approve|reject` 必须发送`{expectedRowVersion}`；响应`{ok,feedback}`是服务器真实版本/状态/时间。后台没有乐观伪审批时间，旧凭据/旧请求迟到不能覆盖新页面。409需刷新核对，不自动复审。
- POST `/api/feedback/admin/{id}/privacy` 需独立管理口令和当前expectedRowVersion，授权时必须完整人工检查并提供脱敏输入/理由；撤回保留原主张与审核审计。后台尚无批量/自动隐私授权，也不默认把approved送给模型。
- 原 `/api/feedback/admin/merge-verified` 认证后410；没有公开候选发布、回滚或停版API。内部发布仍需可信仓储authorizer，TS15负责后续接线，不通过这个页面越过它。

## 运行题库与显式迁移边界

正常Runtime不再读取verified_qa.jsonl注入规则。有已登记002数据库时读取不可变基线，即使旧文件坏了也不偷偷替换。没有sessions.db却存在旧feedback.jsonl或verified_qa.jsonl时，启动拒绝并要求显式副本迁移，哪怕禁用了LOAD_RUNTIME_PUZZLES也不丢弃旧历史后新建库。

只有显式迁移catalog保留include_legacy_verified以维持旧来源语义；原001/002 SQL/checksum/backfill没改，原文件没删没自动迁移。旧反馈重复导入仅比较不可变物理来源和原主张，后来的有效隐私审核/撤回/复审仍原样保存；新增未知来源字段或坏脱敏摘要仍整体拒绝。

## 证据与尚未完成

测试中的“人工确认”、暂停和审核全是合成材料，仅验证程序流程。真实人审、真实模型质量、免费账户资格、多worker生产拓扑、线上迁移/部署未验收。反馈内容、管理读取和脱敏前材料均属私有，不公开上传。

真实UI使用现有Edge与两条自有loopback origin。仅`app.test_server.fixture_app`的显式UI模式注册nonce保护的合成停版setup；普通create_app（即便TESTING）与API-only fixture都404。它要求fake模型/禁真实模型/测试模式/本次实例nonce，没有候选发布权限；不允许生产服务器开启此入口。当前门禁与独立审查状态见[TS10状态](ts10-status.md)。
