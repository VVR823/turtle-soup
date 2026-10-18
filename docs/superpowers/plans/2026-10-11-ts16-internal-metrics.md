# TS16 Internal Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the user-authorized main-agent native execution, task-by-task. Checkboxes are actual progress, not intended completion. One independent reviewer only after the whole stage; no per-task peers, extra CLI or phase approval.

**Goal:** 实现原TS16/A57、C24的有界、可复核、私有统计与真实合成性能证据。

**Architecture:** 复用现有SQLite/业务权威行/必要审计与管理认证。一个纯聚合模块、一份闭合契约、一份薄路由和一个管理面板，不另建统计服务。004只追加被实际范围查询使用的索引，显式迁移，旧应用默认行为不变。

**Tech Stack:** 已安装Python3.13/sqlite3、FastAPI/Pydantic、Next/React/TypeScript、pytest/Vitest/Playwright/owned Edge；零新增依赖/模型调用。

**Spec:** [TS16私有统计设计](../specs/2026-10-11-ts16-internal-metrics-design.md)；读全文再执行。

## Global Constraints

- 默认迁移仍001，应用初始化仍002，Agent默认关闭及已有预算不变。保留001/002/003 SQL与checksum，不读真实用户库/私有corpus/真实dotenv。
- 零新增付费/依赖/模型调用；不迁移生产、不部署、不上传、不提交或更换worktree。旧239运行文件字节保护，用户脏修改保留。
- 窗口`[start,end)`、UTC，默认7×86400秒，最多31×86400秒，有限数值0–253402300799；默认limit50、1–100，cursor最多2048 canonical base64url字符。
- 单次reader一个快照，deadline3秒/progress_handler1000指令，busy_timeout≤500ms且受剩余时间约束；参数化SQL/聚合列投影/limit+1，不取逐行私密全文。
- 默认仅real；test/synthetic/legacy/unknown分别排除。来源版本按observedRuleVersion，非base/to；成功计次turn不由消息或HTTP推算。
- 导出单快照至多100组/512KiB UTF-8，101组或超限409拒绝，不静默截断。无原文/敏感个体ID/其哈希，固定JSON下载/no-store。
- 不承诺跨HTTP静态快照；`fixed_window_live_snapshot`明确显示。覆盖未知/不可用≠0，任务分母全六状态，发布比例非语义准确率。
- 使用apply_patch编辑。测试/服务运行时冻结源码/测试，不开并发门禁；读取同一实际句柄终态再推进。quota仅正常调度后实际恢复，不买卡/额度、不重派审查者。

## Review Focus

1. 旧库只有001/002/003或004漂移：统计不可用、旧业务仍兼容，不自动迁移。归Task1/2的`test_required_004_refuses_old_phase_without_writes`/`test_query_never_initializes_schema`。
2. feedback无关联/重复或矛盾必要审计、malformed JSON：合法手工反馈保留，未知不混real，不泄漏原文。归Task2的`test_feedback_provenance_is_batch_bound_and_unknown_explicit`。
3. task来源observedRuleVersion与base/to不同、HTTP缺来源：只筛来源，不猜当前版，完整分母/unknown提示一致。归Task2的`test_source_version_not_base_or_published_target`。
4. 迟到私有响应/下载、token清除、改筛选/rapid点击：无旧私有数据恢复，清楚可重试。归Task3的面板epoch/Abort/下载与真实UI控制。
5. 写入并发/锁/deadline/导出101组/字节超限：快照内一致、事务收回，拒绝半份导出，不长时间影响游戏。归Task2/3的真实SQLite barrier/timeout及完整导出拒绝测试。

## File responsibilities and interfaces

- Modify `backend/app/migrations.py`：注册/验证/事务004；旧SQL与checksum表达式原字节不变。
- Modify `backend/app/scripts/migrate_data.py`：choices仅加4；原隔离/默认1保留。
- Create `backend/app/metrics_contracts.py`：MetricsQuery/MetricsCounts/MetricsGroup/MetricsCoverage/MetricsSummary/MetricsPage/MetricsExport、MetricsError、parse_metrics_query/encode_metrics_cursor/decode_metrics_cursor/export_projection；闭合类型与白名单。
- Create `backend/app/metrics.py`：`query_metrics(runtime, query: MetricsQuery) -> MetricsPage`、`export_metrics(runtime, query: MetricsQuery) -> MetricsExport`，两者共用有界同快照读取而非浏览器拼页。
- Create `backend/app/routers/metrics.py`；Modify `main.py`include router、`audit_middleware.py`模板注册，无玩家路径修改。
- Create `src/lib/metrics-contract.ts`（strict decoder）/`src/components/MetricsPanel.tsx`；Modify管理page.tsx接线，与原审核tokenepoch一致。
- Modify `backend/testing/ui_agent_fixture.py`显式owned004；Create声明合成测量 `backend/app/scripts/benchmark_metrics.py`、新测试/文档。所有量化产物只到.cache/ts16，既有TS15冻结快照保持历史，不覆写。

