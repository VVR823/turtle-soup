# TS16 私有统计设计

状态：设计已定，实施/测试/性能测量尚未完成。依据原 TS16/A57、C24；TS01–15 的本地验收不重做。沿用用户的自主决策、主代理原生实现、每阶段一位审查者授权，不新增阶段确认。

## 目标与边界

管理员能复核会话、成功计次提问、HTTP 尝试、反馈、任务、候选、审核动作与候选发布；按固定时间和来源版本筛选，显示测试排除、未知来源和审计缺口，下载明确完整的脱敏聚合 JSON。会话数不叫用户人数，机械回归/审核/发布比例不叫答案准确率。

只用现有 SQLite、FastAPI、Pydantic、React/Next 和标准库。不增加分析服务、追踪身份、第三方依赖或模型调用。默认迁移仍 001，应用初始化仍 002，Agent 默认关闭及已有预算不变。不读取真实用户库/私有 corpus/真实 dotenv，不迁移生产、不部署、不上传、不提交或更换 worktree。保留旧 001/002/003 SQL 与 checksum。

## What already exists

- `migrations.py` 注册 001–003，分阶段 BEGIN IMMEDIATE/报告/校验；复用而非并行建库。
- sessions/turns 保存创建、完成、固定版本与流量分类；turn 主键和唯一请求防止重放增加有效提问。
- `audit_store._insert` 保存完整 AuditEvent 到 details_json。因此查询路径是 `$.details.trafficClass`、`$.details.versions.*`、`$.details.feedbackId`，不是 JSON 顶层同名字段。
- feedback_items 的 source_json 不是实际流量分类；必要 feedback_submitted 审计有真实分类。合法未关联手工反馈不能被 INNER JOIN turn 丢掉。
- Agent 不可变 manifest 有 trafficClass/context；候选 SQL status 是当前工作流，不能用 candidate_json.pending 或 run.awaiting_review 替代。
- AuditStore.status 与 002/003 报告已有缺口/覆盖起点；统计只读，不自动 recover。
- 独立管理员口令、固定路由限流、管理页 token epoch/Abort 防迟到响应、隔离 pytest/Vitest/真实 Edge 流程均复用。

## 1. 时间、来源和分母

统一半开窗口 `[start,end)`，UTC 秒；默认 end=当前时间、start=end−7×86400；0 ≤ start ≤ end ≤ 253402300799、最多 31×86400 秒，拒绝 bool/NaN/Inf/非法类型。空窗口合法零结果；Unix 初期默认 start 截为 0。所有一次响应的 SQL 在一个短读取事务/快照内完成。

| 指标 | 权威记录与时间 | 计数规则 |
|---|---|---|
| sessionsCreated | sessions.created_at | 按 session 主键；不是独立人数 |
| successfulChargedTurns | turns.completed_at、实际 session 分类 | completed、charged=1、kind∈answer/win；主键一次；失败、提醒、重放 HTTP 不增加 |
| httpAttempts | audit_events.created_at/event_type=http_attempt | 每实际事件一次，重试/replayed 仍是另一 HTTP 尝试，不当成新提问 |
| feedbackSubmitted | feedback_items.created_at | 反馈主键一次；匹配同创建时间的必要提交审计得到分类；同类重复证据不增加，缺失/矛盾归 unknown |
| tasksCreated | agent_runs.created_at | 所有六种状态均保留，不仅成功或有候选任务 |
| candidatesCreated | rule_candidates.created_at | 候选主键一次，当前 status 不影响创建数 |
| reviewApproved / reviewRejected | candidate_reviewed.created_at | 对应 action 的审核动作数；不是唯一审核人/唯一候选数 |
| candidatePublicationEvents | candidate_published.created_at | 候选发布动作数；不再加同次 generic rule_published |

