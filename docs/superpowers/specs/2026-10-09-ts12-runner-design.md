# TS12 完整分母与可复核比较设计

## 意图、分类与授权

这是新离线评测子系统的 architectural 设计，继承用户已批准原TS12/A44–46/C20及零新增成本、本地持续执行、不再逐阶段确认的授权。目标是面试时能解释每道题、每次失败和每个版本如何影响报告，而不是先写一个高准确率。TS11唯一审查进行时只写不冲突设计；TS11审查终态、一次C/I修复与最后门禁完成前不写TS12源码/测试，不运行共享门禁。

不读生产dotenv/player/桌面原题，不调用真实模型、不购买/部署/上传、不改001/002/默认迁移1、不派多审查者。真实免费账户/隐私许可/人工holdout/语义来源审计/可安全执行的冻结旧系统仍是外部待定子集；其缺失不能阻止runner的离线逻辑实现，也不能被假数据冒充已验收。

## 方案选择与取舍

不延续旧脚本筛选问题/剔除失败/正则提取显示答案的方法，也不引入新的队列、服务、付费模型裁判。选完整TS11 FrozenDataset + 严格预测账本 + 纯指标 + 可信本地driver接口 + 同预算比较。CLI仅固定离线演示，不加载任意模块/模型生成路径或凭据。旧入口改为安全转向新CLI，不保留默认runtime/桌面读写。

真实旧系统HEAD源码可只读取hash，但旧版本顶层即创建HTTP客户端、当前schema也不兼容。直接import/exec或改造后冒称冻结原系统不安全、不诚实。保留frozen_old适配器接口与缺失原因；没有安全可信旧driver时comparison完整性false/质量结论null，而不是把new_system改个名字充当旧系统。代价：正式三系统质量验收待合法旧执行器及真实模型条件；合成三系统夹具只证明比較的工程门禁。

## 1. 严格报告合同

创建backend/eval/run_contracts.py；复用TS11 StrictDatasetModel、Digest、Identity、CanonicalId/HostVersions/TokenUsage；extra forbid/frozen/真实整数/拒绝NaN、重复JSON，schemaVersion真实1。

- RunBudget：modelAttemptsPerCase真实整数1–2，caseTimeoutSeconds有限数>0且≤45，maxContextTurns固定12、maxInputChars固定8000，contextPolicyVersion=context-v1，usagePolicyVersion=provider-declared-v1。这里只允许在线现有已验证窗口，不造可改变提示预算的开关。实际token未知时不声称准确TPM。
- SystemSpec：name=pure_llm|frozen_old|new_system，implementationDigest/promptDigest完整SHA256，adapterId/providerId/modelId有界无URL身份，normalizationVersion=exact-v1，engineVersion有界，seed非负真实整数，budget，executionEvidence=synthetic_fixture|offline_engine。每配置记录自己代码/prompt摘要；比較共同dataset/p1/r1/model/provider/seed/budget必须相同，不能要求三个实现代码摘要相同。
- EvaluationInput：caseId/soupId/puzzleVersion/question、完整Soup/RuleSnapshot证明、实际此前host历史(tuple不可变的HistoryTurn)、SystemSpec。不含ExpectedLabel、ReviewRecord、proposedLabel/FactIds、rawLegacyExpected、来源/审核人。driver没有标准答案/修复路径/数据库权限；普通源码内公开故事事实是输入，不等于给模型题目标准答案。
- HistoryTurn：question/answer/versions，只记录成功五类answer结果；提醒/系统失败/win不放下一轮有效历史，原结果仍留账本。每会话、每系统、每repeat独立，禁止跨汤/角色/会话共享。
- PredictionRecord：caseId/soupId/repeatIndex/systemName，expectedLabel(仅私有报告层)、prediction=五类答案|reminder|error，actualAnswer可空、errorCode固定code、source、resultVersions可空、durationMs有限非负，decisionAttempted真实bool、modelAttemptCount真实0–2，usage(input/output/total可空)/usageStatus=known|partial|unknown|invalid，contextTurnsIncluded/inputChars可空，contextPolicyVersion；不保存模型reasoning/原始输出/问题全文。win对通用answer/reminder数据集为unexpected_host_kind→error，不正则解读reply。
- RunManifest：runId canonicalUUID、datasetDigest/puzzleVersions/ruleVersions/SystemSpec，startedAt/finishedAt真实UTC，inputCaseIds完整唯一集合、inputCount、repeatIndex(0–9)、repeatCount(1–10且index<count)，runnerVersion=eval-runner-v1，metricsVersion=full-denominator-v1，manifestDigest排除且仅排除自身。比较必须保留预声明repeatCount，整次最差repeat的三个报告一起消失也应发现，不能用观察到的最大index反推计划次数。code/prompt/model/provider/seed/run时间/总数/截断策略可追溯，fake证据不提升真实模型结论。
- RunReport：datasetProof:FrozenDataset/manifest/records/metrics、complete、reportDigest；完整私有datasetProof随报告携带，复验其封存并把每条expectedLabel/soup/p1对照原审核内容，不能只检查可重算的report自摘要。records恰好每个计划case一条，恰好相同集合，不允许丢题/重复/挑成功。指标从完整records重新计算并复验。input≤5000，repeat≤10/系统恰好三种时比較，单报告≤100MiB，独占新输出/原摘要保护。完整标签只在私有报告，不进入driver输入。

