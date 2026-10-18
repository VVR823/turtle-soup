# TS17 Local Snapshot Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. No per-task implementer/reviewer; one TS17 whole-stage review after all local delivery units, not after this subplan. Steps use checkbox syntax. User has already authorized autonomous execution; no phase confirmation or Git writes.

**Goal:** 在独立合成目录备份并恢复最新SQLite及明确识别的辅助记录，不升级schema、不覆盖源/现有目录，不把“工具可复制”说成生产停写或完整A58通过。

**Architecture:** 复用 migrate_data._safe_path/_validate_paths/_backup 的输入保护和scratch SQLite backup；新模块负责备份清单、完整性/外键/schema核验与新目录恢复。输入SQLite从不直接打开，即使mode=ro；恢复前只在自有scratch核验。业务停写、资源报告和新增记录演练由后续独立子计划消费本接口。

**Tech Stack:** Python stdlib sqlite3/pathlib/hashlib/json/shutil/tempfile，现有migrations与baselines.strict_json；原生pytest/离线uv，不加依赖。

**Spec:** docs/superpowers/specs/2026-10-12-ts17-local-release-design.md；原TS17、A58–A59、C24。此子计划只覆盖一致快照原语，不取代TS17发布包/最新业务数据演练/Minor/D25/整阶段验收。

## Global Constraints

- 仅显式绝对独立合成路径，真实backend/data、根data及其祖先/子路径拒绝；源、目标、报告不重叠，现有目标或报告绝不覆盖。
- productionReady=false；quiescenceVerified=false：该工具不负责证明外部写入者已停。真实定时任务/生产/公开均HOLD。
- 不执行迁移；schema1/2/3/4逐一核验，未知/漂移/缺外键/损坏拒绝签收。默认迁移1、应用2、Agentfalse及预算不变。
- 备份包括主库与WAL提交结果；源DB/WAL/SHM及辅助文件哈希前后必须完全一致。主库/WAL只在scratch打开，源SHM不触碰。
- 明确认识的辅助文件：sessions.json/generated_soups.json/verified_qa_pairs.jsonl/audit-fallback.jsonl/audit-gap.json；traces目录只允许平坦普通.jsonl/.jsonl.bak文件。其他输入、目录、链接/重定向拒绝；不是默认忽略未知数据。
- 源总文件大小上限64MiB、文件数上限2000，为本地演练边界，超过保留维护/证据，不声称生产容量。SQLite backup沿用15s截止；核验SQL用15s progress-handler截止。
- 输出只写新自有目录；失败保留已产生证据。报告不含玩家内容/ID/凭据，只固定代码/版本/摘要/数量；哈希是完整性校验，不是来源认证或密钥扫描。
- 原TS16冻结清单成为历史；不得覆盖其证据、反复跑已验收阶段。全项目门禁在整个任务完成前仍必跑，不以单文件绿称阶段完成。

## Review Focus

1. WAL尚未checkpoint：恢复必须含最新已提交记录；Task1原生真实WAL断言。
2. 辅助文件/trace链接或manifest路径逃逸：不得读出目录或写到现有内容；Task1拒绝分支。
3. 源在复制期间改变：不能签收半旧半新快照；Task1在真实copy seam注入文件变化。
4. SQLite schema checksum漂移、未来版本、完整性/外键失败：不升级/修复后悄悄接受；Task1变异原生数据库。
5. 备份DB或清单被篡改/增加文件/缺文件：恢复前拒绝，不产生可用目标；Task1真实字节变异。

## Files and Interfaces

- Create backend/app/scripts/snapshot_recovery.py：独立LOCAL CLI及函数。
- Create backend/tests/test_release_recovery.py：本子计划的合成文件/数据库契约；后续最新业务恢复用例追加此文件或独立integration文件。
- Create docs/superpowers/plans/2026-10-12-ts17-progress.md：唯一TS17 ledger与剩余范围映射。

`snapshot_recovery.backup(source: str, target: str, report: str) -> dict`

`snapshot_recovery.restore(source: str, target: str, report: str) -> dict`

