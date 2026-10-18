# TS11 独立评测数据与冻结合同设计

## 意图、分类、权限

这是新增评测子系统的架构型工作。用户要零新增成本、保留真实网站/正常问法，并把项目变成能解释的求职作品；已明确授权自主设计/实施/自审，不逐阶段确认。本设计不改变这些选择，不自动生成“人类已审核”的证据。TS10唯一审查Averroes运行期间，主执行者只写本设计/计划/ledger；58冻结文件、HEAD/index及运行题库不动，不执行共用门禁。

绑定原计划TS11、A41–43、C19和第9节：第一批60新单问（至少6汤）、10组三轮上下文（30判定）、20非是否/控制输入，总110判定；旧评测仅dev/regression，按来源/对话/问法家族及原句/exact-v1重合审计；最终标签不进入修复资产。原目标数字不改。真实独立人审暂缺，只搁置真实标签/holdout冻结，数据合同、模板、110草案及离线安全测试继续。

## 实际问题与方案选择

已完整只读检查app/scripts/eval_host_accuracy.py，未执行：它使用生产式默认路径/桌面回退、动态db.SOUPS、被测是否分类器筛题、把服务失败列需复核并排除硬分母、空历史、从展示字符串抽答案并覆盖旧报告；包含旧99.1%宣传。TS11不沿用它导入数据或作新成绩；TS12替换runner和旧入口，当前不冒称已修复全部旧脚本。

推荐：backend/eval纯合同/分组/私有冻结模块，显式输入与新输出，复用现有Pydantic/摘要/exact-v1/事实目录，无依赖/新DB/新服务。逐条随机拆分不保留来源独立性；把旧数据重新随机抽出也不是新holdout。外部标注平台增加费用/私有传输且无当前授权。选择本地可复核材料，代价是必须等真正人审才能宣布评测数据有效。

## 1. 数据合同

严格extra-forbid/frozen/real-int版本1，JSON输入重复键拒绝，无NaN/Infinity/隐式类型转换。角色仅dev/regression/holdout_candidate/holdout；来源仅legacy/new_authoring/public_synthetic。legacy只dev/regression，public_synthetic示例不计真实6汤/110条验收。每样本程序UUID、soupId、p1、question、caseType(single/context/control)、sourceGroup、familyGroup、可空conversationId、contextIndex与categories、visibility(private/public_authorized)、origin/evidenceSourceDigest、审核状态与label分开。

问题1–500 Unicode字符，说明≤1000，最多8类别/8事实ID，case最多5000、单行32KiB、文件100MiB、完整manifest2MiB；超限报固定原因码，不删超限尾部假称完整。问题原文保留，不由模型输出决定筛选。exact-v1仅产生重复索引，不改原句/否定/主体/数量。控制输入是合法有界文本的非是否/提示注入等，不混入无法进入提问API的空请求；协议非法另有测试，不借此抬高模型分类得分。

context以整组三个连续样本表示：同soup/p1/sourceGroup/conversationId、index1/2/3、同familyGroup、同split。前两问的预期仅用于人审；TS12运行第三轮使用真实前轮历史，不拿标准答案替换错误主持回答。各轮都进入分母。history生成由runner管，不在草案里复制玩家对话。

ExpectedLabel只answer（五类AnswerType）或reminder（answer=null）；system_error不是“正确期待”。labelOrigin=human和真实ReviewRecord不等于AI草稿的proposedLabel；pending/ambiguous/unsupported不得带已确认label。提醒有人工说明，不用被测is_yes_no_question给自己发合格证。

ReviewRecord包含operatorId、UTC时间、完整caseDigest、expectedLabel、factIds、reviewNote、人工声明；允许模型提议，但不能默认生成ReviewRecord。caseDigest绑定原句/分组/来源/题库/类别/proposedLabel，变更任一字段需要重新审核。事实ID来自该p1的完整EvidenceRecord目录；事实存在只能证明引用来源，不能程序证明蕴含/语义正确。提醒可无事实但必须有分类理由；answer必须至少1条本p1真实事实且人工确认。不从玩家expectedAnswer或旧注入答案生成标签。

审核记录是可信操作者声明的本地材料，不提供密码学“真是人类”证明；没有真实操作者动作不填写operatorId/时间/确认。将来人审可显式输入完整review材料，Agent/模型工具不能调用审核/冻结CLI。

Task3实施前接口裁定：EvalCase新增可选`proposedFactIds`（默认空tuple、最多8个f1、唯一），保留DraftEntry中程序解析的事实引用，避免只留下不可逆sourceDigest而丢失审核者所需线索。它与proposedLabel一样只是提议，不是gold；caseDigest包含该字段，build_pending_draft及正式审核校验同p1存在性。已有未填字段兼容为空，真实标签仍只来自完整ReviewRecord。

## 2. 分组、重合、漏数据

输入显式区分旧回归与新草案，不导入旧评测脚本、不读取默认data/桌面/玩家库。旧文本副本可用新纯解析器记录每个物理问答对、文件/行摘要/原旧答案，保留非是否、短句、未知标签、坏尾行及解析问题；不通过宿主分类器筛掉。旧字段只proposedLabel/原始主张，不变成已确认标签。旧材料可完整私有报告，错误正文不出stdout。

原句重复键(soupId,NFC(question))，规范化重复键(soupId,exact-v1(question))；来源组、对话组、人工声明的问法家族组均显式绑定soup/p1。sourceGroup指“问题的采集/创作来源组”，不是公共题库bottom的作者来源：同一道汤跨新问法评测是允许的，不能假称未见故事。p1事实作者来源另保留，不把它混作新问题来源。

