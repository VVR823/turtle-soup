# TS09 HTTP 尝试与事务审计设计

## 目标、授权与阶段

这是架构型子阶段，依据原 TS09/A34–36/C16/D11/D14/D24。用户明确要求全18阶段持续本地实施、自主审查/调整，不重复要求其逐阶段批准；采用主执行者 native 实施、阶段一个全新独立审查员与一次重要问题修复门禁。设计与计划审批按此授权自主完成，仍保留完整书面设计、自审及可恢复账本。

玩家与维护者需要知道：一次提问是否已提交、重试是否重复执行、某个回答用了哪个版本/来源、服务失败是否造成统计缺口。HTTP 请求次数不是已收费轮数；重放也算一次 HTTP 尝试，但同一个 turn 仍只扣一次。测试不能冒充模型质量、历史完整统计或真实用户增长。

TS08 唯一独立审查仍在运行，本阶段当前只允许读源码与写本设计/计划/ledger，不修改其冻结源码或 TS09实现。通过 TS08终态/单次修复门禁后才能开始测试/实现。

## 当前入口事实

现有 trace_logger.record 实际遵守 ENABLE_TRACE，记录成功 owner 路径的私有 question/reply JSONL，文件失败静默；不存在全HTTP覆盖。game_service.ask 重放、BodyLimit/StrictJSON/auth/rate/查询失败不全经过该入口。RuntimeMiddleware 包装 CORS、BodyLimit、run_request，FastAPI同步线程使用复制的 ContextVar；ModelGateway 的 worker 也复制上下文，可能迟到。

game_store.create_game_once/reserve_turn/finish_turn/evaluate_once 已有短 BEGIN IMMEDIATE 事务；模型调用在事务外。HostResult 自带 evidenceIds/cacheHit/versions，不能通过新审计字段重新定义扣费或评分。CompatibleAdapter目前仅返回content，InjectedAdapter可返回AIMessage；未知用量不可当0。

001的SQL/CHECKSUM_001/backfill/原报告不可修改。migrate默认001、核心测试明确“只001表”必须继续成立。现有DB启动 read-only 验证后才WAL/写操作，不能为了002改成启动自动升级旧库。

## 方案比较

推荐：002新增原计划两张表和两索引；请求外层收集受控元信息、每HTTP唯一审计event；必要业务事件在原事务内写入；尝试日志另存失败使用有界私有fallback与不完整状态。优点是业务不依赖外部诊断文件、同turn多attempt不混数；代价是多一次短审计写入和明确的故障恢复状态。

只扩JSONL trace：不能与扣费原子提交，难保证去重/分页和全请求覆盖，不采用。引入消息队列/外部日志平台：增加进程/维护/成本，当前不需要，不采用。不做新前端日志仪表盘，TS16统计与TS15后台继续依赖这一数据基础。

## 002迁移与兼容

Task1自审修订：SQLite mode=ro也会在WAL原目录创建/改SHM。启动检查改在唯一临时DB+WAL副本上执行，复制期间源size/mtime/inode变化则拒绝；不复制原SHM，不自动upgrade原库。代价为冷启动一次完整DB/WAL复制，不能声称实时备份、原子多worker快照或已实测大库性能。3项源侧车hash反例及复制竞态测试覆盖此边界。

在 migrations.py 追加002注册SQL/CHECKSUM_002，包含原计划 feedback_items/audit_events 和 idx_feedback_status(status,created_at)、idx_audit_events_time(created_at,event_type)，不引用未来003表。新增审计覆盖起点元信息存在已有 runtime_meta，时间统一UTC Unix秒。

`migrate(conn,soups,*,legacy_records=None,target_version=1)` 保留001默认和完整旧报告，显式target2才执行独立002 BEGIN IMMEDIATE。若002失败，回滚该步，已完成001保留可验证状态；重复002不改已有数据/报告/基线。`verify_schema(conn,*,required_version=1)` 识别已注册1/2连续账本、checksum、相应表/列/索引；required2遇到001报MigrationRequired；未知/缺失/漂移报MigrationError，不写。

新空应用目录初始化显式target2；已有数据库在启动前 read-only required2验证，001不自动升级。隔离 migrate_data CLI增加 --target-version 1|2（默认1保持旧行为），只升级新输出副本，拒绝源/目标重叠、生产路径和已有输出。新能力必须002后启用，原001测试和纯存储调用仍可独立验证；不会把旧请求/JSONL回填成已记录尝试。

