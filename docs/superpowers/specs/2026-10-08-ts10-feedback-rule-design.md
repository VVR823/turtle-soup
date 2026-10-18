# TS10 反馈事务化、冻结任务证据与规则版本内部发布设计

## 意图、授权与前置门禁

用户的目标是零新增付费成本、真实网站不断档、可讲清楚的 AI 应用/Agent 求职项目。原 TS10/A37–40/C17–18/D6/D7/D11/8.5/8.6 是绑定规格；人类明确授权本地设计、计划、自审与实施自主连续推进，不重复阶段确认、不提交/部署/公开上传，不迁移真实用户数据。

本设计属于架构型。TS09唯一独立审查 Raman 正在运行，48文件/HEAD/index冻结。当前只能读源码与写本阶段独立设计/计划/ledger；TS10测试或产品代码必须等TS09终态、一次重要修复和最终门禁之后。TS09的反馈表已注册，不表示反馈迁入、Agent权限或候选发布完成。

成功标准：并发提交/审核不丢反馈，陈旧row_version拒绝；JSONL只显式隔离导入/导出，坏行/重复ID有溯源且源保留；未人工脱敏许可不能进入未来云工具；规则内容不可变，active pointer与审计同事务，新旧游戏按各自版本运行，显式停版挡住旧局新操作及在途结果提交，历史不被清掉。只验证合成/FakeModel，不制造真实人审/真实模型/线上证明。

## 实际源码与方案选择

main当前反馈提交append JSONL；管理员读全文件并全量改写，审核无版本条件，expectedAnswer自由文本被legacy normalize_expected_answer宽松归一化；旧merge入口已410/停用。FeedbackButton是全局手填表单，现无可靠turn关联，不能拿同汤任意记录补造来源。后台页面未带rowVersion、直接本地修改审核状态。002已有feedback_items与audit_events，两checksum不可改。

001 puzzle_versions与rule_releases触发器不可变；baselines目前只识别schema1，rule字段必须等于原Soup，host_evidence还校验完整Soup与p1摘要。直接给旧Soup加动态字段/修改confusionPoints会破坏快照与证据绑定，不能用“重启加载verified_qa”发布新规则。在线纯缓存已经按题库、规则、引擎、规范化与精确question key分隔。

推荐复用M2事务表、独立反馈/任务/发布小模块，schema2的规则快照保存附加exact_qa，不改原puzzle/Soup或001 SQL；旧schema1读取保持原样。另选项：给JSONL加文件锁能缓解本地覆盖，但无法与DB审计/指针原子提交；新外部DB/队列会增加部署维护，当前零成本单实例不需要。未来不是以单实例假称多机可靠。

## 1. 新反馈与审核

feedback_store负责短事务；提交保留原公开字段，追加可选turnId。所有新反馈status=pending/safe_for_model=0/row_version=0，玩家不能指定审核、许可、版本、来源或Agent权限。拒绝未知soup，不把匿名soupId当用户身份。没有turn仍可反馈，但标记unverified/missing_trace，只能人审。

提供turnId时，事务核对turn的真实session/soup/puzzle/rule、状态与已保存typed结果；问题/展示回复不一致拒绝关联，不以模型/玩家自报版本为真。原question/hostAnswer/expectedAnswer/reason保存在私有payload_json，关联快照保存在source_json，公开只返回ok/id。expectedAnswer只是主张，“不确定”不转事实“与此无关”。新表写入与feedback_submitted审计同事务，失败整体503且不新增半条反馈。

管理员列表是受控分页/时间窗，默认50/max100、7/max31天，稳定(created_at,id)cursor；返回rowVersion与许可状态，不无界读JSONL。所有状态更新要求expectedRowVersion，原子CAS并审计；陈旧409/feedback_version_conflict，重复相同决定在同版本下有明确规则，不能静默以最新版本覆盖。approved只是反馈处理状态，不等于候选语义已确认、不自动发布、不自动授云权限。

已有后台页面最小同步：带服务器rowVersion提交、使用服务器返回的状态/版本/时间，冲突保留当前列表并要求刷新；加入有界分页/范围提示，不能将第一页说成所有历史。完整候选人审与发布按钮仍TS15，不提前开放。全局玩家表单维持现体验，不擅自推断turn。

## 2. 显式旧JSONL导入

不在启动时自动导入生产文件，也不读真实JSONL作测试。显式隔离入口拒绝运行data/祖先路径、重叠/已有输出、符号链接别名；源必须已人工确认并停止写入的副本。每行读取有字节限制、总记录限制；JSON严格解析，未知字段/坏时间/坏行/缺关键内容形成安全报告（行号、原ID摘要、源文件/行hash、原因码），不打印原文本。原文件不改名/删除/覆盖，报告不是原记录替代。