Prediction/error固定分类覆盖invalid_output/provider失败/timeout/budget_exhausted/driver_unavailable/context_too_large/unexpected_host_kind/version_mismatch/driver_error/cancelled。异常正文不出报告；provider ModelFailure有界原errorCode可作为固定子码。每道题不论分类器判断是不是是否问题都运行，不用被测分类器删掉题。

## 2. 完整分母指标

创建metrics.py，`compute_metrics(records:tuple[PredictionRecord,...])->EvaluationMetrics`，无model/DB/file副作用。

固定行truth=[是,不是,是也不是,算是,与此无关,reminder]；列prediction同6类+error。每输入只加一个格，所有格总和=inputCount。整体accuracy=正确对角/inputCount；失败列不能删。五类macro-F1固定五类平均，零分母类F1=0并保留support=0；真值五类预测error/reminder计FN，预测五类但真值reminder计FP，不只对成功子集评分。answerAccuracy分母所有truth-answer，包括error/提醒错判；reminderPrecision/Recall/F1保留undefined=null而非伪造0，分类answer/reminder/error表另外输出。

报告total/correct/errorCount/errorRate、各error分类及class/perSoup支持数与指标。每汤同样完整分母，不拿macro平均汤accuracy冒充总体accuracy。延迟全部实际durationMs排序nearest-rank P50/P95、min/max/count；时钟异常固定拒绝/完整失败，不造负延迟。用量三个维度各输出knownSum/knownCount/unknownCount，未知不得总和0冒充全已知；deterministic0调用可明确input/output/total=0、model0，不等同有调用但未知。多attempt只有同维度全部已知才给本题总数，未知/invalid明确保留，失败已观测用量仍保留。

不预填提升率/97%/99%。空数据报告指标null/支持数0，没有成功运行。这里只输出合成/探索指标，不输出真实泛化质量已证实标志。

## 3. 串行runner与实际历史

创建runner.py；`run_dataset(snapshot:FrozenDataset, *, system:SystemSpec, driver, repeat_index:int, repeat_count:int, clock=time.monotonic, utc_now=utc_timestamp) -> RunReport`。utc_timestamp为run_contracts真实UTC字符串时钟，测试可注入受控时钟。入口verify_frozen_dataset全证明，不允许pending CaseBundle/坏标签直接测准确率。正式holdout与探索dev/regression通过manifest明示；CLI假数据只接受dev/regression，不替真实holdout封存。case排序按确定性的汤/会话/上下文index/caseId；单问与控制不继承别题历史。

driver为可信程序对象，不是文件名/动态import/模型动作。入口/每次call验证预算及deadline，所有失败也占attempt，不无限纠错。driver接收独立EvaluationInput，不接收标签。返回DriverOutcome(host:HostResult|None,errorCode|None,modelObservations tuple,contextMetadata)，严格完整类型/版本检查后归类；unknown dict/displaystring不被自动合法化。driver失败当前题记error，后续仍运行；取消/总预算阻止后续时每个剩余case记error/notAttempted原因，全计划分母留下。

