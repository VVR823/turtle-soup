# 请求审计（TS-09，本地实现）

一次 HTTP 请求不等于一次收费提问。同一 requestId 重发，会留下不同 eventId 的尝试记录，但只对应一个 turn 和一次业务提交。重放记录的 charged 是原 turn 的收费决定，replayed=true 说明本次并未重新收费。错误、缓存命中、拒绝和断线也属于尝试。

## 两种记录，两个失败结果

必要业务事件 session_created / turn_committed / turn_expired / evaluation_created，与原会话、消息、计数、结果或评估在同一个短 SQLite 事务里保存。保存失败则整体回滚，公开返回 503/audit_unavailable；失败不会扣次。finish 回滚时原预留仍在，可按原 UUID 查询，租约到期后恢复，不谎称结果已提交。重放不会新增相同业务事件。

独立 http_attempt 在请求结束后保存。此时业务可能已提交，日志失败不能撤销答案、重新跑模型或重复扣次。请求收集器封存后，晚到的模型线程不能改写记录，也不能污染另一请求。ASGI receive 仍只有原读取者；审计不解析问题、响应正文或请求头。

范围是已启动、已通过 002 核验的应用请求。未启动/关闭的 app_not_started 响应没有可用持久化 Store，不保证跨进程留档；002 以前的尝试不会被倒推补造。status 是读取时的快照，不是仍在进行中的所有 HTTP 请求已经保存的保证。

## 安全字段与未知值

事件是 frozen/extra-forbid 的 AuditEvent，details_json 保存完整规范化安全事件，表的关联列、类型和时间必须与其一致。只读注册路由模板，不记录原 URL/query/IP/headers/口令/问题/回复/汤底/提示词/异常原文/模型 reasoning。必要事实 ID 仅来自已校验 HostResult，最多 128 个，每个最多 200 字符；整事件最多 16KiB，截断有原数量与标记。

只有实际调用才记录 modelCalls，最多现有两次尝试；缓存/重放不创造调用。供应商/模型身份来自受控配置，不取响应任意 metadata。未知或无效 token 分项是 null，不能当 0；明确提供的 0 才是 0。某个分项在任一调用未知，汇总该分项仍是 null，不推算总量。

turn 的版本来自其实际 HostResult；仅恢复/创建/评估 session 时知道固定题库、规则，但不臆测旧引擎，engineVersion/normalizationVersion 显示 unversioned。trafficClass 是测试/真实/合成/旧记录标签，不是去重用户数或模型质量。

审计关联无法表达合法旧存档的长ID时省略该ID并标metadataTruncated，不缩短成另一身份、不让可选日志阻止恢复；已发现的截断标记不会被后续正常metadata清除。

## 降级与恢复边界

SQLite 审计连接在 WAL/SQL 前使用 250ms timeout。所有尝试持久化/文件 IO 放在线程，不让事件循环同步等待。应用最多准入 8 个实际未退出 IO 任务，进入 executor 前计数；500ms 等待超时返回 pending，不释放未退出任务的名额。关闭停止准入，最多等待 2 秒并报告 residualJobs，不能强制取消原生文件 IO。

同一实际worker始终负责终态失败：即使HTTP/关闭等待已返回，仍保留有界未持久化事件、缺口和可用安全标记；不会让asyncio输出原异常。已确认SQL提交不因close异常重新收费或重写业务；连接清理异常不应挡住备用保存。

数据库故障使用 DATA_DIR/audit-fallback.jsonl，只写上述安全事件，总量最多 1000 条/1MiB，单条最多 16KiB。文件不能写/容量忙时使用同样有界的内存缓冲，明确未持久化；超过缓冲则 dropped 增加。stderr 仅固定分类与关联哈希，不打印事件 ID、玩家文本或原异常。部分尾行、坏行、冲突、超限文件保持原文，不截断覆盖以腾空间。

启动恢复或管理员恢复执行一次有界处理，数据库故障时停止本轮，避免逐条等待 1000 次。eventId 与完整 payload 同时核对；完全相同去重，冲突不覆盖。数据库提交后才清理文件；清理失败可再恢复且不会新增重复行。永久缺口保存在有界 audit-gap.json 和可用数据库的 runtime_meta.audit_gap，恢复不清除历史缺口。complete=false 可由永久缺口、未知覆盖起点、待恢复文件、内存或活动 IO 引起。

两种缺口标记共用严格校验（≤1024字节、确切字段、拒绝重复键、bool和非负signed64计数）；损坏/歧义或已知非零丢失量不能报告完整。超限旧文件保持原样，但独立合法RAM仍可恢复到健康数据库，remaining保留文件哨兵+RAM。当前恢复报告recovered/duplicates只计文件，RAM成功恢复会低估该数字（Minor，TS17待修），不等于行丢失。

单实例锁保护本进程，不是多进程共享文件锁、远端可靠队列、断电耐久性或性能 P95 证明。数据库与磁盘/进程同时失效时，内存和未保存缺口可能丢失；不能宣传每次请求永远可追溯。旧私密诊断 Trace 默认关闭，开启后仍含问题/回复，.gitignore 不是安全隔离；其开关不关闭必要审计，其失败只报安全哈希和 metadataTruncated。

## 管理员接口

独立 X-Admin-Token，缺配置 503，缺失/错误/只有站点口令 401。三个接口不在普通游戏响应中添加审计详情。

- GET /api/audit/admin：默认 50、最多 100 条；start/end 为有限非负 UTC Unix 秒，默认最近 7 天，最大 31 天；eventType 仅五种注册类型。时间范围和 SQL 参数化，LIMIT=limit+1。
- cursor 是严格有界（512 字符）无 padding base64URL，包含 createdAt/eventId/start/end/eventType 的规范化 JSON。后续省略条件继承首屏实际窗口/过滤条件，显式改动拒绝422，需开始新查询；时钟推进不会移动原分页窗口。按 created_at DESC,id DESC 稳定分页，同时间记录不重漏。它不是签名或授权凭证，访问仍必须管理员口令。不含窗口的旧裸cursor不放行；本阶段尚未生产发布此接口。
- GET /api/audit/admin/status：覆盖起点、完整性、永久缺口、丢失量、文件/内存积压与实际 IO 数量，无文件路径/原始文本。
- POST /api/audit/admin/recover：不接收 body/query/任意路径；成功返回恢复报告，仍有实际 IO 返回 202/pending，不冒称已完成。恢复 5次/分钟，读取 30次/分钟，沿用应用限流开关。

合成 5000 行的 EXPLAIN 使用 idx_audit_events_time，查询只取 limit+1。时间/类型索引不能证明生产延迟，等时间记录可能需要临时排序；TS-16 根据实际查询继续评估，不在本阶段新增所有索引。

## 验证与真实证据

本阶段状态与报告见 [TS09 状态](ts09-status.md)。所有回归使用自有临时目录、FakeModel/合成数据；不代表真实模型准确率、真实用户增长、实际免费账户资格或生产部署。迁移见 [迁移指南](migrations.md)，测试见 [testing](testing.md)。