只计显式 real 进默认 counts。分别返回 excluded.test/synthetic/legacy/unknown 的同指标 counts；不可将未知归 real 或把无审计记录解释成真实零。反馈无必要来源审计属于 unknown；历史 legacy 来源明确时可归 legacy。业务表损坏/无法验证数据库结构是统计不可用，不将其吞掉为零。

版本筛选固定是**原始来源**：soupId、puzzleVersion、ruleVersion。sessions/turns 取固定来源列；已关联反馈只取已核实 source 的来源版本/实际 turn；任务/候选/审核/发布取 run.manifest.context.soupId/observedPuzzleVersion/observedRuleVersion。baseRuleVersion 与发布后的 toRuleVersion 不是本接口的过滤维度。

HTTP 的 HostVersions 取该事件实际 `details.versions`，soup 只能由实际关联的 turn/session 取；没有关联或版本记录不猜当前题目/版本。未关联手工反馈保留其真实分类、公开 soupId，但版本 null。未筛选时这些 real 记录保留，并以 null 维度及 unscopedReal 计数明确显示；指定题目/版本时未知值不匹配。unscopedReal 是同时间窗、筛选前的提示，不是已筛选 counts 的子集。

维度不是任意自由字符串：soupId须来自已验证题库快照的题目集合，puzzle/rule版本符合既有p1:/r1:格式且来源绑定一致；畸形、未注册或互相矛盾的维度输出null/unknown，不将原字符串反射到统计/游标/导出。必要审计的外层eventType/eventId须与SQL列一致；任务关联审核/发布的event分类与不可变run分类矛盾归unknown。上述守卫用于统计解释和隐私，不成为新业务权限或人工语义判断。

任务/候选状态分布是**窗口内创建队列的当前状态**，不是截至 end 的历史状态。taskStates 含 queued/running/awaiting_review/needs_human/failed/cancelled；candidateStates 含 pending/approved/rejected/published。taskPublication.numerator 是创建队列中当前有 published 候选的 distinct run，denominator 是完整 real tasksCreated；零分母 ratio=null。发布后回滚仍保留已发布历史，不叫“修复正确率”。

## 2. 查询与闭合响应

主模块 `backend/app/metrics.py`（不另建 MetricsService）。纯查询模型/游标放 `metrics_contracts.py`，私有 HTTP 放 `routers/metrics.py`。

`MetricsQuery`：start/end、soupId/puzzleVersion/ruleVersion（可空）、limit 默认50/1–100、cursor（可空、最多2048 ASCII base64url字符）。公开题目ID最长200，沿用 p1:/r1: 版本验证。未知参数/重复参数/请求体/非法数值拒绝422，不动态拼 SQL 用户值。

`query_metrics(runtime, query: MetricsQuery) -> MetricsPage`：不初始化数据库/迁移/恢复审计/读取模型。专有 mode=rw URI连接只打开已存在隔离配置所指库、PRAGMA query_only=ON、BEGIN读取；结构要求004。整体3秒 deadline，progress_handler每1000指令中断，busy_timeout最大500ms并受剩余时间约束；finally回滚读取事务/清理handler/关闭连接。结构缺失/漂移=503 metrics_unavailable，锁/超时=503 metrics_busy；不输出原异常或私密SQL值。已有结构校验也受同一deadline约束。

SQL先按各自时间索引缩窄，再参数化 JOIN/聚合，不逐条拉问题、manifest/candidate/报告全文到 Python。不新增物化统计表/缓存。反馈必要审计匹配在同一时间范围内批量归类，矛盾证据显式 unknown。JSON先 json_valid 再 json_extract；缺失/非法/类型错误的元信息不能当 real。SQL 分类只用于统计，不授予业务/发布权限。

一次读快照内：完整汇总 counts/excluded、当前队列状态/发布分母、覆盖元信息、按 `(UTC日,soupId,puzzleVersion,ruleVersion)` 分组的公开聚合页。排序明确 null 在前，统一不可碰撞的排序键；页查询 LIMIT limit+1，返回至多 limit 行。响应只投影公开分组键、非负整数 counts 和闭合的窗口/分页/覆盖说明，不返回任何行级身份或自由文本。

