# 修复 Agent 循环参考（TS14）

本页描述已实现的服务器接口和限制，不是生产启用指南。TS14 最终门禁与独立审查进度见[状态](ts14-status.md)；首次理解请读[大白话解释](agent-loop-explanation.md)，本地复现见[操作指南](agent-loop-howto.md)。五工具参数与报告合同见[工具参考](agent-tools-reference.md)。

## 启动前提

`Settings.ENABLE_AGENT` 默认 `False`；关闭时没有后台 worker，也不因访问接口创建模型网关或迁移003。显式启用要求 `API_WORKER_COUNT == 1`、已有合格003结构、独立管理员口令，以及反馈/关联回合/人工隐私许可/版本的服务器验证。普通应用初始化仍到002，不自动升级已有库到003。迁移仅遵循[隔离迁移说明](migrations.md)，本轮没有生产迁移。

`Runtime.start_agent_worker()` 在应用 lifespan 中执行。启用时先验证003，再创建本应用唯一协调器；重复调用返回已有 worker。运行材料从 SQLite 重新冻结，不能用请求正文指定模型、权限、工具清单、流量类别、题集、租约、预算或执行代码。没有真实关联回合不能捏造任务。

## 管理 HTTP

全部路径需要独立 `X-Admin-Token`；站点的 `X-Site-Token` 不能替代它。口令未配置或功能关闭安全拒绝。下列 UUID 仅作格式示例，不对应实际反馈，不能直接启动真实任务。

| 方法与路径 | 正文 | 成功响应 | 每来源限流 |
| --- | --- | --- | --- |
| `POST /api/feedback/admin/agent-runs` | `feedbackId`、`requestId`、`expectedFeedbackVersion` | 202，只有 `runId` | 20/分钟 |
| `GET /api/feedback/admin/agent-runs/{run_id}` | 无 | 200，最小状态 | 30/分钟 |
| `POST /api/feedback/admin/agent-runs/{run_id}/cancel` | 只有 `expectedRowVersion` | 200，最小状态 | 20/分钟 |

启动正文示例：

```json
{"feedbackId":"11111111-1111-4111-8111-111111111111","requestId":"22222222-2222-4222-8222-222222222222","expectedFeedbackVersion":0}
```

版本必须是真正 JSON 整数，范围 `0..9223372036854775807`，不接受布尔值、字符串或小数。拒绝额外字段、重复 JSON 键、NaN/Infinity、非规范 ID，管理 JSON 输入最多32KiB。相同有效启动意图重试返回同一 `runId`，即使任务已经前进也不返回另一种确认正文；冲突意图或陈旧版本409。授权/冻结材料已经撤回时，不能靠旧 `requestId` 绕过当前授权。

取消使用刚读取的 `rowVersion`。心跳也会推进版本，409后需重新读状态，不能盲目覆盖。取消 queued/running 会写终止记录并清除租约；当前版本的 cancelled 重放不另扣预算。不存在404、输入不合格422、超大正文413、限流429附 `Retry-After`，功能不可用503。错误返回安全的 `detail/code/requestId`，不回显私密输入或原始异常。不同任务 ID 不能绕过同一路由的限流桶。

最小状态字段：`id`、`state`、`rowVersion`、`modelAttemptsUsed`、`toolAttemptsUsed`、`deadlineAt`、`reason`、`candidateId`、`steps`。每个步骤仅有 `seq/action/state/tool`，最多32个；不含提示词、反馈正文、事实原文、租约令牌或模型原始输出。材料授权撤回后管理员仍可读取这种摘要或取消；这不恢复执行权限。

状态集合：`queued / running / awaiting_review / needs_human / failed / cancelled`。`reason` 可以为空（模型正常 finish），也可以是 `source_changed / permission_revoked / budget_exhausted / deadline / model_output_invalid / tool_failed / model_unavailable / cancellation / shutting_down / missing_corpus / context_too_large`。代码列表不是对每个停止分支已取得真实模型证据的声明。

**本阶段没有候选批准或发布 HTTP。** `awaiting_review` 仅表示保存了本任务的待审核候选；没有切换正式规则、缓存版本指针或旧局答案。

## 服务器循环与持久化

`RepairAgent(store, executor, gateway).drive(run_id, lease_token, cancelled)` 返回 `AgentStatus`。模型只选五工具之一或 `finish`；`model_decision/server_stop` 是内部持久化动作，模型不能提交它们。

