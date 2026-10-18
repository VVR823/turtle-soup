# 九张核心模块学习卡

先读[一次提问路线](project-learning-map.md)，再按 CM01–CM09 学习。这里解释业务、设计和已经发生过的失败；完整参数仍以链接的源码和接口参考为准。配套操作见[安全练习](practice-checklist.md)。

这些是 AI 辅助整理的材料，不是你已经独立实现、学会或上线的证明。历史 RED 指修复前测试确实失败，GREEN 指修复后对应测试通过；不是现在故意破坏成品。下文历史报告已重新读取，不把不同范围的测试数相加，也不把合成问题当真实模型成绩。

## CM01：配置与 Runtime，各实例各管自己的东西

**业务问题。** 测试如果读了真实密钥、写了玩家数据库，或者两个应用串用了缓存，会伤到真实用户。程序关闭后再偷偷创建模型客户端，还会留下没人收尾的工作。

**入口和关系。** [main.py](../../backend/app/main.py) 的 `create_app` 只建应用；进入 lifespan 才选择 [config.py](../../backend/app/config.py) 的 `Settings`、创建 [runtime.py](../../backend/app/runtime.py) 的 `Runtime`、初始化存储。请求通过 `runtime_context` 取得本实例，退出时 `Runtime.aclose` 收尾。测试显式用 `Settings.for_test`，默认 FakeModel、独立临时目录、不读 dotenv、不调用真实模型。

**为什么这样设计。** 配置像地址簿，Runtime 像这家店自己的柜台。不能所有店共用一个“当前数据库”。关闭入口和首次创建网关用同一把锁，且先标记关闭再等待清理。代价是要传递实例上下文；旧 CLI 的显式调用还有兼容路径，不能宣传所有调用都天然无全局状态。

**真实失败与修复。** TS03 曾在异步关闭尚未结束时允许首次创建网关。`test_runtime_rejects_first_gateway_creation_after_shutdown_has_started` 用暂停真正的 `aclose` 暴露窗口。修复后拒绝新建并报 `model_unavailable`。[原 RED](../../.cache/ts03/review-red.xml) 中该用例确实失败；[阶段 GREEN](../../.cache/ts03/review-green.xml) 为83通过、2平台跳过。

**怎样验证/独立练习。** 运行练习表 CM01；自己在隔离练习副本增加“反复关闭不再新建资源”的控制，解释为什么“已发起关闭”和“已经清理完”不同。不得把关闭中占位说成供应商远端推理已取消。参考[测试实例契约](../test-runtime.md)。

## CM02：HTTP、整轮事务和原请求恢复

**业务问题。** 玩家断网时，服务端可能已经保存答案。盲目重试会再调模型、再扣次数；直接返回损坏的旧响应则可能泄露私有信息或串局。

**入口和关系。** [request_contract.py](../../backend/app/request_contract.py) 的 `StrictJSONRoute` 拒绝重复 JSON 字段；[main.chat](../../backend/app/main.py) 检查场景/权限，调用 [game_service.ask](../../backend/app/game_service.py)。后者经 `db` 兼容入口调用 [game_store.reserve_turn/finish_turn](../../backend/app/game_store.py)，已结束请求返回 `TurnReplay`；保存响应由 [game_responses.py](../../backend/app/game_responses.py) 严格解码。前端 [game-journal.ts](../../src/lib/game-journal.ts) 保存原请求编号，[game-controller.ts](../../src/lib/game-controller.ts) 负责同步。

**为什么这样设计。** 同编号同内容是同一件事；同编号换内容冲突，新编号才是新提问。模型工作放在两段短事务之间，不一直锁住数据库。保存消息、计数、结果和恢复响应一起提交；租约、token、行版本和终态拦住迟到结果。代价是存在明确的“处理中”状态，不能把任何超时都当作从未发生。