游标严格 canonical JSON/base64url、schemaVersion=1、绑定 start/end/全部筛选/limit 和最后公开分组键。后续请求省略 start/end 可恢复游标的窗口；显式筛选或 limit 不同拒绝422，未知字段/重复 JSON 键/非法null键/非canonical编码拒绝422。游标没有权限，不用签名替代管理员鉴权。

分页窗口固定，但每次 HTTP 是新的读取快照，**不承诺跨请求静态快照**。响应 consistency=`fixed_window_live_snapshot`，管理页说明运行期间计数/状态可能变动，重新查询回第一页；禁止把拼接多页当作完整冻结导出。关闭读取事务后再读进程审计 status；status 缺失/待落盘/永久缺口都明确输出，不能扩大 SQL 窗口覆盖承诺。

## 3. 缺口、私有 HTTP 与导出

响应 coverage 明确：auditStartedAt、agentStartedAt、historicalAttemptsBackfilled=false、historicalRunsBackfilled=false、windowStartsBeforeAudit/windowStartsBeforeAgent、processAudit（complete/permanentGap/dropped/fallbackCount/memoryCount/activeIO 或 null），以及警示状态。进程 dropped 是全进程数，不是本窗口精确丢失数；complete 只表示此时已知进程没有待落盘缺口，不证明模型语义正确或历史完整。缺口不清空数据库内已知聚合值。

- GET `/api/metrics/admin`：独立 X-Admin-Token，30/分钟，闭合查询和响应。
- GET `/api/metrics/admin/export`：同鉴权，5/分钟，仅 start/end/soupId/puzzleVersion/ruleVersion。不接受 cursor/limit；一个新读快照，最多100分组、最多512KiB UTF-8 JSON。101组或字节超限返回409 metrics_export_too_large，提示缩小范围/题目/版本；**拒绝而非静默截断**。空统计可导出明确完整空数组。
- 导出从同一闭合字段白名单新构造，含 schemaVersion、固定window/filters、完整summary/coverage/groups、complete=true、generatedAt。无原文/背景/模型输出/审核理由、无 session/turn/request/feedback/run/candidate/op/event ID、无其散列。题目/版本是公开维度，不导出令牌/路径/自由文本。
- JSON下载不使用CSV，免新增公式注入面；固定文件名/content-disposition、Cache-Control:no-store、响应超限无半份文件。
- StrictJSONRoute/现有鉴权错误处理复用，新路由加入 audit_middleware 固定模板；统计GET仍只有正常HTTP尝试审计，不修改业务数据。HTTP尝试结束后才落盘，当前请求不虚算进当前读快照。

## 4. 索引与显式004

候选索引仅覆盖确实用到的创建/完成时间：`idx_sessions_created(created_at,id)`、`idx_turns_completed(completed_at,id)`、`idx_feedback_created(created_at,id)`、`idx_agent_runs_created(created_at,id)`、`idx_rule_candidates_created(created_at,id)`。复用既有 `idx_audit_events_time`。不预建所有版本/流量组合。

追加 METRICS_SQL/CHECKSUM_004（coverageContract=`metrics-indexes-v1`），只建上述索引和004报告/版本记录，不改旧数据，不回填。报告 phase004 精确含 checksum/indexNames/noHistoricalBackfill=true，继承003报告且 migrationVersion=4。注册验证接受1–4正确前缀，对>=3仍验证003全部结构与报告，对4精确验证索引定义及004报告，缺失/改列/错报告/错checksum/缺号/未来5均拒绝。

`migrate(...,target_version=1)`仍默认1；显式4先正常完成003，再一次BEGIN IMMEDIATE完成004，任意DDL/报告/版本/验证/完整性/commit错误仅回滚004。已有有效4上重跑1/2/3返回旧原报告、不写数据；4重跑同样只读返回原004报告。CLI仅扩展显式choices到4，不更改路径/隔离/退出码/默认版本。默认应用不偷偷升级004；未升级仅统计不可用，普通游戏/审计/Agent保持旧兼容。