## Task 1: Append-only004 compatibility gate

**Files:** migrations.py、migrate_data.py；Create `backend/tests/test_metrics_migrations.py`。不改旧migration测试来放宽契约。

**Interfaces:** `METRICS_SQL: tuple[str,...]`五个设计指定索引；`CHECKSUM_004: str`；`migrate(conn,soups,*,legacy_records=None,target_version=1)->dict`接受1–4；`verify_schema(conn,*,required_version=1)->None`验证1–4正确前缀及所有已注册阶段。

- [x] Write actual failing native test `test_registered_004_indexes_and_report`: `report=migrate(conn,[puzzle()],target_version=4); assert report['migrationVersion']==4; assert report['phase004']['noHistoricalBackfill'] is True; verify_schema(conn,required_version=4)`；逐索引核对PRAGMA列顺序，旧三checksum与SQLbytes保存。
- [x] Run `node scripts/test-backend.mjs backend/tests/test_metrics_migrations.py -q --junitxml=.cache/ts16/migration-red.xml`：实际EXIT1/29FAIL1旧默认controlPASS，拒绝未注册4/CLIchoice4。
- [x] Add native old1/2/3 read-only refusal、4重跑/旧原报告/全部原行不变、每DDL/报告/版本/验证/完整性/commit确实命中注入的仅004回滚、错索引/报告/checksum/缺号/未来5拒绝，以及CLI显式4/默认1/旧路径拒绝测试。
- [x] Implement只追加索引004及严格phase004报告；现migrate主体提取为`_migrate_to_agent(...target_version=1)`保持旧行为，新migrate wrapper按目标先003，再原子004；`verify_schema`>=3保持Agent校验。不在GET/初始化加迁移。
- [x] Run新模块及旧`test_migrations.py test_audit_migrations.py test_agent_migrations.py test_migration_cli.py`：137PASS；完整86967实际EXIT0/2460Pythonrecords2450PASS10既有SKIP，含Eval412，加frontend289/Node25/API3=2767离线PASS。API110612正常关闭，原239sameSHA；HEAD/index未变。1个pytest缓存目录权限警告及既有Node颜色warning保留记录，下次full显式PYTEST_ADDOPTS用.cache/ts16，非业务失败/不改ACL。不提交Git。Task1本地兼容完成；索引实际聚合reader/EXPLAIN仍归Task2，TS16未完成。

## Task 2: Closed aggregation reader, provenance and measured query path

**Files:** metrics_contracts.py、metrics.py；Create `backend/tests/test_metrics_queries.py`、`test_metrics_contracts.py`、`test_metrics_query_plan.py`；Task4的benchmark复用此reader。

**Interfaces:**
`parse_metrics_query(values: list[tuple[str,str]], *, now: float, export: bool=False) -> MetricsQuery`，消费原QueryParams.multi_items以拒绝重复/未知参数；reader也重新校验调用方模型。
`MetricsPage`包含schemaVersion1、consistency、query(window/filters/limit)、summary、coverage、groups（≤limit）、nextCursor。
`MetricsSummary`有counts/excluded[test,synthetic,legacy,unknown]/unscopedReal、taskStates/candidateStates、taskPublication[numerator,denominator,ratio]；九字段counts见Spec表。
`MetricsExport`只白名单schemaVersion/window/filters/summary/coverage/groups/complete/generatedAt，无cursor/敏感ID。`MetricsError(code,status)`不携带原异常值。

- [x] Write `test_successful_turns_not_messages_or_http_replays`：实际创建2声明合成real-tag会话/actualreserve+finish重放、answer/reminder/system_error/win，8消息/2计次和4实际AuditStore.record_attempt已核对；query-interface-native-red.xml真实1缺readerFAIL。两次前置夹具错误分别保留，非产品RED；预期reader计数2/2/4及零分母null仍待GREEN。
- [x] 实际参数、边界、cursor与来源/分类控制在119定向、274当前定向和7695当前完整门禁通过；literal RED与前置夹具错误分别保存在ledger，无猜当前版本。
- [x] 完整typed审计/业务来源、反馈关联/冲突/缺失、六任务/四候选状态、审核/发布去重、跨时间口径、未知/私密canary已原生通过；声明合成统计不是人审证据。
- [x] 闭合parse/models/canonicalcursor及专有query_only同快照参数化CTE/lookahead已实现；metrics.py含流向图，无新服务/缓存。
- [x] 实际SQLite barrier/锁/共享预算/清理故障/旧schema拒绝与coverage未知控制通过，native真实RED→GREEN详细证据保留。
- [x] 实际200/1000/5000、两条聚合SQL和所有五个004/审计时间索引EXPLAIN已测；不逐行读私密原文。当前274定向/2944离线通过与独立源计数成立；两条聚合不是整个生命周期所有SQL数，不冒称并发吞吐或模型质量。

