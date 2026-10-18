# 私有统计接口参考

统计仅向独立管理员提供汇总，不返回会话、轮次、反馈、任务、候选或请求的持有凭据及其摘要。来源分组只使用已验证摘要、身份和规则绑定的题库快照（包括合法历史），并非任意登记字符串；catalog损坏固定503不可用。实现：`backend/app/metrics.py`、`metrics_contracts.py`、`routers/metrics.py`。

[操作指南](metrics-howto.md) · [口径解释](metrics-explanation.md) · [实测状态](ts16-status.md)

## HTTP 参数与响应

| 方法和路径 | 参数 | 行为 |
| --- | --- | --- |
| GET `/api/metrics/admin` | 窗口、来源、limit、cursor | 同一读快照的完整汇总与一页分组；30次/60秒 |
| GET `/api/metrics/admin/export` | 仅窗口和来源，不接受limit/cursor | 新的单次读快照、完整JSON附件；5次/60秒 |

要求独立 `X-Admin-Token`，站点口令不能代替。不接受GET请求体、重复或未知参数。成功及已处理错误均 `Cache-Control: no-store`。固定附件名 `turtle-soup-metrics.json`。

| 参数 | 类型、默认值与约束 |
| --- | --- |
| start/end | UTC Unix秒，有限数，0至253402300799；含开始、不含结束。默认结束为服务端时间、开始为前7天且不早于0；最多31天，允许空窗口 |
| soupId | 可选，1至200字符，非全空白，已登记的公开题目ID |
| puzzleVersion | 可选，p1:后64位小写十六进制，来源题目版本 |
| ruleVersion | 可选，r1:后64位小写十六进制；原业务分组按来源规则版本，发布后观测按实际publishedRuleVersion筛选，两者口径不同 |
| limit | 仅分页，整数1至100，默认50；页面可选50/100 |
| cursor | 仅分页，规范base64url，1至2048字符，绑定窗口/来源/limit；只有公开分组键，不是授权凭据 |

分页响应：schemaVersion=3、consistency、query、summary、coverage、groups、nextCursor。组按UTC日/题目/题目版本/规则版本排序，未知来源保留null且排前。不同HTTP请求各有新快照，翻页不是冻结历史。

导出：schemaVersion=3、window、filters、summary、coverage、groups、complete=true、generatedAt。超过100组或512KiB UTF-8返回409，拒绝整份，不截断后声称完整。

响应格式3、分页游标格式1和数据库005是不同版本号。004仍支持原统计，发布后观测明确unknown/schema_5_required；005来源损坏时unknown/source_unavailable，observedRuns/failedRuns均null，不补0。完整005读者按startedAt半开窗口聚合出生来源与不可变账本；state为observed或partial（窗口开始早于sourceCoverageStart），historicalBackfill=false。主数只计算real，excluded.test/synthetic/unknown单列；0次真实观测不证明0错误。旧格式2消费者仅接受明确unknown/source_not_integrated，不能默默提升成新统计。`complete:true`只表示分组导出完整，不保证模型质量。本次未部署，前后端须同步更新。

### 发布后观测的完整分母

13个必填严格非负整数：observedRuns、passedRuns、failedRuns、incompleteRuns、pendingRuns、pendingExpiredRuns、plannedCases、attemptedCases、passedCases、counterexampleCases、errorCases、unsupportedCases、notAttemptedCases。四种run状态合计为observedRuns，pendingExpiredRuns只是pending子集；全部plannedCases包含未尝试项，系统错误/不支持不得删掉或算通过。expired以本次服务器时间判断，不是窗口end。失败运行不等于所有case均失败；不是准确率或真人效果。

采集只由管理员显式POST `/api/feedback/admin/post-publication-regressions`（独立X-Admin-Token，5次/60秒）触发，闭合JSON仅operationKey、candidateId、publishedRuleVersion。语料/预算/计划/结果由服务端确定，不能由客户端提交；同key只重放原记录，异内容冲突，pending不自动重跑。固定执行不连真实模型，无确定性判断时记unsupported；来源绑定已发布目标、操作回执与必要审计，不拿候选预览作发布后观察。此入口没有新增玩家问答hook/后台轮询/Agent工具。证据和限制见[D18 ledger](superpowers/plans/2026-10-13-d18-progress.md)。

