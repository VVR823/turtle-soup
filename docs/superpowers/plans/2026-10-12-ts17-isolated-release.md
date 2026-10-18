# TS17 Isolated Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL superpowers:executing-plans inline/TDD; same TS17 ledger and ONE whole-stage reviewer after all LOCAL units. Autonomous authorization already given; no phase confirmation, Git writes, deployment or uploads.

**Goal:** 实际产出可核对、独立于数据和密钥的LOCAL示例backend与Next standalone包，不把既有禁standalone页面构建冒充发布包。

**Architecture:** 固定源码allowlist生成新的只含代码/锁文件backend目录，app.soups.py仅在副本用自建合成示例替换，不读原私人题库。前端沿用sterile复制/净化环境；standalone构建必须先解决tracingRoot与dependency junction输出逃逸，生成SHA清单并启动实际产物作冒烟。原网站目录不变。

**Tech Stack:** 已安装Node22/Next16.2.12、Python已锁环境；Node fs/path/crypto/test，原有SQLite/FastAPI，零安装/供应商调用。

**Spec:** docs/superpowers/specs/2026-10-12-ts17-local-release-design.md，原TS17/A59/C24；latest-data恢复原生证据已完成LOCAL核心，不替代上线授权。

## Global Constraints

- release目标为projectRoot/.cache的直接新子目录；拒绝已有/重叠/redirect、private/data/dotenv/Git/旧部署包/嵌题辅助脚本/评测dataset进产物。
- backend源码仅固定allowlist；不读取/复制app/soups.py及backup题库、_deploy_check.py、test_server.py、整个backend/data、.venv、eval/tests/datasets/私有corpus。只生成副本合成seed，真实玩家题库与数据不动。
- app.testing.py是实际Agent安全检测依赖，不删以假装无Fake；其存在不等于真实模型质量。eval仅白名单纯代码（明确来源校验依赖），不夹带案例/真实标签。
- 清单version1/localOnly=true/productionReady=false/dataKind=synthetic_demo，文件相对POSIX路径→SHA256；哈希不是来源许可、全面密钥扫描、Windows→Linux兼容或生产Ready证明。
- 源/生成产物之间不可有指向原node_modules的运行junction；构建输入显式已安装deps可以read-only链接，但Next自动拷贝不得逃出owned输出。产物缺静态资源/入口/manifest/依赖或混入额外文件则拒绝签收。
- Docker CLI目前不可用，Docker真正构建单独HOLD；不能因此不做可运行本地package。真实TLS/SSH/hostkey/cron/生产数据迁移、上线与公开仍HOLD。
- 原239运行文件/HEAD-index不变；唯一门禁LIVE时冻结代码，旧证据不覆盖；此子计划selected绿不等于整个TS17当前full/Edge/review已过。

## Review Focus

1. 文件名.py但内含私人题库/备份：Task1实际canary排除测试、合成替身，不从原seed推导公开样例。
2. allowlist源文件或目录junction：Task1实际junction拒绝，不读逃逸目标；未知output拒绝。
3. 清单自相矛盾、缺文件、多文件、被改字节：Task1全文件集合/hash严格验证后拒绝。
4. Next tracedFile相对tracingRoot含..：Task2不得写越界，确认实际installed copyTracedFiles算法与owned trace根，不能试写原workspace再修。
5. Next包只有server.js但没有public/static：Task2真实产物动态路由/静态资源冒烟，不能用source next start替代。

## Task 1: LOCAL backend demo code artifact and integrity contract

**Files:** create scripts/backend-release-policy.mjs, scripts/tests/backend-release-policy.test.mjs; future smoke wrapper scripts/test-backend-release.mjs plus scripts/tests/probe-backend-release.py.

**Interfaces:** export `buildBackendRelease(projectRoot:string, target:string) -> manifestObject` and `verifyBackendRelease(target:string) -> manifestObject` (synchronous); export fixed `backendReleaseFiles` array for exact-policy fixtures, not arbitrary copy patterns. `build` never copies wholebackend, does not execute code/install/deploy; verify rejects exact fileset/hash/metadata mismatch and redirects.

- [ ] Step1 native Node测试动态import missing模块FAIL；合成源夹具所有allowlist文件、private seed/.env/data/backup等canary，实际artifact只能有whitelisted source+generated seed+manifest，源seed字节未变/不被复制；已有输出不覆盖、target外部/ancestor拒绝、实际源junction拒绝。
- [ ] Step2 `node --test scripts/tests/backend-release-policy.test.mjs` save .cache/ts17/backend-release-red.log；Expected missing module/assertion FAIL，不是无测试文件。
- [ ] Step3 固定实际runtime所需app顶层代码、agents14/routers6、eval source registry依赖的8个模块与backend/pyproject.toml/uv.lock/requirements.txt。保留源相对目录；固定生成seed为Soup(id='demo-synthetic',title='合成本地示例',surface='这只是部署演示',bottom='这是自行编写的合成示例，不代表真实题库',source='synthetic_demo')；不能删db.SEED_SOUPS依赖。目标mkdir只在所有输入path与来源稳定核验后；复制后digest验证。metadata拒绝private内容，不宣传public授权。
- [ ] Step4 native负向原生文件变异：已生成manifest metadata schemaVersion真布尔、path escape/hash damage/missing/extra file、link -> verify拒绝；将targetfile真实损坏，不仅assert源码文字。
- [ ] Step5 同时运行此native文件与既有frontend-build-policy/fixture-process回归，Expected0fail；将新test纳入package test:harness，先test实际npm command覆盖新test，不通过grep source宣称已纳入。
- [ ] Step6 isolated实际backend artifact：用正常权限wrapper已安装offline Python -I，从artifact/backend首路径import app/eval，验证模块__file__都在artifact，禁止缺文件回退原app；显式Settings.for_test/FakeModel/网络禁止/自有新data，实际健康/公开seed/新会话/问答与关闭。这不是fresh pip install/Linux生产验证；未执行前只签policy native。