Task2预检补充：DriverOutcome另含modelAttemptCount真实0–2，独立于modelObservations长度；before_attempt预留后取消可能还没有started观测，不能据此退款或写成0次。观测ordinal必须连续且不超过预留次数，未尝试决策必须0预留。BudgetedGateway/实际driver可显式注入clock=time.monotonic，须与runner使用相同纪元；非法/倒退时钟拒绝产出完整报告。complete是可信producer根据实际close作出的状态，不是摘要能够认证操作系统收尾的证明；未知收尾必为false并停止后续调用。

上下文使用当前系统实际上一轮合法host答案，故意错误答案仍在该系统历史里；不能用标准答案纠正历史。相同代词不同组保留，不跨组、系统或repeat。最长12完整有效turn，8000字符完整事实+问题+系统指令；实际裁剪仅整轮且报告metadata，保存账本不删除历史。无法安全装入固定事实则本题context_too_large，不截汤底。

创建drivers.py：固定的NewSystemDriver通过Settings.for_test/独立Runtime/runtime_context调用真正ai_host.handle_host_response，Soup/完整rule/p1/r1显式，无lifespan/database。PureLLMDriver跳过现有deterministic与分类拦截，仅同版本完整上下文+现有JSON五类协议；因此它若把提醒题判成answer，会真实记分类错误而非预先过滤。纯LLM严格协议的能力局限进metadata/文档，不强称输入分类模型。CLI使用现有exact FakeModel；失败脚本模型是tests/support.py的FakeModel子类，不在生产类添加仅测试参数；可信程序API不是任意Python安全沙箱，CLI无动态对象入口。假模型只读脚本输出不读gold；ModelGateway依旧最多2attempt/45s，before_attempt核验本题预算，停止与close检查自有worker回收，unknown用量正确汇总。

driver的deadline/attemptLimit必须真的约束现有call_llm内的45s/默认2attempt，不能只写报告。用本地BudgetedGateway包装当前ModelGateway.invoke，将deadline取本题与调用方较小值、max_attempts取本题政策并以before_attempt记录每次预留；wrapper只由runner拥有，收尾调用现有close并检查active/cleanup失败，不改变生产gateway。尚有自有未回收worker时不得继续新题模型调用，剩余题保留notAttempted/error；不谎称timeout强停远端。固定fake driver只接收FakeModel或显式测试脚本类型，不根据陌生对象自动创建CompatibleAdapter。promptDigest绑定实际使用的提示模板及renderer源版本，不当作每题完整prompt字节摘要；每题输入版本/上下文计数另外记录。包装器从实际invoke消息取得inputChars，不解析可被用户伪造的提示文字来猜turnCount；当前生产新链没有导出真实turnCount时记null，政策与代码摘要仍绑定，不能用传入history长度假装实际裁剪数。普通deterministic无模型prompt时两者null。期限限制模型等待，可信本地确定性代码/报告验证不冒称抢占式CPU硬超时。

冻结旧执行器仅可信本地接口/版本摘要与独立边界；本阶段只有UnavailableOldDriver明确driver_unavailable，不实现任意外部callable/module执行器。绝不执行git旧源码顶层、不暂时关guards、不修改现有纯规则/正常游戏协议为评测服务。SyntheticDriver由测试私有夹具提供三种配置，输出与真值分离；其报告始终synthetic_fixture，不假称真实旧系统基准。report.complete表示全部决策实际尝试且资源收尾明确，不表示全部答对；真实尝试的provider失败仍是完整运行，未尝试/不明收尾则false，所有行均在指标分母。

## 4. 相同预算比较与保留波动

创建comparison.py；`compare_runs(reports:tuple[RunReport,...])->ComparisonReport`。每repeat恰好三system唯一；共同dataset/p1/r1/input集合/model/provider/seed/budget/contextpolicy一致，manifest/report摘要完整、全部运行报告保留；重复runId/缺配置/预算不同/改dataset/count/少一次失败run均拒绝比较或明确incomplete，不生成提升结论。每配置实现/prompt摘要自己的全部repeat不变。最多10repeat/30runs，运行顺序固定，不同时抢占在线模型资源。