成功写一次新report并返回同一元信息：status='passed', operation='backup'|'restore', migrationVersion:int, sourceUnchanged=true, productionReady=false, quiescenceVerified=false, fileCount:int, databaseSha256:str。失败抛`RecoveryError`，CLI统一退出1/fixed code，不输出异常路径/内容。CLI `main(argv: list[str] | None = None) -> int`，必选`backup|restore --source --target --report`；无隐式路径/生产开关。

备份目标含sessions.db、允许的辅助文件/trace与recovery-manifest.json。Manifest严格schemaVersion=1、migrationVersion1–4、files为相对POSIX路径→小写SHA256、productionReady=false；不含原输入SHM/WAL，因为SQLite backup已整合WAL。恢复验证精确文件集合/所有摘要/schema/完整性；在新目标复制已验证快照与辅助文件，不复制manifest作为运行数据。

## Task 1: Immutable isolated backup and restore primitive

- [ ] Step1 写原生失败测试：`test_recovery_api_is_available`用动态import+callable断言（缺功能是明确FAIL，不让collection import error伪装RED）。随后分别断言schema1–4、真实WAL最新question_limit=33、原消息41/42内容保持、辅助文件/trace字节不变、源全部摘要不变、report不含Question?/Truth/秘密canary，productionReady/quiescence均false。
- [ ] Step2 `node scripts/test-backend.mjs backend/tests/test_release_recovery.py -q --junitxml=.cache/ts17/recovery-red.xml`，Expected缺snapshot_recovery明确FAIL；完整输出保存recovery-red.log。
- [ ] Step3 实现上述三个精确函数及RecoveryError；复用backup原语而非migrate_data.main。验证输出SQLite PRAGMA integrity_check='ok'/foreign_key_check空/migrations.verify_schema(required_version=实际版本)，不给自己生成“自动兼容旧代码”结论。
- [ ] Step4 原生负向测试逐类RED→GREEN：目标/报告碰撞、protected/relative paths、无DB/未知输入、链接、源变化、未知schema/checksum、backup摘要/文件集合/manifest重复键与路径逃逸。源变化mock只包裹真实shutil.copy2后写synthetic文件，断言真实拒绝副作用，不断言mock调用。
- [ ] Step5 `node scripts/test-backend.mjs backend/tests/test_release_recovery.py backend/tests/test_migration_cli.py backend/tests/test_migrations.py backend/tests/test_metrics_migrations.py -q --junitxml=.cache/ts17/recovery-green.xml`；Expected全部通过，保持原迁移测试不改。现有全套门禁待子计划全部完成再实际运行，未运行前只标selected green，不标Task complete。
- [ ] Step6 记录每条RED→GREEN/源码身份/实际命令和计数，保留工作树与证据，不提交、不清理未知输出。当前项目完整隔离门禁通过后才签收本Task。

## Dependencies / Pre-flight rulings

Ruling: 先恢复原语再发布包 — 无共享产品状态、原语可独立验证，后续业务演练需要其签名 — 若顺序判断不当只影响本地排期，不降低上线验收。

Ruling: 停写声明不做成boolean“已验证” — 快照工具不能证明外部cron或所有资源已停止，明确quiescenceVerified=false；后续必须看Runtime实际shutdown报告和全writer inventory — 若忽略则不能达到A58，故本子计划绝不签收生产门禁。

Ruling: 未知辅助文件fail closed — 不能默认丢弃潜在新数据；识别范围扩充须先用真实synthetic夹具测试 — 代价是演练可能暂时拒绝，优于静默不完整备份。

## Self-review

已对应设计“一致性备份/恢复”所有LOCAL原语边界；完整业务写入停写/幂等、发布包、Minor、D25归后续TS17单元，原D18仍独立欠项；生产TLS/SSH/cron/镜像与上线授权明确HOLD。函数名/manifest/reports在生产与消费步骤一致，无新的Agent或公网接口。唯一整阶段review等全部LOCAL交付，不派子计划review或询问阶段继续。