## 强类型事件与私有信息最小化

新增 audit_events.py 定义 frozen/extra-forbid/strict 的 `AuditEvent(schemaVersion=1,eventId,eventType,requestId,sessionId,turnId,runId,createdAt,details)`，eventId程序生成UUID。eventType初始 http_attempt/session_created/turn_committed/turn_expired/evaluation_created。业务稳定ID按事务结果获得；无可核验关联时为null，不能猜测另一个玩家/会话。

AttemptDetails含 method（有界合法HTTP方法）、routeTemplate（注册路由模板，未知统一unmatched，不是原path/query）、statusCode（100–599或null）、durationMs（非负有限数）、trafficClass(test/real/synthetic/legacy)、outcome、source、kind、charged、cacheHit、versions、evidenceIds、reasonCode、modelCalls、responseStarted/disconnected 等有界字段。无该数据则null，不用默认false/0冒充观测。source沿用HostSource，kind沿用HostKind，版本沿用HostVersions；reasonCode是程序选定短分类，不保存模型原reasoning。

evidenceIds只来自已校验HostResult，最多128个、各≤200字符；超长时记截断标记和原数量，不声称完整。不得记录原question/reply、汤底/提示词、请求headers/query、IP/口令/密钥、原始模型思维链、异常堆栈或任意metadata字典。内部业务可关联必要事实ID；普通响应/公开错误不添加审计细节，合法evaluate/ended原汤底展示不受影响。

`ModelCallObservation`最多2条/现有在线调用，ordinal、provider/model受控字符串、status/errorCode、安全Usage。input/output/totalTokens分别StrictInt≥0|null；缺失/非法元信息为null并记usage状态，不影响合法答案。若任一尝试用量未知，总汇为null，同时可保留已知分项。模型/供应商不能通过usage决定HostResult、收费、规则来源或权限。

## HTTP尝试上下文

新增 audit_context.py 的请求owned可变收集器（RLock、密封标记），ContextVar提供 `attempt_context()` / `current_attempt()` / 程序owned update方法。外层ASGI wrapper在进入 CORS/BodyLimit/run_request之前为每HTTP生成独立eventId，处理403/401/400/413/422/429/503/404/普通成功/幂等重放/缓存命中/断网。websocket/lifespan不假装HTTP事件。

收集已确认的响应status、路由模板和耗时，endpoint在校验req后绑定request/session，GameStore返回结果时绑定实际turn/版本/来源；拒绝输入不再次宽松解析JSON或读原请求体。ASGI receive继续唯一交给原生命周期控制，不新增竞争读。send包装只读协议状态，不把响应body当HostResult。异常未发送响应则statusCode=null/outcome=error；不能伪造200。最终密封后模型worker迟到不能修改或另写已终结attempt。

attempt结束保存独立短事务，异步路径通过 to_thread 执行SQLite/文件IO，不在事件循环同步等待10秒DB锁。写入失败只影响审计完整性，不改变已提交业务响应、不重执行提问。保存耗时有界于短DB busy_timeout（初始≤250ms）；不启动无界日志工作线程/队列。

自审补充异步准入边界：默认executor本身有无界队列，因此在to_thread之前用本应用RLock计数限制最多8个实际未退出审计IO任务；500ms响应等待超时只返回pending，不释放还在运行的任务名额。容量忙时事件进入最多1000条/1MiB的应用内未持久化缓冲并显式gap/status；后续恢复/关闭尝试有界flush，不假装内存已经落盘。DB审计连接在开启WAL/任何SQL之前设置timeout≤250ms，不能先调用默认10秒db._connect再改PRAGMA。关闭停止准入，最多等待2秒并报告实际残留；不谎称已取消阻塞文件IO。全盘/进程失效时该内存仍可能丢失，属于下述明确限制。

开局/查询/揭晓/重放通过显式program hooks更新本attempt，不直接遍历私有历史猜来源。重放只选对应turn的已保存typed元信息；legacy-unversioned没有可核验来源时null+legacy标记，不能创造模型calls/token。缓存来源使用本次返回HostResult.cacheHit。

## 必要业务事件同事务

在已有create/finish/expire/evaluate事务内调用 `insert_business_event(conn,event)`；只有实际新写入才新增业务event，重放不再新增同一业务事件。eventId由业务身份确定的UUID5或事务中持久化一次，保证失败/重放不重复。创建、消息/计数/状态/typed结果或评估快照与对应必要事件同提交/同回滚，不在里面写文件或联网。