**真实失败与修复。** TS04 原恢复路径能返回夹带私有字段或另一局的有效响应。永久 `test_saved_turn_rejects_unknown_private_fields`、`test_saved_turn_rejects_another_sessions_valid_envelope` 等先失败；修复白名单及局/轮/状态/计数绑定，不删除历史。[RED](../../.cache/ts04/review-red.xml) 14失败/3控制通过，[GREEN](../../.cache/ts04/review-green.xml) 88通过，范围不同。[处置说明](../ts04-status.md)。

**怎样验证/独立练习。** CM02 同时检查损坏响应拒绝和成功/失败原响应重放不增加调用。自己加一个“相同文字、新 requestId”的独立控制，并写出预期计数。游戏次数、模型调用次数、token 消耗不是同一个数。[恢复取舍](../game-recovery.md)。

## CM03：类型、事实、规则和缓存，不靠关键词硬猜

**业务问题。** “不是”里也含“是”；“前者是凶手吗”离开前文没有固定答案。缓存如果忽略上下文或版本，会把错误答案快速重复给很多人。

**入口和关系。** [schemas.HostResult](../../backend/app/schemas.py) 限定答案/提醒/失败的合法组合；[model_gateway.py](../../backend/app/model_gateway.py) 处理有限尝试，`ai_host.handle_host_response` 编排主持。事实在 [host_evidence.py](../../backend/app/host_evidence.py)，规则在 [host_rules.decide_deterministic](../../backend/app/host_rules.py)，缓存在 [host_cache.py](../../backend/app/host_cache.py)。精确键用 [question_normalization.py](../../backend/app/question_normalization.py)，检索到候选证据不代表有权直接给答案。

**为什么这样设计。** 只接受约定的五类回答，不从乱文里捞一个“是”。规则须覆盖完整命题及条件；指代/未知正常回退模型，不把普通问法一律报异常。缓存只收有证据、独立于上下文的确定性结果，键含题目/规则/引擎/规范化版本，最多1024项、插入后600秒过期；不缓存局的剩余次数。代价是命中率更保守，真实质量仍需人工标签/独立评测。

**真实失败与修复。** TS06 的指代问法曾被当作静态规则，两个不同前文的局得到同一错误捷径答案。`test_authored_reference_needs_opposite_history_judgment` 等先失败；完整范围检查改在捷径/缓存之前。[RED](../../.cache/ts06/review-regressions-red.xml) 15失败/3控制通过；[组合 GREEN](../../.cache/ts06/review-regressions-green.xml) 329通过。[规则与缓存说明](../ts06-status.md)。公开搜索只用标题/汤面/标签，不搜索私有汤底。

**怎样验证/独立练习。** CM03 保留普通模型路径。自己增加一个前文指代反例或否定精确键控制，预测模型调用量和缓存资格。格式合法但事实上答错，格式校验不会自动知道；不要把证据检索、程序校验或 FakeModel 当万能裁判。

## CM04：评分与独立评测，未知不是零

**业务问题。** 8题中2题接口失败，只拿返回成功的6题算准确率会藏起失败。“碰到剧情关键词”也不等于还原真相。

**入口和关系。** 游戏的 [game_service.evaluate_snapshot](../../backend/app/game_service.py) 调用主持评分，[scoring.score_confirmed_coverage](../../backend/app/scoring.py) 只用已提交的类型化轮次与固定题目版本；`verifiedCoverage`、`plotProgress` 分开，`reconstructionScore` 当前为 `null`。独立实验由 [eval/runner.py](../../backend/eval/runner.py) 生成每个计划样本的记录，再由 [eval/metrics.compute_metrics](../../backend/eval/metrics.py) 算完整分母；报告/清单/对比不是同一个对象。

**为什么这样设计。** 错答、非法输出、接口失败、未尝试都留记录。标准答案用于最后算分，不先放进被测模型上下文。没有 token 观测写未知，不写0。代价是指标可能更难看，但可以解释失败去了哪里；覆盖率和合成测试不能宣传为真实模型准确率或完整叙事还原能力。