导入每个物理来源行的程序UUID5基于sourceFileDigest+lineNumber+lineDigest，原feedbackId单独留source。相同文件重复导入幂等；相同旧ID但不同问题/答案/来源行分别保留，不互相覆盖或合并真值；完全重复行仍保留来源计数，不隐藏异常。旧approved保留其历史状态标签，但safe_for_model仍false，缺可靠turn/Trace仍missing_trace。输入改变拒绝本轮，坏行报告/源hash可复核，所有目标写入遵守M2与事务审计。

数据库是运行权威源，旧_get/load/save JSONL路由退役；旧merge/shim/cleanup保持停用，模拟定时触发零写/零删除。运行时不再把verified_qa_pairs.jsonl注入Soup；显式旧迁移的catalog loader独立选legacy_verified输入以保留原旧来源语义，不改001 backfill/旧报告。新空应用目录若遇旧verified规则/反馈待迁入，不自动拿它们发布成新规则或删除它们，明确要求隔离演练。真实cron/timer盘点、源迁入生产与部署保留外部权限门禁。

## 3. 人工许可与TaskContext（不执行Agent）

独立FeedbackPrivacyReview请求要求expectedRowVersion，管理员显式提交裁剪/脱敏后的完整输入，确认已检查身份/联系方式/私人信息与是否授权用于模型。safeForModel=true不是正则扫描自动通过，也不自动证明语义正确；原输入私有保留，审核后sanitized输入与hash/审核版本入payload，许可改变使row_version增加并审计。撤回许可不删除历史，不谎称已发出的云请求可以撤回。审核入口只存数据，不做云调用。

task_context纯受控冻结辅助在短读事务核对反馈版本、许可、可靠turn/soup/p1/r1/typed结果与当前待发布基线。没有可靠Trace、身份/私密未审核、source损坏、题库版本不同或任何未知都needs_human/稳定原因，不能借另一个turn补齐。observedRuleVersion与baseRuleVersion可以不同但puzzleVersion必须相同；显式保留旧观测，不静默换事实。

TaskContext是frozen/extra-forbid/version1，保存feedbackId/sourceFeedbackVersion/sanitizedInput/inputDigest/turnId/soupId/observedPuzzleVersion/observedRuleVersion/baseRuleVersion与固定事实/回归/工具允许范围。模型不能修改这些字段，伪造other turn/soup/version/path/tool拒绝。每次未来工具/模型新尝试前重新验证源版本/许可/停版/快照；已开始外部请求仍可能在途，此处仅能挡后续调用。TS13/14才持久化run与执行循环，这里不引用003、不开agent-runs API或声称已有安全云轨迹。

## 4. 不可变规则快照与内部CAS原语

旧schema1读取与摘要不变。新schema2 rules_json含原rulesBySoup（必须仍等于p1中的完整RULE_FIELDS）与exactQaBySoup；manifest含同一puzzleVersions、受控origin与parentRuleVersion，父列必须匹配。仍用内容寻址r1:摘要（它是ID格式，不是payload的schemaVersion），包含所有操作/问题/答案/factIds/规范化/批准与报告绑定，不用创建时间修改内容。原p1/Soup不增加字段、不改hash，原release从不UPDATE/DELETE。

RuleSnapshot与Soup并列，host显式接收可选validated snapshot；无附加规则时旧调用签名仍可用。published exact_qa使用exact-v1键、五类答案、实际p1事实ID、独立上下文确认，不允许regex/模糊匹配/外部执行/改事实。保留特殊剧情/游戏流程优先级；只有验证的全句key命中附加规则，其他正常问法继续旧规则或模型，不变成格式异常。命中HostResult的source/evidence/ruleId/versions都由程序生成，缓存按所属r1隔离，评分继续按事实依据而非显示文本。

内部publication原语仅接受受控已审核材料、expectedRuleVersion/expectedPointerVersion与operationKey（程序UUID），不开放HTTP发布。RulePublisher构造时必须传服务端authorizer，authorizer使用同一conn核对并返回strict frozen ReviewReceipt；不存在默认放行、TESTING绕过、模型选择回调或未配置时自动批准。receipt绑定draftDigest/candidateDigest/reportId/reportDigest/suiteManifestDigest/p1/base r1、answerSupported=true/contextIndependent=true与1–1000字人审理由，且完整状态非截断/非incomplete。发布重新计算材料摘要，与receipt逐项比较。TS10测试注入程序拥有的synthetic记录authorizer，并测试正文/报告/确认被替换时拒绝；不是新生产审批入口/真实人审证明。TS13/15才用真实candidate/report/approval仓储实现authorizer，阶段10不引用003；app不创建自动发布器。