## Follow-up design (NOT an executable Task 2 brief yet): Actual Next standalone

**Files:** create scripts/test-standalone-release.mjs and scripts/standalone-release-policy.mjs with scripts/tests/standalone-release-policy.test.mjs；复用既有frontendEnvironment/createSterileFrontend，不修改原next.config或原deps。

- [ ] Step1 在installed Next output.md与copyTracedFiles源码基础上选安全trace根方案：优先owned依赖materialization（查大小/链接/空间/不下载），或tracingRoot可证明包含全部输入的只读已装deps+sterile monorepo根。若所有tracedFile输出无法在构建前证明无..逃逸，就单独HOLD该部分先做其他，不运行有越界风险的build。
- [ ] Step2 前置native反例覆盖tracedPath逃逸、dotenv/data/private/nested source links、缺static/public/server入口、多文件/清单不符；实际safe packaging复制验证。接口/精确启动协议根据现有owned fixture wrapper核对后补充Task2 brief，不凭此计划臆造端口/字段。
- [ ] Step3 ONLY owned freshbuild output:'standalone'，配置静态资源与相对server入口，产物不依赖source junction或当前cwd；源码/数据/依赖hash保护，原root不写构建文件。
- [ ] Step4 actualstandalone进程在自有loopback端口（先确认无占用，不能复用foreignserver）从实际artifact启动；GET静态HTML/资产、动态/game/[id]与/difficulty/[id]页面、无uncaught错误；server正常关闭。独立后台API必须复用固定owned协议，不能联系生产URL。
- [ ] Step5 当前phasewhole offline/type/lint/build/Edge及唯一review仍在全部LOCAL units完成后；本包smoke不是A59真实上线门禁。

## Preflight / self-review

db.py实际import app.soups.SEED_SOUPS，必须生成副本替身；FixedRegression实际_SOURCES包含eval8个纯模块，不能把整个eval私有数据目录复制。当前test-frontend-build明确output undefined；不算standalone证明。Next copyTracedFiles用path.relative(tracingRoot,tracedFilePath)决定输出，若tracingRoot过窄会..越界，必须先解决再build。两个独立单元用同ledger，不派分项review、不等待阶段授权。最终runbook/Minor/D25及D18仍原scope欠项，不被本计划吞掉。

## Task 1 smoke brief (exact interfaces, before implementation)

- `scripts/test-backend-release.mjs` exports async `probeBackendRelease(target, data)`; both absolute paths, artifact already verified and data a NEW direct sibling child in the same project-owned `.cache`. It returns the parsed JSON success receipt only after actual native child EXIT0, complete module-origin assertions and post-probe manifest revalidation. No original data/seed read, install or default dotenv.
- Installed interpreter is explicit repo `backend/.venv-ts01/Scripts/python.exe` (POSIX bin/python); child `-I -B scripts/tests/probe-backend-release.py <artifact/backend> <newdata>`, cwd artifact root, sterile frontendEnvironment OS variables plus LANGSMITH_TRACING=false/LANGCHAIN_TRACING_V2=false. No inherited provider/config secrets, PYTHONPATH or NODE_OPTIONS.
- Python helper uses standard socket outbound connect/resolve guards before app imports, adds ONLY artifact/backend to sys.path, explicit Settings.for_test and FakeModel; actual TestClient health, public synthetic seed, new chat and same-key replay, fixed regression suite source registry and all loaded app/eval module origins within artifact. TestClient lifespan closes actual gateway/audit/client; verify receipt plus current snapshots, no response payload/session ID logging.
- Wrapper async child owns hidden subprocess and uses existing stopFixture for bounded cleanup; timeout/failure is never green. No listen port/server/browser/production URL. CLI no-args builds a new backend-demo cache artifact and owns new sibling data, emits bounded LOCAL/non-production receipt. This is installed-dependency Windows smoke, not fresh pip install/wheel/Linux/real-provider proof.
- New native `scripts/tests/backend-release-smoke.test.mjs`: missing-wrapper test must first genuinely FAIL; then actual new artifact + fresh child JSON health/synthetic/module-origin/replay/cleanup proof; existing/non-sibling data and damaged artifact reject without touching their sentinels. Add tests to test:harness only after selected native GREEN. Whole TS17 suite still pending.

Ruling: former Task2 had unresolved tracing/entry interfaces — reclassify as follow-up design, not falsely executable plan; lock separate brief after safe dependency/tracing facts. Task1 exact native artifact/smoke remains independent and authorized.

Ruling: actual native startup rejected the planned Soup-instance SEED_SOUPS — existing db.load_catalog uses Soup(**s), hence generated-only seed must be Soup(...).model_dump(mode="json") mapping. Original db/catalog untouched; no explicit soups override to hide the defect. Native smoke observed the TypeError first; keep failing evidence and rerun real artifact startup.

Ruling: Windows asyncio stdlib socketpair is its local self-pipe, not provider I/O — guard permits only thread-local synchronous construction by captured stdlib socketpair; all arbitrary connect/connect_ex/resolve/create_connection remain blocked. Failed harness traceback retained, not mislabeled product regression.