| 约束 | 当前实现 |
| --- | --- |
| 全任务模型尝试 | 最多10，先原子预留，再尝试网关；恢复不退次数 |
| 全任务工具尝试 | 最多8，失败/未知预留保留；一次重试使用新序号和操作 ID |
| 纠错 | 同一无效/未知决策 episode 最多一次；不无限修格式 |
| 工具重试 | 同一精确动作最多一次；需要本任务失败/未知父记录 |
| 总期限 | 第一次领取起180秒；排队未领取不计时；接管/重启不刷新 |
| 单次决策 | 网关 `max_attempts=1`，最多剩余期限与45秒中的较小值 |
| 提示词 | 系统与任务内容合计最多8000字符；不是token数 |
| 模型动作输出 | 严格JSON，最多32KiB UTF-8；宿主答案仍走原合同 |
| 排队容量 | 最多10个queued任务，不是持久化历史总条数 |
| 租约 | worker60秒、独立10秒心跳；独立仓储默认30秒 |
| 本地模型准入 | 全网关最多2个所有者、Agent最多1个；在线等待者优先 |

`build_decision_messages(run, steps)` 使用审核脱敏上下文和实际存储的步骤结果，返回消息及输入/提示词摘要。不放入标准答案、holdout或模型隐藏思维。历史保留每个序号、动作、失败和未知状态；精确重复内容可以引用原序号，不删除失败、不截掉分母。无法装入8000字符则转人工。

意图和结果分两次短事务保存，计算期间不持有数据库事务。预留预算、步骤、审计同事务；完成前再次验证来源、许可、版本、租约令牌和原期限。只允许新预留者执行；读到未知 planned 不能当成功或免费重跑。已存第10次有效决策仍可执行其 finish，不先误判次数耗尽。取消或新租约接管后迟到结果不能写入。

`run_regression` 必须保留完整计划/失败/未执行分母；`save_candidate_rule` 必须引用本任务实际完成、同草案/上下文/版本/套件的报告。固定执行器缺独立 corpus 时报告不完整，不能仅凭模型说“通过”保存合格候选。应用当前不自动发现/接入独立 corpus；这是待验证接线，见状态页。

## worker 与关闭

`AgentWorker.start()`、`run_once()`、`stop_admission()`、`close(wait_seconds=2)` 是服务器接口，不向 HTTP 或模型开放。SQLite 是任务队列唯一来源；一个协调线程驱动一个任务，另一个线程只做心跳，不并发跑第二个模型任务。网关已占用或有在线等待者时先延后领取；领取后的准入仍由网关原子裁决，快照不能代替它。

关闭先停止新任务和发取消信号，再由 Runtime 关闭其自有网关、等待 worker。worker 合计 join 最多2秒；网关也有独立有界等待。`WorkerShutdown` 返回 `admissionClosed/coordinatorAlive/heartbeatAlive/activeRunId/cleanupConfirmed/lastError`。取消、响应超时或线程 join 超时都不证明远端推理停止；清理未知时保留模型名额，不假报释放成功。

审查修复补上了几个不同边界：兼容 HTTP 适配器把修复提示词的 typed system/human 消息转换为标准 role/content JSON，原主持人字典和注入模型行为不改。模型意图预留后，网关 `before_attempt` 再验证当前来源、租约、原期限、取消信号和同一 planned 记录；拒绝不退预算，也不增加第二次预留。

普通事务获得 SQLite 写锁后及提交前都重新检查关闭状态，提交与 Runtime 关闭共用短锁，不在数据库等待或计算期间持锁。修复循环绑定服务器自有 run/token/Event 执行作用域，心跳失败即时撤销这次执行的普通写权限；工具、候选和 finish 都受同一提交屏障约束。最小管理员读取不重新获得执行权限，终止通道仍独立。

领取前已永久失效的 queued 材料由服务器专用 CAS 转为 `needs_human/source_changed`，没有租约、开始时间或额外尝试；不能用它终止当前有效排队任务，也不能覆盖已取消/被领取的任务。短暂存储或审计失败保留原队列以便后续重试。该通道不向 HTTP 或模型开放，内部无 ownerDigest 的 source_changed 终止记录只用于这类未开始任务。

实现入口：`backend/app/agents/{repair_agent,agent_prompt,store,worker,decision_contracts}.py`、`backend/app/routers/agent_runs.py`、`backend/app/runtime.py`、`backend/app/main.py`。
