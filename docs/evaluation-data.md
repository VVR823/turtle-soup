# 独立评测数据参考

`backend/eval` 的数据模块保存完整输入、审计问题之间的关联、绑定题库版本与人工审核，再封存不可偷换的评测材料。数据模块不调用模型、不打开生产数据库，也不是 Agent 工具；TS12另有实际宿主/固定本地FakeModel运行器，见[完整分母评测](evaluation-runner.md)。通过工程检查不等于答案真的正确：目前110条私有新草案全部等待人工审核。

## CLI 接口

在 backend 工作目录使用现有 `.venv-ts01/Scripts/python.exe -m eval.cli`。没有默认路径；输入必须显式、绝对、无别名，输出必须是新文件。

| 命令 | 必需参数 | 输入 → 输出 |
| --- | --- | --- |
| inventory | --input --catalog --audit --output | CaseBundle/CatalogBundle/GroupAudit → 私有 InventoryReport |
| freeze | 同上 | 全部条件满足 → FrozenDataset；否则 needs_human 报告，不冒充封存成功 |
| repair-export | --input --output | 验证过的 dev/regression FrozenDataset → CaseBundle；holdout/candidate 拒绝 |

repair-export 可选 `--public-synthetic`，仅允许材料本身已声明 public_synthetic/public_authorized 的合成演示。私有材料不能靠开关变成公开材料；这不是上传或云调用授权，没有 `--role` 覆盖入口。

退出码0=ready、2=needs_human、1=refused。stdout 仅计数/固定错误码，不含问题、答案、审核人、路径、traceback。报告保留 sourceIssueCount；另一个 complete 审计不能抹掉原 CaseBundle 的物理异常。

## 数据合同

模型均严格、冻结、拒绝额外字段；JSON拒绝重复键/非有限数/布尔冒充schemaVersion，版本为真实整数1。完整字段类型见 [contracts.py](../backend/eval/contracts.py)/[manifest.py](../backend/eval/manifest.py)，分组见 [grouping.py](../backend/eval/grouping.py)。

- EvalCase：canonical UUID caseId，soupId/puzzleVersion/question/caseType/split/sourceGroup/familyGroup/conversationId/contextIndex/categories/visibility/origin/evidenceSourceDigest/authorRole/reviewState/proposedLabel/rawLegacyExpected/review；proposedFactIds 默认空元组。caseType=single|context|control；split=dev|regression|holdout_candidate|holdout。问题1–500字符且非空白；身份1–200字符；类别与事实各≤8且唯一；旧答案≤1000，未知/空答案不被改成正确答案。
- ExpectedLabel(kind,answer)：answer 必须是五类合法答案之一，reminder 的 answer 必须null；system_error不是标准答案。
- ReviewRecord：显式 operatorId/reviewedAt/caseDigest/expectedLabel/factIds/reviewNote/humanConfirmed=true，UTC真实日期，说明1–1000字符；answer 至少一个同p1真实f1。contextDigest仅独立题可缺省null；上下文题必须绑定context-review-v1有序前文业务摘要和人工标准答案，前文变更必须重审受影响后续题。没有默认审核人或自动确认；审核依赖中的gold不会交给模型。
- EvalPuzzle(soupId,puzzleVersion,soupJson,ruleSnapshot)：完整canonical选中Soup/p1和全量r1字节证明；所有release成员ID/版本格式/字段/overlay/parent结构复验。没有提供完整Soup的其他成员仅结构验证，不能宣称其p1内容/事实/历史parent链也已核实。静态种子来源eval-seed-snapshot，不证明生产当前版本。
- SourceDigest：sourceId/sourceDigest/questionSourceGroup/origin/collectedAt/visibility/caseIds。源字节SHA-256、UTC时间、≤5000唯一ID；questionSourceGroup是问题采集来源，不是故事作者。
- CaseBundle(schemaVersion,cases,sourceDigests,issues)：未封存草案/原文包，可盘点pending，不要求先有人工封存。
- CatalogBundle(schemaVersion,puzzles)：1–256个完整题库版本；没有生产默认加载。
- GroupAudit：完整groups/edges/quarantineCaseIds/issues，candidateInputDigest/repairInputDigest/sourceInventoryDigest/auditDigest/complete；输入变动后重新审计。
- DatasetInventory：完整inputCount、singleCount/singleSoupCount/contextGroupCount/contextDecisionCount/controlCount、pending/ambiguous/unsupported/reviewed/quarantine/eligible/issue计数、auditComplete/deficits；数量覆盖不是人工标签覆盖。
- DatasetManifest：splitRole、UTC frozenAt、完整inputCaseIds/inputCount/eligibleCount/inventory/sourceDigests/puzzleVersions/ruleVersions，casesDigest/catalogDigest/auditDigest/candidateInputDigest/repairInputDigest，exact-v1/group-v1/manual-v1、visibility/complete、自身datasetDigest。
- FrozenDataset(manifest,casesJson,catalogJson,groupAuditJson)：全量不可变canonical JSON证明，读取重新验证全部内容/分组/源/审核声明，不只信complete=true。

文件≤100MiB，cases≤5000；单条canonical case或旧文本物理行≤32KiB；manifest header+catalog+audit总证明≤2MiB，cases另计。旧文本≤20000物理行/5000问题，超限拒绝而非静默截断；CLI≤32参数，每参数≤2048字符。

## Python 操作接口

仅供可信本地操作者；路径不交给模型、不自动扫描。