插入失败安全拒绝该业务写入并返回脱敏503。原预留租约/恢复规则保留，不能把“审计失败”包装成已经成功扣次数。已经提交的业务在外部尝试日志失败时照常原结果返回，之后相同requestId重放不会重扣。001纯存储调用不引用未建audit表；应用M2写入口必须required2，不把缺表静默当成M2成功。

## 有界fallback、缺口与恢复

新增 audit_store.py 管理 attempt 保存和私有 `.DATA_DIR/audit-fallback.jsonl`。事件只含上述安全结构。应用自有锁下每fallback总≤1000条/1MiB，单事件≤16KiB；载入/重放也限制相同预算。失败记录脱敏stderr固定分类+eventId的hash，绝不打印原异常/玩家字段/完整路径。容量满/坏行/无法写文件有dropped/gap标记，不能覆盖旧记录腾空间或无限append。

审计状态包括覆盖起点、fallback待恢复条数、历史故障/永久缺口/运行内未持久化计数；可写时持久化有界gap sidecar和runtime_meta。DB恢复后 `recover_fallback()` 按eventId+规范化payload核对去重，冲突不覆盖，坏行隔离并记缺口；成功提交后才减少已恢复文件，不删除未恢复行。回收文件失败可以重复恢复但不会重复DB事件；不得清除已经出现的永久缺口。

启动恢复以及显式管理员recover触发一次有界处理；不每请求读改写全历史、不后台无限重试。若DB和磁盘/进程同时彻底失效，无法保证每个未持久化attempt跨重启保存，明确限制；不把此不可保证情形宣传成完整统计。ENABLE_TRACE=false只关闭旧诊断trace，不能关闭必要业务审计与attempt覆盖。

## 有界管理员读取

新增独立 X-Admin-Token 的 `/api/audit/admin`、`/api/audit/admin/status`、`POST /api/audit/admin/recover`，管理口令缺失503/错误401；普通站点口令不够。列表默认50/最大100，默认近7天/最大31天，严格start/end UTC有限时间，拒绝无限范围。cursor按(createdAt,eventId)稳定倒序、严格有界校验；响应选择安全事件DTO，不带原始exception/fallback路径/文件原文。status显示完整性和覆盖起点，不能隐藏缺口。

SQL参数化，时间范围与游标/索引在合成5000事件上EXPLAIN验证使用时间索引，TS16再根据实际聚合形态补优化；不现在建所有索引或承诺生产P95。公开请求不能读事件明细或恢复操作，管理内容不执行玩家HTML/模型指令。当前前端不新增dashboard。

## 验证与停止条件

原001 checksum/SQL/backfill/原记录字节与read-only启动安全永久测试；002逐语句失败/幂等/checksum/索引/feedback默认false。业务audit插入失败各阶段回滚、外部attempt日志失败后原结果/计数可重放。每HTTP独立eventId与同turn关联，缓存、重放、guard/非法JSON/体积/rate/模型失败/断开也覆盖；并发乱序与模型迟到密封。MockTransport提供合法/缺失/非法usage，nullable输出不改变answer验证。

fallbackDB故障、写失败、容量/字节边界、坏尾行、重复恢复/冲突、收尾失败与管理员缺口显示。私有facts/credential/reasoning输入不进入stderr/普通DTO，合法reveal仍可显示原答案。管理员分页/鉴权/时间范围/游标/EXPLAIN。全隔离离线/hash门禁、TS08永久UI、根lint/typecheck须实际跑；单独报告实际证据，不把跳过/夹具当真实质量。

出现重扣/缺事务审计却提交/普通响应泄漏/未知用量冒称0即阻断阶段。未决外部事项单独ledger保留，先继续不受影响工作；不得生产迁移/部署、读取私密配置/真实玩家、购买/真实模型调用/上传。

## 设计自审

各A34–36/C16已落到迁移、typed上下文、业务事务、fallback/管理员读取四个交付单元。002仅依赖001；新增required2不影响migrate默认001；诊断开关与必要审计分离。唯一receive不变，late模型元数据密封、fallback去重但不是OS级可靠队列。短依据不是原reasoning，用量不存在必须null。无未定义外部选择、无占位/私有数据/付费依赖；进入writing-plans，TS08终态前不实施。