输出每系统各run指标+跨重复min/max/mean/population标准差、相对new-minus-baseline差值完整保留正负/零，不挑最优seed或忽略失败重复；没有可用冻结old时qualityConclusion=null/incomplete=true，报告缺失原因不把两配置包装成三配置。fake或offline_engine不得产生真实模型质量结论。ComparisonReport保留完整RunReport元组及摘要，而非只留成功均值；总输入报告及最终比较各≤100MiB，超过显式拒绝，不能静默删掉大或失败的run。

Task3实现前明确：共同范围另绑定adapterId/normalizationVersion/executionEvidence/repeatCount；每系统的engineVersion/代码/prompt允许与另外两系统不同，但同一系统每次重复必须同完整SystemSpec。既拒绝重复runId，也拒绝同系统同repeatIndex的另名run。missingRuns只记报告不存在，incompleteRuns另外记已有但未完成报告，全部原报告保持输入顺序。统计accuracy/answerAccuracy/macroF1/errorRate/P50/P95/totalTokens/modelReservations各项均含knownCount/unknownCount和总体标准差；token只在该run所有题用量都已知时进入总量统计，不把部分已知总和冒充完整账单。差值按同repeatIndex配对new-minus-baseline，已有但未完成pair数值为null/reason=incomplete_run；真实已尝试provider失败仍是完整run并保留差值。摘要不能认证真实模型身份，qualityConclusion固定null。比较读回必须严格复验原run和重算所有统计/缺项/摘要。

## 5. CLI、旧入口与隐私

创建run_cli.py固定`python -m eval.run_cli run --dataset <显式FrozenDataset绝对路径> --output <新私有RunBundle绝对路径> --system new_system|pure_llm --repeat 1..10 --fake-answer <五类>`，全部参数显式。RunBundle(schemaVersion:1,reports:tuple1..10RunReport)包含该系统所有预声明重复、index集合完整且repeatCount一致，所有报告都复验，不覆盖既有文件。只用FakeModel/for_test，拒绝真实provider/defaultpaths/role覆盖/任意adapter/module/凭据/网络开关，输出计数/code而非gold。旧app.scripts.eval_host_accuracy替换为无app db/ai_host/config/transport顶层导入的兼容shim，同参数转向新CLI，旧--only/max-per-soup/test-dir/default桌面路径拒绝。声明旧报告保留但旧99.1无法验证独立泛化，实际report用完整新口径。

比较入口可另`python -m eval.run_cli compare --input <1..30明确RunBundle路径> --output <新私有比较>`，flatten全部报告，不接受目录glob/扫描，不执行任意系统。holdout标签仅私有报告/最终验证，不提供给未来Agent回归工具；TS13/15回归仅load_repair_corpus允许角色。无需新增Web页面/公开数据集/云评测依赖。modelAttemptCount表示before_attempt本地预留次数，不证明供应商实际接收请求；在预留后取消/超时也不退款，policy为local-reservations-v1并入manifest。

## 6. 验收及复核焦点

C20合成夹具混正确/错误/提醒/invalid/429/timeout：每题都占分母，macro-F1/error列手算精确验证，源码真实新链假模型集成，实际上下文wronganswer不会偷用gold，三配置同预算metadata/重复波动正负差值，报告篡改/缺题拒绝。旧入口import不会dotenv/runtime/HTTP初始化，私有输出既有文件不覆盖、失败不丢原。

五个优先边界：失败→下一题继续而分母不减；同代词不同历史/失败中轮不喂gold；错版本/合法显示但非法协议仍error；某系统免费限流/未知token/一次重复很差不能被比较删掉；旧入口缺参数/既有文件/动态模块拒绝且旧数据/迁移字节不变。

实施拆合同与指标、runner与drivers、比较、CLI/旧入口/文档四个单元，main native真实RED→GREEN→整套/串行UI/hash；阶段末ONE清洁继承模型审查+一次C/I修复，Minors记录。真实质量/人审/旧执行器待定不阻止本地工程逻辑，但A46正式三真实系统同模型结果未满足时不能称全部验收。遵守TS11冻结期无源码/test共享变更。