## Task 3: Private HTTP and actual admin interactions

**Files:** routers/metrics.py/main.py/audit_events.py、metrics-contract.ts/MetricsPanel.tsx/page.tsx、owned UI fixture；Create `backend/tests/test_metrics_http.py`、前端contract/paneltests；existing `tests/ui`下新增`admin-metrics.spec.ts`。固定模板的实际所有者是 audit_events.ROUTE_TEMPLATES，audit_middleware 原有编译/匹配逻辑复用，不为注册两条模板重写中间件。

**Interfaces:** GET两个固定路径/独立X-Admin-Token，summary30/min/export5/min；消费Task2parse/reader/export。`readMetricsPage(value:unknown)`、`readMetricsExport(value:unknown)`闭合解析；`MetricsPanel({adminToken}: {adminToken:string})`清除epoch并仅手动操作。

- [x] HTTP真实404 RED ->薄路由；35原生HTTP鉴权/旧库/限流/重复/坏cursor/body/模板/privacy控制包含在实际full44194，错误no-store两类真实RED已修，不用mock替代。
- [x] actual100完整/101拒绝、UTF8 guard低TEST阈值保留真实512KiB、空完整、独立SQL快照控制/私密canary/拒绝分页导出均原生通过；真实Edge105拒绝+筛选27完整实际文件，不把50页当导出。
- [x] 薄路由/固定模板/固定附件/no-store；decoder缺模块transform RED准确记录为无可运行断言，28原生frontcontract GREEN闭合验证，非虚报28RED断言。
- [x] 真实MetricsPanel接私有页，334完整frontend/type0lint0；真实2token/filter复活RED修正，pending/inflight/errors/zero/malformed/abort/lateexports/unmount/doubleclick均有控制，無gamepoll。详细证据/rulings在ledger。
- [x] freshownedfixture显式4+nonce标记/CLI体量只ownedDB，无生产/默认迁移；32realEdge/build0/normal双关闭，完整27组下载13416bytes/私密SID-token不泄漏、主代理检查截图、375DOM无溢出。CurrentTask3full44194 actual2941offlinePASS10existingSKIP/API73832正常退出/原239sameSHA/HEAD-indexsame；QA main非独立review。Task3 LOCAL完整，不代表整个TS16或模型质量。

## Task 4: Synthetic evidence, final one-peer gate and handoff

**Files:** benchmark_metrics.py、`backend/tests/test_metrics_benchmark.py`、docs/metrics.md/QA输入/README局部与TS16ledger；仅最后新增TS16审查报告/裁定文档。

**Interfaces:** `measure_metrics(*, warmups:int=3,samples:int=20)->dict`仅创建/删除自己新的TemporaryDirectory。CLI无用户库路径/模型/覆盖输出参数；结果stdout由常规工具保存.cache/ts16，不内建公共上传。报告actual规模/计数/env/all20samples/nearest-rank/P50/P95/CPU/Pythonalloc/DBWAL/SQLplan和明确synthetic标签。

- [x] benchmark实际3缺模块RED/0.80s → 3原生GREEN/11.10s；200/1000/5000、3/20全样本/nearest-rank/独立源计数/失败无分位数与清理已验证。
- [x] 实际独立CLI20samplesJSON/SQLplan/resources在.cache/ts16/benchmark-measured.json，真实reader90.63/92.49ms，批次before80.75/83.30、after80.38/82.00，标注tracemalloc开销/合成/非RSS/非旧reader；不保证巨大加速/机器容量。
- [x] 当前274定向/type0lint0及完整7695EXIT0/2944离线通过10既有跳过（2582Python含412Eval+334front+25Node+3API），API71512正常关闭/原239sameSHA/HEAD-indexsame；diff-check0带既有CRLFwarning，无Git写入。
- [x] 四docs reference/howto/explanation/status、README/backendREADME/migrations已同步实际口径/004模板/HTTP模板/实测表与边界；文档原生命令42PASS2.58s；修正checker空父路径后实际7docs66links0broken、limited格式密钥pattern0，不称完整安全审计。TS15旧snapshot不覆写，TS16新source/evidence在唯一审查前冻结。
- [x] ONE clean whole-TS16reviewer实际completed/关闭，完整原文及逐项5I/3M/21Declined裁定保存；M2/M3上调Important，同一次C-I native修复含真实Edge发现的大catalog重复验证，最后完整96815 EXIT0/2982离线PASS10既有SKIP（2604Python含412Eval+350front+25Node+3API）、当前Edge32PASS/build0/正常双关闭。原239字节/HEAD-index不变，不派重审；M1 Minor明确延续TS17。
- [ ] 原A57尚有D18“后续回归失败数”权威来源未实现，不能标原完整A57全部通过。TS16现有工程子集的审查/最终门禁已闭合；按用户“暂搁无法决定部分，先做不受影响工作”接TS17本地发布/恢复，不等待阶段点击，不删除D18或把未知报0。真实human/provider/prod仍HOLD；整18本地范围及D18可离线实现部分真正完成前不结束目标/停止hourly。