**真实失败与修复。** TS12 普通 Ctrl-C 曾让运行器直接退出，丢掉已做样本及后续计划分母。`test_cancellation_preserves_previous_current_and_remaining_cases_without_zero_guess` 先失败；修复取消记录/清理及不确定调用数，完整报告标为不完整。[真实行为 RED](../../.cache/ts12/review-regressions-behavior-red.xml) 31失败/3控制通过包含该反例；[处置及最终证据](../ts12-review-resolution.md) 不把首次测试捕获错误当产品缺陷。

**怎样验证/独立练习。** CM04 同时跑取消反例和 `test_all_eight_decisions_and_error_column_enter_literal_denominator`：手算合成3/8而非3/6，不是模型成绩。自己给合成矩阵加一条失败，先手算新分母、错误率和未知用量，再加断言。[评测参考](../evaluation-runner.md)。

## CM05：反馈、隐私与审计，三个许可不能混用

**业务问题。** 玩家说“你答错了”只是主张；管理员认可反馈，不等于允许把原文发给模型，更不等于已经发布新规则。

**入口和关系。** [routers/feedback.py](../../backend/app/routers/feedback.py) 分别提供提交、批准/拒绝、隐私许可；[feedback_store.py](../../backend/app/feedback_store.py) 的 `submit_feedback/review_feedback/set_model_permission` 在 SQL 事务内检查行版本、保存必要审计。模型使用脱敏的许可投影，默认 `safeForModel=false`。业务审计与 [audit_middleware.py](../../backend/app/audit_middleware.py) 的 HTTP 尝试记录分开，重试的请求条数不等于多完成了几轮游戏。

**为什么这样设计。** 使用预期行版本，旧页面不能覆盖新修改。必要审计失败时业务一起回滚，辅助观测失败则不能伪造完整覆盖。代价是管理员要分别核对语义、隐私和后续发布；撤回本地许可不能保证供应商删除之前已收到的数据。

**真实失败与修复。** TS10 曾接受纯空白的必填反馈，随后阻断整页管理。新提交拒绝空白；旧记录保留、允许人工拒绝/撤回，不用批准把坏记录变合法。`test_new_required_blank_fields_are_rejected_before_feedback_write` 等在[真正 RED](../../.cache/ts10/review-i1-backend-verified-red.xml) 16失败/5控制通过，[GREEN](../../.cache/ts10/review-i1-backend-final.xml) 23通过。[完整裁定](../ts10-review-resolution.md)。

**怎样验证/独立练习。** CM05 不调用模型、不删旧负载。自己增加“反馈批准后仍没有模型许可”的合成控制，解释为什么还不能自动公开或发布。不能把玩家原文/密钥粘进练习或审核备注。[反馈规则](../feedback-rules.md)。

## CM06：Agent 选择工具，服务端保留决定权限

**业务问题。** Agent 可能重复调用、无限修复、重启后恢复预算，或在许可已经撤回时仍把材料发出去。

**入口和关系。** [agents/repair_agent.py](../../backend/app/agents/repair_agent.py) 的 `RepairAgent` 读取持久步骤，构建提示、预留决策、通过网关调用模型，再提交类型化决策。模型只能选择 [tool_contracts.py](../../backend/app/agents/tool_contracts.py) 白名单工具或结束；[tools.py](../../backend/app/agents/tools.py) 执行，`AgentStore` 管权限/租约/预算/步骤，[worker.py](../../backend/app/agents/worker.py) 管启动与恢复。不是模型直接执行 Python/SQL。

**为什么这样设计。** 五个工具是 `get_turn_trace`、`retrieve_truth`、`find_rule_conflicts`、`run_regression`、`save_candidate_rule`。模型决策尝试最多10、工具尝试最多8，重启沿用原期限与已花预算；步骤先登记再执行。失败也可能已经花了一次尝试，不能靠重启退款。代价是某些不确定步骤交给人处理，而不是自动无限重做；单机限额不是跨机器容量或 SLA。

