# 数据迁移与旧局兼容（TS-02 / TS-09）

本地已实现不可变001、显式002（反馈/审计）、显式003（Agent）、显式004（仅五个统计时间索引）和显式005（发布后观测账本/覆盖起点/不可变约束）。应用新空库启动仍只要求002，CLI默认001不变，不自动升级003/004/005；Agent默认关闭。见[TS14](ts14-status.md)/[TS15](ts15-status.md)、[统计指南](metrics-howto.md)与[D18 ledger](superpowers/plans/2026-10-13-d18-progress.md)。没有对实际玩家库、服务器或定时任务执行迁移/停用。

## 数据行为

- 新空数据目录：显式应用启动执行 001+002。已有数据库：在自建临时 DB+WAL 副本上只读验证 required_version=2，再开启运行连接；不自动改旧 schema，也不直接用 mode=ro 打开源目录（它仍可能改写 SHM）。复制中源 size/mtime/inode 改变则拒绝；冷启动复制成本未做大库性能证明。旧库/只有001报 MigrationRequired，必须先离线演练。
- 001 的 DDL、JSON 导入、旧消息回填、原字段核对、完整性检查和版本账本在同一事务内执行。失败回滚本步；没有自动 down migration、删列或用旧备份覆盖新数据。
- 正常旧局绑定当前完整基线；可可靠配对的 user/host 消息关联一个 completed turn。原消息 ID、内容、时间、计数不变。legacy-unversioned 和 answerVerified=false 表示旧模型/引擎不可追溯，不是新质量评测。
- 无法配对、提醒标记/计数不一致、缺题、终态矛盾等局保留原记录并标记 incompatible；恢复、提问和揭晓返回 410/legacy_session_incompatible，不自动新建或清空。
- 新局保存 puzzleVersion/ruleVersion 与服务端 traffic_class。测试为 test，普通新局为 real，历史为 legacy；这不是去重用户数。
- puzzle_versions 与 rule_releases 保存完整内容和内容摘要，应用恢复检查 manifest；数据库触发器拒绝 UPDATE/DELETE。内容摘要不是数字签名，也不能阻止有权限的人改数据库/删除触发器。

## 隔离演练入口

在 backend 工作目录运行 `python -m app.scripts.migrate_data --help`。本机锁定环境也可使用 backend/.venv-ts01/Scripts/python.exe。**不运行旧部署脚本，不把源路径指向 backend/data、根 data 或它们的祖先目录。**

输入是已经人工确认、停止写入并放在独立位置的旧数据副本，不是在线数据库。复制 SQLite 不能只复制 .db 而忽略 WAL；该入口先复制 .db/WAL 到自建临时目录，再从临时副本执行 SQLite backup，并用 before/after 摘要检测原输入变化。SQLite 只读连接也可能生成 SHM，故不直接打开输入目录中的数据库；WAL/已存在 SHM 均纳入保留校验。临时目录只包含本次生成副本，结束后自动清理，不删除原输入。实际生产备份/恢复演练仍属于 TS-17。

```powershell
# 三个路径都要替换成明确的隔离绝对路径；输出目录/报告必须尚不存在。
python -m app.scripts.migrate_data --dry-run `
  --source 'D:\isolated\old-copy' `
  --target 'D:\isolated\new-output' `
  --report 'D:\isolated\dry-run-report.json'
```

dry-run 在内存中完成真正迁移，写报告但不创建 target。正式本地演练去掉 --dry-run，并使用新的 target/report 路径。target 只含迁移演练数据库，**不是完整生产数据目录，也不是可直接部署的发布包**。反馈/Trace 与旧源文件没有被删除或自动迁走。

CLI `--target-version 1|2|3|4|5` 默认仍是1，不带参数仍演练001。当前应用启动要求002须显式 `--target-version 2`；003 Agent、004原统计、005发布后观测须另行显式选择，不在GET或启动中升级。输入为独立旧/已迁移副本，输出仍必须新目录。002在独立短事务增加feedback_items/audit_events、索引和audit_coverage_start/migration_002_report。002失败只回滚002，001仍可验证；后续同样保留已完成阶段、拒绝结构漂移。重跑保留原报告与历史行，不把旧HTTP/JSONL编成新审计；004只加五个时间索引、noHistoricalBackfill=true。005也不补造历史观察，旧001–004已登记SQL/checksum不改，未知/断档/未来版本拒绝。

退出码：0 = 本次隔离演练通过；2 = 存在需要人审的异常/重复记录；1 = 路径拒绝或失败。任何结果均 productionReady=false。不要把生成数据库或报告提交 Git；放在私有隔离目录或仓库忽略的 .cache 中。

## 报告与异常处理

JSON sessions.json 是严格输入：缺少必要计数/创建时间、错误类型或未知字段不能通过当前契约。坏记录、重复 session/message ID 的来源文件、记录序号与 hash 入报告，不显示原问答或会话持有凭据。完整原文件留在 source；报告不是原始记录的替代品，也不应擅自公开。

SQLite 结构未知、缺必要主键/消息外键、存在孤立消息、checksum 不符、未来版本、快照损坏或完整性失败，拒绝迁移/启动；不把损坏冒充空库。恢复同时验证局绑定的题库和规则版本及其 manifest 关系。异常 JSON 会导致演练失败，不重命名源文件为 .bak。JSON 整数限制在 SQLite 64 位范围，生成消息 ID 前预留整份有效输入的显式 ID。重跑 migrate 对已应用的版本不重复加列或导入；001 尚未发布，本次审查修正后 backfill contract/checksum 更新为 legacy-v2，不自动升级旧的演练输出。

## 旧写入者

仓库内已停用 `app.scripts.merge_verified_qa` 的 main/run_merge/cleanup_old_sessions；默认定时触发退出 2，不读改 JSONL、不删除历史、不执行 systemctl。管理员旧 HTTP merge-verified 入口认证后返回 410/legacy_writer_disabled。

本地反馈HTTP/后台已转002数据库与审核版本CAS，不再写旧JSONL；审核不等于规则真值或模型权限。TS10内部版本发布/暂停事务已实现，仓储人审接线仍待TS15，未公开发布API。Runtime禁用旧verified自动注入；显式隔离迁移仍保留来源语义。缺数据库却有旧feedback/verified文件时拒绝自动新建，不丢历史。真实服务器可能仍运行旧代码或另有cron/timer，因此不能凭本地shim声称线上已全部停写。上线前要盘点Web/API、Agent、cron、systemd timer、手工维护/注入脚本和直接数据库访问者。

## 验证与停止条件

TS11纯离线数据合同不新增数据库迁移，不改变注册001/002、默认目标版本或旧报告。私有评测显式输入/新输出与真实迁移完全分开；种子catalog不是生产active版本，人审及旧副本审计未完成。见[评测数据](evaluation-data.md)。

pytest 临时夹具验证新空库、旧 SQLite、JSON 导入、WAL 备份、重跑、各 DDL/回填失败、快照损坏和真实本地 API 旧局恢复。它们不是生产备份演练、跨平台实跑或已部署证据。验证命令见 [testing.md](testing.md)，阶段证据见 [ts02-status.md](ts02-status.md)。

出现不一致、报告 needs_review、缺版本或未知旧格式时，保留 source、拒绝上线、核对记录来源和恢复策略；不要默认重置玩家数据。新版数据库投入使用后发生问题，要保留最新库、暂停写入并前滚修复/使用已验证兼容版本，不能拿旧备份覆盖新增数据。
