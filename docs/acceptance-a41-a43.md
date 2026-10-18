# A41–A43 评测数据：工程可核，真实人审仍待完成

2026-10-15。保留原60单问/至少6汤、10组三轮、20控制目标，不降低数字或把合成标注换名成人审。当前398文件身份55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32；以下7份现有测试完整读、同源绑定，并从[完整XML](../.cache/a46/review-final.xml)精确classname核178通过/0skip，均已在3014后端/3515离线数中，不重跑、不相加。

| 模块 | 当前已有通过 | 对应保护 |
| --- | ---: | --- |
| eval.tests.test_dataset_inventory | 9 | 110的字面规模/实际差额、提议事实、AI草案不变成人审 |
| eval.tests.test_dataset_grouping | 19 | 来源/家族/原句/规范化的传递污染、上下文差异与缺来源 |
| eval.tests.test_legacy_dataset | 22 | 旧输入逐物理行保留，坏尾/未配对显式缺口，固定regression |
| eval.tests.test_dataset_contracts | 62 | 严格审核记录/事实/输入hash/UTC/身份/上下文绑定 |
| eval.tests.test_dataset_manifest | 32 | 完整封存、改标签/漏输入/重算假审计拒绝，holdout不可修复导入 |
| eval.tests.test_dataset_cli | 23 | pending真实exit2、私有/公开权限、独占输出与holdout导出拒绝 |
| test_repair_corpus | 11 | 独立冻结反例不能由Agent重写，holdout/换语料/换源码拒绝 |

XML SHA256=d297ae1a7a0628f0c1e9120ffcc510086c4cedaa3b21c65aebd10cb94f78ba90。合成fixture中的humanConfirmed=true只用于验证合同，不是实际真人标签或真实语义证明。

## A41：数量已有；不冒称金标

实际[既有盘点回执](../.cache/d18/completion-refresh-1863a266-95dd-4a0f-b2d2-aef4a160d5d8-receipt.json)SHA256=82fd6e2dda8fc44042b7b2f828baa65cf0032eb4d2632113fe4cbf08ba0c7f09，2026-10-14T12:58:58.615Z由原380源执行inventory/freeze，各exit2/needs_human：110输入=60新单问/6汤+10组三轮/30决策+20控制；各数量deficit=0，但pending110/reviewed0/eligible0、auditComplete=false/sourceIssueCount1、formalSealProduced=false。

本次只复核该回执、3份已知AI草案/题库/来源盘点输入摘要及2输出摘要，全部匹配；没有重跑CLI、输出私有题目、创造审核者或改原材料。故这仍是已核原盘点，不把380的执行身份换成当前398，也不把数量齐全说成A42已完成。类别字段及可查询库存由原草案/严格合同保留；未核真人语义类别覆盖，不以合成110测试替代实际审核。

[inventory永久回归](../backend/eval/tests/test_dataset_inventory.py)明确删成107时按实际报告59单问/9组完整上下文/19控制、差额各1；公开合成样例不计真实60/6目标，不能用换口径凑数。

## A42：来源隔离和封存工程，不是替人审

[grouping](../backend/eval/tests/test_dataset_grouping.py)按source/family/raw/NFC/exact及conversation传递成分组，旧/公开样例污染整个相关候选成分；规范化保留否定、主体、数字和原问题，不把不同问题糊成相同。相同代词但不同真实历史可有相反标签；同独立问题相反标签、三轮缺项/重复index/不同split或题库则明确不完整。缺来源清单不默认“审计完成”，重算一个假干净摘要不能掩盖原关系。

[review合同](../backend/eval/tests/test_dataset_contracts.py)绑定operatorId、UTC、caseDigest、expectedLabel、真实factId、reviewNote、humanConfirmed及上下文digest；改问题/来源/事实/角色/上下文后旧审核失效。程序验证有该事实和声明完整，不能证明结论被事实支持，也不能认证声称的真人身份。永久反例明确：存在factId但合成“人工声明”填错答案，结构校验仍只把它当声明，不宣布语义正确。

[manifest](../backend/eval/tests/test_dataset_manifest.py)要求所有指定输入、完整来源审计和已审核记录，pending/ambiguous/漏项/来源替换/坏JSON不能封存；不可只移走失败输入后宣称110。真实独立来源、审核人员/参考答案和最终holdout封存尚缺，因此A42仍HOLD。依赖：由真实有权审核者检查实际材料并提供可核来源/事实依据与歧义处置；不自动填标签或用AI自审冒充。

## A43：旧数据、公开样例与Agent修复集分开

[旧解析](../backend/eval/tests/test_legacy_dataset.py)保留“谁？”及“不确定/不重要”等原文、物理行/源hash和稳定独立ID；不筛成漂亮accuracy，不把未知答案强转五类。旧材料只能dev/regression，不能改个角色字段当最终holdout。

冻结holdout直接进repair loader被拒，复制manifest改role也拒；私人回归可私有导出，但--public-synthetic不赋予私有材料公开资格。仅本来public_synthetic/public_authorized的授权合成样例有显式公开导出路径，[A36–A38](acceptance-a36-a38.md)保留其边界；这不是已经公开或复现未公开全量质量报告。

[实际修复语料回归](../backend/tests/test_repair_corpus.py)运行固定临时preview和全部独立反例，报告仅case IDs/结果/安全codes，不把expectedLabel/原题底传给模型工具。错误反例/缺独立候选问题就failed/incomplete；Agent不能改冻结标签，不能借holdout、超过100条后截断成成功、在旧suite identity下换另一有效语料或换代码。其synthetic_fixture结果不是实际真人参考任务成功率。

结论：A41数量证据与A42/A43本地隔离/审计/封存工程有实际证据；真实独立人审/holdout未完成，整体不签收。生产、公开、真实模型、人工8任务等另HOLD，不因这里的通过数而扩大授权。继续A47–A49工具/候选/固定回归及后续剩余断言，无需阶段确认。
