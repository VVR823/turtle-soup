# A46 旧系统基线身份与本地实现边界

2026-10-15最新本地检查点：A46新增旧算法离线对照单元已完成唯一审查及一次必要修复。当前398源/55462476…实际3515离线通过/14原有明确跳过，另35 owned Edge页面通过，type/lint退出0；UI/API资源正常关闭、字节未变产物复用与新隔离smoke完成，原239数据/HEAD/index保护不变。471 Eval与26定向测试包含在完整回归中，不相加。此前398/bb0ab4df…的3513结果是修复前历史。只签收该本地单元；继续核原18阶段完整验收，真实模型、人审、生产、公开与本人能力仍HOLD。 见[当前验证](a46-local-verification.md)及[审查处置](superpowers/plans/2026-10-15-a46-review-resolution.md)。此前53 CLI/469 Eval/9合成报告与原阶段数字仍保留为各自冻结身份的工程证据。

下方为2026-10-14只读核查历史，不是当时旧系统已跑通、真实三方评测或准确率提升证据。

## 找到的真实旧源码

TS01证据明确记录副本 `D:/CODE/turtle-soup-clean-ts01-18b93182b3ff439eb9664d686491cf6b`，来源是当时的 tracked + nonignored untracked working tree copy，不是 Git checkout/remote clone。当前11个非数据源码/依赖声明文件均与当时 `.cache/ts01/source-manifest.json` 的SHA256一致，10个Python文件实际AST解析成功。宿主、旧RAG、prompt、schemas、配置、runtime、paths、limiter、测试model与requirements都还在；没有因新的宿主改造而丢失。

[静态核查回执](../.cache/d18/completion-refresh-1863a266-95dd-4a0f-b2d2-aef4a160d5d8-old-baseline.json)逐文件保存实际字节摘要和静态imports/functions。未导入/执行旧宿主，未读旧 `soups.py`、玩家QA、数据库或dotenv，没有联网。AST解析与少数文件哈希不是完整调用闭包、安全运行或已安装依赖认证，回执保留 `sourceClosureComplete=false` 和 `safeExecutorImplemented=false`。

## 不能偷换的身份与行为

这个副本已包含TS01早期测试隔离改动：旧 `_get_llm` 从应用Runtime取注入模型，真实transport在没有注入模型时才惰性创建。不能叫“未经改动的原始HEAD”或“生产当时全部状态”；之前 `git show HEAD` 可读到的提交代码在宿主transport处已经不同，不能拿提交SHA代替副本字节身份。

旧判断路径仍有真实历史差异：RAG提取核心时去掉否定词并做模糊匹配，宿主自行选最近10条message，JSON解析失败后尝试文本归一化等。后续旧执行器必须保留这些实际代码及缺陷；不能改成新exact规则、用新host改名、修好旧分类器或给模型标准答案。超时、调用预算、无网络、关闭回收是评测外壳约束，不是替旧算法修答案。

## 自主裁定与接续条件

Ruling：旧源码并非不存在；A46仍有可推进的本地实现工作。采用明确署名的“TS01 captured working-tree baseline”作为待实现候选，原始提交/生产历史基线身份保留未证明；成本是不能对外宣称覆盖了全部历史生产行为。TS12原来“禁止执行旧代码”的安全裁定在新的隔离设计、反例和门禁完成前继续有效，不直接启动旧accuracy脚本。

下一步在既有 `EvaluationInput → DriverOutcome → RunReport` 中设计固定、同源、无任意路径/动态模块入口的旧宿主适配。先完成完整旧执行闭包核查，再制定同预算transport与严格结果桥接的反例：旧缺陷保留、旧/新模块不污染、输入不含gold、1/2调用上限、8000输入字符上限、45秒截止、取消和真实关闭、全部失败进入分母。没有这些证据前继续使用显式UnavailableOldDriver，不能将当前静态回执当作可执行比较报告。

真实免费模型资格、合法独立人工标签、重复三方实验和生产/公开权限是另外的HOLD，不妨碍这个本地隔离实现；不因本地实现完成而自动解除。