后端内部默认构造可以补unknown对象/字段，前端要求完整字段；“所有后端缺字段都拒绝”不是当前实现。这个防御性合同差异是[TS17延期Minor](ts17-review-resolution.md)，不制造0次失败，也不新增调用方提交统计对象的入口。

## 九项计数

默认counts仅计算明确real，不是去重人数。

| 字段 | 时间字段与对象 |
| --- | --- |
| sessionsCreated | 会话主键按created_at |
| successfulChargedTurns | 唯一轮次按completed_at；仅completed、charged=1、kind为answer/win |
| httpAttempts | 每条合格HTTP审计按事件时间，失败与重放各计一次 |
| feedbackSubmitted | 唯一反馈按提交时间，须有匹配且无分类冲突的提交来源审计 |
| tasksCreated/candidatesCreated | 任务/候选主键按创建时间 |
| reviewApproved/reviewRejected | 对应审核动作按事件时间 |
| candidatePublicationEvents | 候选发布事件按事件时间，不重复计通用规则发布审计 |

excluded.test/synthetic/legacy/unknown各有同样九项。unscopedReal在来源筛选前计算未完整绑定来源的real行，不猜当前版本。坏格式、重复JSON对象键、外层ID/时间/类型不匹配或分类冲突不变成合法来源。反馈重复证据须每条必要字段完整且turn关联一致，单条有效证据不能掩盖缺省/null或关联冲突。

taskStates是窗口内创建任务的六种**当前**状态；candidateStates是窗口内创建候选的四种当前状态，不是截止end的历史状态。taskPublication分子为该创建队列里已有published候选的不同任务数，分母为全部队列任务数；分母0时ratio=null，不是修复正确率。

coverage保留审计/Agent开始时间、历史未知和本进程缓冲/丢失状态。进程状态不是查询窗口的历史丢失数；没有数据不能证明从未丢失。004明确noHistoricalBackfill=true，不补造旧审计。

## 拒绝与读取边界

| HTTP/代码 | 含义 |
| --- | --- |
| 401 | 独立管理员身份未通过 |
| 422 metrics_query_invalid | 参数、窗口、cursor或GET请求体不合要求 |
| 429 | 对应接口限流，保留Retry-After |
| 409 metrics_export_too_large | 缩小完整导出范围 |
| 503 metrics_busy | 锁或共享3秒SQL预算耗尽 |
| 503 metrics_unavailable | 缺004、结构损坏或读取/清理失败；不是所有503都靠迁移解决 |

专有SQLite连接、query_only和短读事务，模式校验也计入3秒预算。失败清理进度处理器、事务、连接，不输出原始SQLite错误。读路径不初始化、迁移、恢复Agent或调用模型；业务表不改写，原HTTP尝试审计仍会记录请求。

私有页面另有10秒获取/解码超时，明确提示重试并释放按钮；取消或迟到响应不能恢复旧数据/下载。这不是放宽后端3秒读取预算，也不改玩家游戏请求。

## 合成测量接口

`app.scripts.benchmark_metrics.measure_metrics(*, warmups=3, samples=20) -> dict`仅创建/清理自己的新临时目录。warmups为0至10、samples为1至100整数，bool拒绝。CLI无数据库路径、输出覆盖或模型参数。

报告保留全部实际样本、nearest-rank P50/P95、环境、CPU、Python分配峰值、DB/WAL字节、实际SQL计划、cleanupConfirmed。失败只记录固定状态/代码，没有成功或部分分位数。默认200会话/1000轮次/5000typed审计是合成统计行，不是1000次游戏请求或真实用户。

真实reader计数与独立源SQL核对；当前审计real/test/synthetic/legacy/unknown五类各1000，unknown为typed null来源，200会话和1000轮次仍为四类合法业务行。窗口从实际迁移覆盖后开始，processAudit未知仍明确unknown。reader计时含完整JSON序列化及闭合回读，serializedBytes保存每个实测样本字节数；measurementScope明确范围。索引前后只比较真实捕获的同一SQL批次，不是旧reader基线。CPU/Python峰值包含本次构造与测量；峰值不是RSS，时间包含tracemalloc开销。