**真实失败与修复。** TS14 曾在预留后等待适配器、期间撤回来源，却仍实际发出一次 Mock HTTP。`test_source_is_rechecked_after_adapter_construction_before_dispatch` 在[RED](../../.cache/ts14/review-i4-red.xml) 中撤回分支失败、正向控制通过。修复 `before_attempt`：真正发送前重查同一已花意图、来源、租约与停止信号；不再预留一次。[GREEN](../../.cache/ts14/review-i4-green.xml) 82通过，[完整裁定](../ts14-review-resolution.md)。

**怎样验证/独立练习。** CM06 预期撤回后发送0次、已花尝试仍为1，不是“完全没发生”。自己增加无撤回的控制或暂停后恢复预算控制，记录状态变化，不恢复已撤权限。参考[循环](../agent-loop-reference.md)、[工具](../agent-tools-reference.md)。Fake动态选择不证明真实模型能做同样决策。

## CM07：候选、人审、发布和回滚是四件事

**业务问题。** 回归全绿的候选也可能语义错误；看详情后证据又被撤回；把“批准”按钮直接当发布会绕过最后检查。

**入口和关系。** [routers/admin_candidates.py](../../backend/app/routers/admin_candidates.py) 鉴权后调用 [CandidateReviewStore](../../backend/app/candidate_review.py) 的 `detail/approve/reject/publish/rollback`。详情提供固定原问题/此前对话与脱敏输入的区别；批准要求人审确认，发布另有操作凭据、基线版本检查，再调用 [rule_publication.py](../../backend/app/rule_publication.py)。新会话取发布指针，旧会话固定自己的版本。

**为什么这样设计。** 模型只保存待审候选，不能批准自己。服务端重新核验真实保存的报告/规则/题目/语料身份；回滚移动规则指针，不删除玩家新写入或审计历史。代价是需要人确认语义、独立原始上下文及单独发布。hash 只证明内容一致，不证明真人标签、权限或真实准确率。

**真实失败与修复。** TS15 在必要审计写入后撤回/替换语料或改变代码身份，曾仍能批准/发布。`test_non_db_authority_change_after_necessary_audit_rolls_back_the_whole_mutation` 六反例在[RED](../../.cache/ts15/review-i2-red.xml) 确实失败。修复最终提交同连接复核及受支持语料替换共锁，整笔 SQL 回滚；[GREEN](../../.cache/ts15/review-i2-current.xml) 92通过。[处置](../ts15-review-resolution.md) 同时说明源码热改不受跨文件系统原子锁保证。

**怎样验证/独立练习。** CM07 检查整库状态不变，不只检查HTTP错误码。自己加“批准但未发布，指针不变”的控制，或解释新旧局/回滚后的版本差别。不得使用真实后台按钮做练习。参考[候选契约](../candidate-review-reference.md)。

## CM08：私有统计必须讲清数据来源

**业务问题。** 空统计页显示0，可能真的没有失败，也可能根本没接采集。两者对管理员的含义完全不同。

**入口和关系。** [routers/metrics.py](../../backend/app/routers/metrics.py) 的 `metrics_page/metrics_export` 调用 [metrics.query_metrics/export_metrics](../../backend/app/metrics.py)，由 [metrics_contracts.py](../../backend/app/metrics_contracts.py) 校验，前端 [MetricsPanel.tsx](../../src/components/MetricsPanel.tsx) 显示。当前统计 Page/Export 版本3、游标版本1、基础统计迁移004/发布后观测迁移005，版本号各自有含义，不是一套递增开关。

**为什么这样设计。** 已有事件按明确窗口/题目/题目版本/规则版本分组，真实与测试口径分开。D18已接入本地显式发布后固定复查、005不可变账本及完整四状态/案例分母；只有管理员动作触发，不加玩家问答或Agent自动调用。未启用005为 `unknown/schema_5_required`，必要来源损坏为 `unknown/source_unavailable`，计数都为null；已知真实观测0也不证明零错误。v2兼容只接受其原明确 `unknown/source_not_integrated` 对象，不能把v3观测冒充v2。完整导出只保证分组完整，不保证模型语义质量；不能拿发布前回归或Agent失败数替代发布后观测。

