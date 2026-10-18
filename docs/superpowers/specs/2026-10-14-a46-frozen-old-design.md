# A46 固定TS01旧宿主离线执行器设计

## 目标与授权

补齐原A46本地缺口，让纯LLM/TS01真实旧宿主/新宿主能够在同一版本输入、模型和最大预算下保留全部重复与失败。不是实际免费模型实验或准确率提升结论。用户已授权连续本地实施和普通决策，不逐阶段询问；零新增付费、数据/Git保护、平台审批、真实人审/模型/生产/公开HOLD不变。选择原生执行，无逐Task代理；完成整个新单元后一次独立只读审查。

## 选择与身份

选择固定同源档案+私有模块namespace+预算化FakeModel桥接；不启动旧服务/数据库，不用新host改名，不用AST摘取/重写旧分类器。另一选择是直接跑旧backend，存在默认配置/真实数据风险；逐函数重写则无法忠实基线。依据已核11文件/10AST，档案身份为TS01 captured working-tree，已含TS01测试隔离，不是假称原始HEAD或历史生产全态。

在 `backend/eval/frozen_ts01_sources/` 保存11个已有非数据文件的完整原字节为 `.raw`，避免被正常Python自动导入；仅指定清单，绝不复制soups、QA、数据库、dotenv或accuracy脚本。元数据保留来源SHA和长度，代码钉住11条原顺序记录的SHA256 `255afe9f471ce2316734f0a9c9e30793dbd978ece9ba223d7d7bf53e7ffb6898`。清单可验证一致性，不是第三方身份认证。requirements是历史声明，不声称安装的wheel与历史机器完全一致。

## 装载闭包

`frozen_old_sources.py` 固定verify/read/load，不接受调用方目录、模块或回调。逐项根路径/普通文件/无链接/单hardlink/有界读取/实际SHA校验，所有字节验证完成后才编译执行已读的缓存字节，避免验证后重新读不同代码。10个模块按固定依赖顺序装载：app package、schemas、paths、config、runtime、rate_limit、prompts、rag、testing、ai_host。相对导入保留完整源码，namespace为每个装载owner独有的 `eval._frozen_ts01_<uuid>.app`，不得覆盖任何现代app模块。

旧config导入不读dotenv，旧runtime导入不实例化Runtime；driver才用其显式for_test设置及runtime_context绑定已预算化模型。每个owner有自己的旧random.Random(seed)，关闭只删除属于该owner且对象仍匹配的模块；import错误也清除本owner部分注册。可信本地代码边界，不声称OS权限沙箱/任意Python隔离或硬CPU抢占。AST证明仅用于闭包检查，不裁剪算法。

## 预算桥接与旧行为

`FrozenOldDriver(*, settings: Settings, fake_model: FakeModel, clock=time.monotonic)` 只接受当前Settings.for_test/fake/禁止真实模型/禁止运行题库，私有档案已验证才装载。输入必须严格EvaluationInput，system.name=frozen_old/engineVersion=host-ts01-frozen-v1、固定旧实现/prompt身份；p1/r1来自同一输入，既有runner承担版本复验与全分母。旧Soup由输入完整soupJson构造，不读取外部题库/标签；旧实际分类、RAG去否定、文本归一化和最近10条message全部保留。

旧模型原来最多两次invoke（解析失败后文本回退），因此每次旧invoke通过共享case预算至多一个transport attempt，整个case累计1–2次。期限=min(caller deadline,开始+声明≤45秒)，最多12个完整有效history turn、实际完整prompt≤8000字符，不能截断汤底/事实来通过。actual context window保留旧10message=最多5完整turn；manifest max12是共同最大界，不假称旧宿主消费12。deterministic时不伪造prompt/上下文观察。

复用现有ModelGateway所有owner/admission/取消/真实close逻辑；增加仅用于受信任InjectedAdapter+FakeModel的raw legacy响应合同，让旧JSON parser/归一化确实处理原始输出。默认host_judgment/repair_action不变，真实CompatibleAdapter不能使用此合同；返回字符串≤16000字符，不把旧输出先用新严格parser修好。每次invoke独立AttemptCollector，再重排全case ordinal1..2；保留未知usage，started但未完成仍如实记录。失败/预算拒绝/取消不能变成新合法答案，旧算法自身将坏文本归一化成答案的历史缺陷必须保留为旧基线行为；不能因此改变新在线宿主标准。

结果桥接只接受完整旧dict及明确flags：canonical五类答→source legacy；always_yes已明确命中可按旧分支保留“是”展示变体；明确flow/reminder或未调用模型的非是否提醒→reminder；win/giveup等不在本评测分类范围→unexpected_host_kind；非canonical模型失败→固定error，不匹配任意子字符串。不调用新host/新规则/新normalize来修旧结果。旧异常stdout不输出到用户或报告；只丢弃输出内容，不抹除错误记录。

## CLI、证据与验收

固定 `--system frozen_old`，无 `--legacy-dir`/`--module`；仍只接受显式dev/regression/FakeModel、新输出、repeat1..10。三个配置adapter/provider/model/seed/budget/context上界/数据版本相同，engine及实际实现/prompt可不同；comparison保留所有输入和missing/incomplete，qualityConclusion=null。旧闭包、桥接、网关和producer依赖进入实际指纹，不能只绑定静态prompt字符串。实际完整源身份须扩展包括 `.raw` 和清单，不用旧380总数为新增代码背书。

先逐Task真实RED→GREEN；最终全Eval/完整offline/type/lint、真实owned UI按实际影响、新backend包或其不含eval的明确边界、当前source与原239/Git前后保护，再唯一新单元审查/一次必要修复。测试合成gold不是真人结果；真实三方、生产历史、免费资格/人工holdout继续HOLD。局部GREEN或装载旧函数不称完整driver完成。