以union-find对来源/对话/家族及重复索引形成污染连通组，审计全部边。某组若含旧dev/regression、规则修复精确资产或已公开示例，其候选条目整体不准holdout；移出记录进入显式quarantine清单，并保留总输入数与目标差额。不能只删冲突一行后把同组剩余称独立。unknown family/source/manual evidence使冻结拒绝，不凭模糊检索自动证明无重合。

同句不同历史可以有不同答案，不能错误合并成一个标签或通用QA：重复边会使其同组保留，两条上下文来源仍分别存在；同soup/p1、无上下文且同问法不同已确认答案是label_conflict，冻结拒绝。分组元数据不能语义识别所有近义改写，人工家族审查是必需外部证据，报告明确此限制。

## 3. 审核、冻结和完整manifest

编译inventory先统计所有输入、physical badRows、pending/ambiguous/quarantine/label_conflict及单问/汤数/三轮组/控制数；未达60/6/10/20给真实deficits，不修改目标。不输出准确率，不以过滤后的规模冒充输入规模。

freeze仅对明确提供的candidate集合、实际完整人工审核和无污染/歧义/版本错配成功；任何候选未确认或坏行都拒绝正式holdout。不能给“部分已确认集合”悄悄换分母；若操作者明确另建较小探索集，role=dev、报告不足，非A41/正式holdout。原草案/旧副本不改不删，输出到新目录。

manifest版本1绑定全部case/review/file/catalog/p1/r1/normalization/grouping/作者来源/收集日期/完整输入清单/污染索引摘要/策略/规模/差额/visibility与label状态；datasetDigest按规范JSON内容，修改标签/分组/审核/事实/源文件任何一项即变。新snapshot文件不可覆盖，读取重新验证完整字节摘要与合同；不只看manifest写了complete=true。TS12另补code/prompt/model/provider/budget/seed/time/context-policy运行manifest，不在TS11捏造模型版本或运行记录。

## 4. 公私与修复资产

holdout的完整输入/标签/审核说明/私有原文只在backend/eval/private或操作者明确私有目录，gitignore不等于已清除Git历史/保证磁盘保密。TS18另做公开范围/历史验收。默认stdout仅数目/安全错误码，不打印题干/真值/路径/原异常/审核者身份；新报告默认private，不外传。

load_repair_corpus仅加载显式dev/regression且已人工确认的样本；拒绝holdout/holdout_candidate、公私混合、污染未完成及不完整材料。它不提供任意路径给模型；TS13固定仓储/工具才接入口。安全演示只能public_authorized/public_synthetic，不能从私有holdout抽几题直接公开。公开synthetic的标签可由程序拥有的合成测试提供，但只能证明管线逻辑，不证明真实人审/质量。

110草案使用至少6个可信题库快照中的新问法，保持pending/proposedLabel和private，事实引用程序生成且人工待审；不读取真实玩家反馈/最终标签。生成来源标new_authoring/ai_draft，不作为公开样例或真实标注。若原旧问法/规则资产副本未提供，overlapAudit=unavailable，不能冻结正式holdout，也不能声称无重合；仍交付新纯导入/分组工具和有界合成验证。

## 5. 实施与测试

四单元：严格样本/人工审核/事实合同；显式旧副本解析和污染分组；新草案/inventory/私有冻结/修复资产门禁；CLI/文档/全门禁/唯一独立审查。所有测试临时合成目录，真实模型0调用；不跑旧eval脚本、不迁移生产、不读私密dotenv/玩家内容。backend/eval/tests加入受保护默认pytest发现范围，不能因目录不同漏掉全套/守卫。每单元TDD/自审，阶段末一个干净继承模型审查、一次重要修复，Minor留账。

C19至少验证110真实程序清单计数/6汤/三轮连续性；pending/伪人审/源修改/坏fact/hash/label_conflict拒绝；跨组转移/规范化重复/连通传递/合法不同历史不误删；旧集合绝不能升holdout；相同snapshot重读、修改任意绑定字段即失败；repair-loader无法访问holdout标签；权限/文件/审核失败不覆盖原输出。

本设计自审：合同覆盖A41–43/C19；提醒与五类标签分开；新来源组与题库作者组分开；110=60+30+20没有缩数；真正人审/旧副本重合审核独立搁置，不能凭AI草案补齐。下一步formal implementation plan；TS10终态及一次修复前不写本阶段源码/测试。

## 6. 唯一审查后合同修订（当前约束）

Lagrange实际C0/I3/M0；本地唯一修复补齐以下边界，不新增真实审核或生产权限。ReviewRecord增加可空contextDigest，独立题须null，上下文题须context-review-v1有序前缀摘要：同组三条完整范围、先前业务caseDigest和人工标准答案；改前轮问题或答案必须重新人工审核受影响后续行。validate_reviewed_case接收显式context_cases，盘点也验证当前审核；该依赖是人审材料，不是喂给模型的实际历史。

inventory(cases,*,audit,source_digests)必须显式来源；新增纯proofs.validate_scope共用于盘点/封存，验证源摘要/覆盖、组/边连通与隔离列表含义，不把自重hash当证明。合法pending/缺口可盘点，坏源/清空隔离不可ready。全r1成员ID/版本格式/字段/overlay/parent结构验证，选中完整Soup仍复算p1/f1；未提供其他Soup的事实/完整p1和历史parent链不声称已经验证。source/family按同汤p1、raw/exact按同汤跨p1，整组隔离不是跨不同故事一律隔离全部110。