add的相同/相反重复与覆盖冲突拒绝。replace必须同canonical question key、当前唯一旧exact规则的完整targetRuleDigest；对模糊、多重、跨规则类型、未独立上下文无法确定的目标needs_human，不删任意规则或覆盖事实。明确支持两种目标：schema2已发布exact_qa；原ConfusionPoint.q/a的完整来源绑定（只有独立全句精确key，完整sourcePath/sourcePayload/p1/base r1/normalization参与摘要，match正则不授替换权限）。同key多个实际目标拒绝，publisher从已核验snapshot枚举静态目标，不接受任意JSON路径/索引。替换旧ConfusionPoint仅由新exact overlay在同key优先，并保留原author规则及其他问法/旧局；不能声称修复所有相似表达。Checkpoint/事实/metadata/条件/通用正则不是可自动替换类型，改计分事实要人审题库修订，不让exact补丁偷偷改p1。schema2副本应用patch再验证，正文/操作/目标/事实/报告改变使digest与旧批准失效。

BEGIN IMMEDIATE核对active pointer的ruleVersion/row_version，INSERT新release（或校验完全相同内容）、切pointer与rule_published审计同事务；同operationKey相同payload返回原结果，不同payload409。回滚只切到可验证旧release，并记新操作和审计，不删除当前版本/历史。

## 5. 显式停版与游戏恢复

runtime_meta按rule_suspension:<digest>存严格停版标记（不改001/002，不新建003），停用/解除需显式受控管理操作与reason/audit，CAS回滚可原子停用严重错误源版本。active目标必须可用。新局选新pointer；老局固定原p1/r1，普通发布/回滚不改其会话、消息、原评分或缓存键。

reserve/finish/evaluate在原事务里检查所属规则是否停用；在途owner结果也拒绝409/rule_version_suspended，不扣次、不写新问答、保留原预留及历史。过期释放/只读历史恢复仍可进行；ended保存评估仍可合法显示。恢复响应追加ruleSuspended状态，前端禁用新提问/新揭晓并说明暂停原因，保留原session与pending UUID，不自动另开/覆盖保存对局。人工明确解除后可重新同步，不声称切pointer已修复全部旧局。

## 6. 审计、故障与边界

不改已登记001/002 SQL/checksum。反馈提交/审核/许可/导入/发布/回滚/停版采用新的严格tagged detail与受控eventType，沿用借用事务audit_store.insert_business_event；不把私有原反馈复制进普通HTTP尝试/fallback/stderr。必要审核短理由/确认/事实引用仅管理员受控业务审计字段，与原模型reasoning分开；安全事件总量仍16KiB，有界标识/摘要，不允许任意metadata字典。

所有模型调用仍事务外，stage10自身零云调用；原00费用/50–100分页/250ms尝试日志/真实未退出8IO边界不削弱。异常返回脱敏固定code，版本冲突409，缺审计/快照503，数据/范围错误422。DB事务失败不重放外部调用，源副本保留。匿名session/turn持有关系不是实名授权，不宣传独立用户数。

## 7. 验证、分解与自审

五个交付单元：feedback契约/事务与管理员CAS；隔离幂等导入/溯源；人工许可+冻结TaskContext；schema2精确规则/内部CAS/停版；HTTP/后台最小适配+全门禁/唯一独立审查。TDD先观察RED再实现，原测试/玩家数据守卫不削弱；current TS09审查没终态之前不写测试/产品源码。

用事件栅栏/独立临时SQLite测并发提交审核、所有写边界注入回滚、旧ID不同内容、重复导入/坏尾行/源不变；许可/版本改变、other turn/soup/p1、旧缺Trace、未知事实与无人工确认零新调用；双CAS一次发布、审计失败整体回滚、operation payload冲突、不可变旧release；发布/回滚后新旧局/缓存分隔，停版前预留的晚到提交拒绝、前端保留原局；未知语义/指代不同历史不当通用规则。最终全离线/hash+UI/lint/typecheck，单阶段一个clean inherited reviewer，一次Critical/Important修复，Minor与外部门禁留账。

自审当前设计无真实数据/密钥/生产行为、无003依赖或付费模型裁判；并发原子性/版本绑定/原历史不变均可用合成测试。两个歧义已选定：强制服务端authorizer/完整绑定receipt（不是模型自报），replace只允许唯一精确QA或ConfusionPoint完整来源（不是修改计分事实/任意规则）；明确反例与成本入ledger。无占位或隐含自动云授权。TS15才能外露候选发布/回滚，不重新启用legacy merge。审核许可不等于正则脱敏万能、绿色报告不等于语义已证明、外部云请求不保证可取消。设计自审完成，下一步writing-plans；仍不越过TS09只读审查门禁。