## Test/user-flow map and failure handling

```
explicit004 -> oldphase/read-only拒绝 -> migration tests [PLANNED]
           -> atomic indexes/report/commit -> fault+old-row tests [PLANNED]
admin query -> strict/auth/rate -> HTTP refusal tests [PLANNED ->E2E]
            -> dedicated read snapshot
                 -> range/provenance/unknown -> queries tests [PLANNED]
                 -> summary/allstates/denominator -> queries tests [PLANNED]
                 -> group cursor/window -> contracts/query tests [PLANNED]
                 -> lock/deadline/close -> barrier tests [PLANNED]
            -> token/filter fences -> Panel tests + real Edge [PLANNED ->E2E]
admin export -> single snapshot/<=100+512KiB
             -> reject too large/no partial JSON -> HTTP+Edge [PLANNED]
synthetic benchmark -> actual SQL/EXPLAIN/20 samples -> nativebench [PLANNED]
```

这是计划路径图，不是已执行覆盖率/语句覆盖率。新增LLM/prompt路径=无；既有Eval保留整套门禁，不加收费评判。每错误路径都有中文可恢复原因：旧库503明确未显式004；坏输入422可修改；限流429等待；忙/超时503可重试；export409缩小范围；token变动撤销显示/下载；coveragegap不把未知清零。任何新静默失败都阻断该任务完成。

## NOT in scope / sequential execution

不读/导出真实生产数字，不迁移/部署/公开、不改变玩家业务/Agent预算、不做去重人数/真实语义准确率、不造多副本或长驻跨HTTP快照。大规模export明示拒绝，非静默省略原A57。既有共享Worker TODO未达测量触发；TS15Minor/缺corpus浏览器场景保留TS17。Sequential implementation: migrations -> reader -> HTTP/UI -> measured evidence/one peer；共享契约/SQL/fixture，按用户要求不做并行worktree。

## GSTACK REVIEW REPORT（实施前历史设计自审）

以下表格/VERDICT是当时的设计状态，不是当前门禁。当前完整原审查/逐项修复/最终证据分别见 docs/ts16-review-report.md、docs/ts16-review-resolution.md、docs/ts16-status.md；原A57 D18来源欠项仍保留，不以工程子集验收覆盖原范围。

技能全文及sections全文读取后按用户原授权做主代理工程自审；不运行全局gstack脚本/同步/遥测/新CLI、额外outsidevoice或重复确认，不伪造完整独立gstack管线结果。

| Review | Runs | Status | Findings / decision and cost |
|---|---:|---|---|
| Scope / Step0 | 1 main | adopted original TS16 only | >8文件主要是契约/薄路由/测试/单面板，不新增服务；保留必要错误/UI/测量不压成只有一个SQL |
| Architecture | 1 main | design addressed | 原数据库不支持004：追加indexes-only+旧phase兼容；多页无同快照保证：明确live并单请求完整export，成本最多100组拒绝大导出 |
| Code quality | 1 main | design addressed | feedback缺分类与完整audit envelope：复用必要提交/`$.details.*`，批量、未知明确；闭合白名单，非拉整行再删敏感字段 |
| Tests | 1 main | planned, not passed | 五ReviewFocus均有task/native或UIowner；实际RED/GREEN、SQLitebarrier/EXPLAIN、真实Edge下载、旧migration/default保持 |
| Performance | 1 main | planned, not measured | 五时间index仅针对查询，3秒读取deadline；actual200/1000/5000、同SQL批次before/after+fullreader20samples，CPU/alloc不冒充RSS |
| Independent/outside voice | 0 | intentionally deferred | 用户限每阶段一位整体审查者，Task4统一执行，不把主代理自审叫独立意见 |

VERDICT: 设计及实现顺序可按既定自主授权执行；产品/测试/量化/整阶段独立审查尚未完成，不能声称A57已通过。生产及真实质量仍是权限/证据HOLD，不是待决定的本地设计。

NO UNRESOLVED DECISIONS