实际合成 EXPLAIN 证明范围reader使用这些索引；如无收益或SQL未用到，先调整查询，不声称索引生效。旧 checksum 与SQLtuple/native测试必须保持。

## 5. 管理页与隔离验证

existing `/admin/feedback` 添加 `MetricsPanel`，手动打开/查询/切换题目与版本/下一页/下载；不在游戏页面轮询。token更换/清除、筛选变化、卸载时 abort+epoch fencing，迟到响应不能显示/下载旧私有数据。双击禁用运行中按钮；401/429/超时/503/409/非法响应/空页有中文恢复提示。未知版本显示“版本未知”；不可用显示原因不画零图；审计缺口可见；会话不是人数、分母和当前状态/窗口口径解释可见。导出必须用当下有效令牌重新获取后端完整快照，不能在浏览器拼页。

owned TESTING UI fixture显式升级004；不改变正式初始化/Agent开关。真实Edge观察合成游戏+反馈+修复流程产生的 test 排除，私有统计鉴权/窗口回读/缺口/空数据/下载无私密字段。单元/HTTP验证独立的声明合成 real 标签数据计数，不包装为真实访问。

## 6. 性能证据

标准库测试/测量脚本只创建新的隔离临时库，明示 synthetic 数据：200 sessions/1000 turns/5000 audit events；分类包含real/test/synthetic/legacy/unknown并给预期计数，尺寸按实际SQL复核。固定独立时钟或覆盖起点后的样本，不修改报告以假装历史已回填。无真实数据/模型/corpus调用。

实际生产query_metrics路径3次热身、20次样本，保留每次耗时；nearest-rank P50/P95、错误数、process_time CPU秒、tracemalloc Python分配峰值（不是RSS）、DB/WAL字节、Python/SQLite/OS/CPU数量/数据规模/窗口配置。真实reader观测SQL/参数和EXPLAIN，证明有界返回/非N+1；不只对自写近似SQL计时。

前后对比：从实际reader捕获的**同一聚合SQL批次**，在两个纯合成同内容库对比004索引前后，标明这项是查询批次测量、不含schema验证；另报带004校验/连接/序列化的当前完整reader耗时。所有数字由运行产物产生，不预填阈值或“提升百分比”。测量失败保留错误，不转换为准确率、LLM延迟、生产QPS或用户数。

## NOT in scope / 明确待定

生产004迁移/部署/真实流量读取/公开导出需要另行权限，独立HOLD，不阻塞本地A57。稳定去重人数无身份依据不做；真正语义准确率需独立人工证据不做。跨请求长驻SQLite快照、数据仓库/Redis/多副本、任意规模导出不做：增复杂度和锁/隐私风险，没有本阶段需求。既有测量触发共享Worker TODO不提前实现。TS15两个Minor及缺corpus浏览器覆盖留TS17，不借统计阶段重审修复系统。

## 工程审查的采用与限制

使用 Superpowers 设计/计划和 gstack 工程四区检查，用户已明确不要阶段提问；本设计按既定授权决定范围，不执行技能通用的全局写入/同步/遥测/新CLI代理/提交/上线/重复审批。四区结论及逐项取舍写入实施计划末尾，属于主代理自审，不伪造独立/跨模型审查。独立审查仍只在整阶段完成后派原约定的一位。

SQLite 文档支持一次读取事务的历史快照，**不支持本方案凭游标跨HTTP保持同一快照**：[Transactions](https://www.sqlite.org/lang_transaction.html)。索引以实际查询计划验证：[Query planner](https://www.sqlite.org/queryplanner.html)。progress_handler使用已安装Python标准库接口而非新依赖：[Python sqlite3](https://docs.python.org/3.13/library/sqlite3.html)。