| 模块 | 接口 |
| --- | --- |
| catalog | build_seed_catalog(*,soup_ids:tuple[str,...])；validate_catalog(puzzles) |
| drafts | build_pending_draft(DraftRequest(catalog,entries,authorBatchId,collectedAt))；DraftEntry含问题/分组/上下文/类别/可空proposedLabel/factIds，输出私有AI pending |
| authoring | compile_authoring(source:Path,*,cases_output,catalog_output,audit_output)；AuthoringSource显式soupIds/batch/date/entries，factSourcePaths仅bottom，旧审计始终初始unavailable |
| legacy | parse_legacy_copy(LegacySource(path,sourceId,soupId,puzzleVersion,format,sourceGroup))；format显式player_host/qa/arrow/alternating，返回全部cases/issues/physicalRows/fileDigest/complete |
| grouping | audit_groups(cases,*,repair_cases,source_digests,source_complete:bool)；input_digest(cases)；case_context_key(case,cases) |
| contracts | case_digest(case)；review_context_digest(case,cases)；review_is_current(case,cases)；validate_reviewed_case(case,*,catalog,context_cases=None)，上下文必须显式全组三条 |
| inventory | inventory(cases,*,audit,source_digests)，源记录必需；verify_audit(audit)；proofs.validate_scope(cases,proof,source_digests,role)，盘点与封存共享结构/来源/隔离检查 |
| manifest | freeze_dataset(cases,*,catalog,audit,source_digests,frozen_at)；freeze_regression同签名但仅同一dev或regression角色 |
| manifest | verify_frozen_dataset(snapshot)；load_repair_corpus(snapshot)；read_snapshot(path)/write_new_snapshot(snapshot,*,output)；read_case_bundle(path)/write_new_case_bundle(bundle,*,output) |

## 为什么修复过的题不能再证明泛化

拿考试题改程序，再拿同一套题考试，分数会虚高。旧材料仅进dev/regression，新候选关联旧池时整组隔离：来源、家族、会话、NFC原文或exact-v1相同问题形成可以传递的连通组。程序发现不了所有语义改写，仍需真实人工核对来源/家族；source_complete=true是可信操作者声明，不是数字签名或真值证明。

同故事可有新问题，但不能宣称没见过故事。三轮保留三条原文和1/2/3索引；相同代词在不同历史里可有不同答案，不去重成一条。TS12回放真实模型历史，不把标准答案喂进历史。

```text
新草案 → 全输入盘点 → 真正人工审核 ───┐
旧修复隔离副本 → 来源/家族/重复关联审计 ├→ 完整私有封存
                    关联旧修复组 → 隔离┘
```

固定最低60单问/≥6汤+10组三轮(30决策)+20控制=110；缺题/缺审核如实报告，不缩分母。代价是正式验收必须人工准备；hash防偷偷变化，不证明审核人身份或答案正确。原候选业务split不强行改写，正式角色写manifest.splitRole=holdout，避免改变已审核内容使声明过期。

## How to 盘点或请求封存私有草案

前提：已有环境和下面四份私有产物。这不是生产启动入口，不读取dotenv；每次换未存在output，不删除旧证据强行覆盖。

```powershell
Push-Location D:\CODE\turtle-soup\backend
try {
  .\.venv-ts01\Scripts\python.exe -m eval.cli inventory `
    --input D:\CODE\turtle-soup\backend\eval\private\pending-110-20261009.json `
    --catalog D:\CODE\turtle-soup\backend\eval\private\catalog-6-20261009.json `
    --audit D:\CODE\turtle-soup\backend\eval\private\overlap-unavailable-20261009.json `
    --output D:\CODE\turtle-soup\backend\eval\private\inventory-example-new.json
} finally { Pop-Location }
```

当前退出2，inputCount/pendingCount=110、reviewedCount/eligibleCount=0。换freeze并用另一新output仍退出2，只写needs_human报告，不封存。

人工流程：在私有副本逐条阅读题库与实际上下文，选择真实标准答案或ambiguous/unsupported，记录真实operatorId/UTC日期/同版本事实/说明；case_digest仅排除review/reviewState。上下文全组三条显式提供，审核人按先后顺序确认前文，记录review_context_digest，前一轮问题/答案变化后受影响的后续题必须重新真人确认，不能只让脚本刷新摘要。改来源、标签提案、版本也重审。不能复制测试synthetic-test-only声明给真实材料。合法旧隔离副本显式导入，再人工确认来源/家族和audit；保留解析问题，修复后新源摘要/新bundle，不手改complete=true。盘点必须传原CaseBundle.sourceDigests，不能从审计自摘要猜来源；全输入审核、来源与关联证明、覆盖均满足再freeze。

验证：报告有inventory/status/sourceIssueCount；正式封存用read_snapshot复验。needs_human不是模型失败；output_exists换新名字；source_changed先停写再获得合法副本；拒绝Desktop、runtime/data、.env、链接、`..`别名。

## How to 导出修复材料

只用已经freeze_regression的私有dev/regression快照：`python -m eval.cli repair-export --input <绝对快照路径> --output <新私有绝对路径>`，退出0后read_case_bundle验证。真实快照不存在时先真实审核，不用holdout/角色覆盖代替。公开合成演示需实际许可和--public-synthetic，不满足真实110验收。

错误版本/事实/角色、损坏/重复JSON、未授权公开、既有输出均拒绝。独占新写入失败保留部分新文件和固定错误，不删除/覆盖原材料，换新文件名并保留失败证据。

## 测试与状态

见[离线测试](testing.md)/[TS11状态](ts11-status.md)/[设计](superpowers/specs/2026-10-09-ts11-dataset-design.md)。测试审核是合成声明，不是人审证据。旧app/scripts/eval_host_accuracy.py已在TS12退役为惰性安全转向入口，只接受新CLI显式参数，不再默认读旧数据/筛题；原报告保留，旧99.1%不能作独立泛化成绩。运行器/最终审查状态见[TS12指南](evaluation-runner.md)/[状态](ts12-status.md)。