**真实失败与修复。** TS17 的旧继承校验器只接受1，使默认v2页面在完整导出时反而被拒绝。`test_private_v2_page_can_be_revalidated_before_complete_export` 和实际导出反例在[补充 RED](../../.cache/ts17/metrics-source-revalidation-red-2.xml) 2失败/12通过。校验改为模型声明的精确整数版本，布尔/字符串/浮点/旧版本仍拒绝；[记录](../ts17-metrics-source-qa.md)保留失败与当前全套证据。

**怎样验证/独立练习。** CM08核对当前v3页面/导出重校验及005缺失仍null；另读 `test_protocol_three_counts_complete_cohort_not_only_successful_results`，看成功、反例、不完整、待完成全部进入分母，test不混进real。自己为“已知零计数”和“未知来源”写不同断言。上一段v2失败是当时的历史证据，不是当前wire版本。后端默认可补未知对象、前端外部响应严格要求字段的原Minor仍保留，不能声称所有省略字段都被后端拒绝。见[当前A57证据](../acceptance-a57.md)和[口径参考](../metrics-reference.md)。

## CM09：代码产物、最新数据和恢复演练

**业务问题。** 直接复制SQLite主文件可能漏掉 WAL 中已提交数据；拿发布前备份覆盖回来，会丢掉上线后新玩家的局。

**入口和关系。** [test-backend-release.mjs](../../scripts/test-backend-release.mjs)、[test-standalone-release.mjs](../../scripts/test-standalone-release.mjs) 是现有命令入口，分别调用 [后端产物策略/验证器](../../scripts/backend-release-policy.mjs)、[前端产物策略/验证器](../../scripts/standalone-release-policy.mjs)；这里不再次构建产物。[snapshot_recovery.py](../../backend/app/scripts/snapshot_recovery.py) 的 `backup/restore` 通过 SQLite backup API、完整性/版本/辅助文件摘要检查恢复到全新目录。停写者盘点由 [recovery_quiescence.py](../../backend/app/scripts/recovery_quiescence.py) 单独表达；包通过校验不能代替实际运行兼容性。

**为什么这样设计。** 代码、私密配置、玩家数据分离。新写入后先保留最新一致性数据，再退规则/功能或切已验证兼容代码；未知旧代码保持维护，不承诺能继续写。只恢复到新路径，不覆盖源。代价是多一个演练目录和明确兼容矩阵，不承诺任意旧版本“秒回滚”。

**真实失败与修复。** TS17 原来只检查源未变，复制出来的辅助文件被破坏也会报成功。`test_recovery_detects_corrupted_auxiliary_copy_not_just_unchanged_input` 的backup/restore两分支在[RED](../../.cache/ts17/recovery-copy-red.xml) 确实失败（另43通过、4权限跳过）。复制后逐文件校验，不匹配拒绝且不生成成功报告；当前[最终全套 XML](../../.cache/ts17/review-fixed-whole-sequential.xml)含这两个通过用例。

**怎样验证/独立练习。** CM09 的复制破坏只发生在测试自有目录。自己增加“目标已存在时哨兵文件不能改变”的控制，或在最新数据演练测试中增加一条合成业务记录。禁止对 `backend/data`、真实服务器或旧备份直接运行恢复。参考[恢复操作与兼容矩阵](../release-recovery.md)。Linux/Docker、真实线上停写/部署及完整生产恢复仍未验证。

## 学会的标准

能指出入口和实际调用关系、解释一种代价、预测反例结果、独立补一条测试并看懂失败原因，才记录为“本人掌握”。原工程报告和本次材料核验只能证明工程/材料状态，不能替代你的练习。按[练习记录格式](practice-checklist.md)留自己的证据；公开范围仍受[公开前盘点](../publication-preflight.md)限制。
