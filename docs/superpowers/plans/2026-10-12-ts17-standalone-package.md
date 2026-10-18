# TS17 Standalone Package and HTTP Smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL executing-plans/TDD inline; same TS17 ledger/ONE whole-stage review after all LOCAL units. No phase confirmation, install, Git writes, deployment or publication.

**Goal:** 补齐实际standalone的public/static，校验独立包完整性，并真正从包启动服务验证动态路由与实际资产。

**Architecture:** 已构建owned input `.cache/ts07-frontend-MLJK1w`的`.next/standalone`只允许server.js/package.json/.next/node_modules，合并同input的public和.next/static进入NEW直接cache子目录；严格regularfile/无redirect与manifest。固定helper require真正生成server.js，不用next start或原workspace源码；只访问其带随机owned header的loopback响应，EOF驱动Next真实gracefulclose。

**Tech Stack:** installed Node22/Next16.2.12，标准fs/path/crypto/child_process/http/net；零下载/APIprovider成本。

**Spec:** docs/superpowers/specs/2026-10-12-ts17-local-release-design.md；owned standalone build已actualEXIT0，当前67harnessPASS，原239/native5 hash未变。

## Global Constraints

- 产物/data/env/source隔离；不读原backend题库/用户数据，不复制整workspace或已装整deps进发布包，只复制Next实际traced物理运行依赖。
- source只能owned `.cache/ts07-frontend-*`，targetNEW同cache直接子目录，无已有/overlap/junction。source所选三树和目标全regularfile，危险/private/env/db/wal/shm/旧source根拒绝；失败输出保留而不签receipt。
- 精确文件清单schemaVersion1/localOnly=true/productionReady=false/dataKind=code_only/filesPOSIXsha256；server.js、package.json、.next/BUILD_ID、.next/static非空/public非空/node_modules/next/package.json必须存在。额外/缺少/改字节/link/非canonical/重复metadata拒绝，清单不是来源许可或全面secret扫描证明。
- 构建不能重跑96935，input物理deps也不重复制26351；当前Next package与真实trace来自已通过ownedbuild。
- HTTPsmoke仅自己绑定的127.0.0.1临时未占用端口，随机instanceId，所有响应必须X-TS17-Instance一致；不能用foreign进程/生产API。HTML GET /,/game/demo-synthetic?level=tianyi,/difficulty/demo-synthetic,/admin/feedback plus实际_next css/js与public文件；同一资产bodySHA与清单一致。
- 仅HTTP产物冒烟，不宣称浏览器交互/无uncaughtJS已经验收；最终真Edge仍独立保留，不以HTTP绿替代。
- Helper启动generated server.js需其实际require.cache node_modules来源全位于artifact；EOF打印本次关闭marker并process.emit('SIGTERM','SIGTERM')调用Next原生handler。实际Next16.2.12 cleanup在server.close/nextServer.close/flushTraces后EXIT143；此为明确expectedcooperativecode，须EOFmarker/端口再绑定/实际终态共同核验，不接受强杀、未知signal、143无marker。
- 用stopFixture只作 boundedcleanup，forcedcleanup始终FAIL；helper hidden，源/测试在gateLIVE冻结；不中断其他工作，不请用户手动接续。

## Review Focus

1. .next/standalone缺static/public却server存在：native缺树/空树拒绝，actualpackage及HTTPasset字节核对。
2. resealedmetadata、完整duplicateJSON、额外file/emptydir：manifest闭合/schema严格及canonical编码、exactobservedfiles；原生counterexamples。
3. source/target/artifact真实junction：先验证selectedsource和祖先，拒绝，不dereference已知privateinput。
4. sourcecopy期间字节改变：真实fs.copyFileSync seam反例拒绝，input不稳定不签收。
5. own服务退出但port被占/EOF未知：currentnativecaller必须等实际终态，再bind原port验证释放；ready/HTTPheader防误用foreign，日志不输出玩家/keys。

## Task 1: Independent code-only package integrity

**Files:** scripts/standalone-release-policy.mjs, scripts/tests/standalone-release-policy.test.mjs.

**Interfaces:** sync `packageStandalone(sterile:string,target:string)->manifestObject`, `verifyStandaloneRelease(target:string)->manifestObject`. sourcefixedtracedtree+static/public; target/cache directNEW. Exactmetadata and allhashes verified, no arbitrary inclusion argument. LOCALreports only.

- [ ] Step1 missingAPInativeFAIL；literalfixture ownserver/Nextpkg/BUILD_ID/static/public/privatecanaries excluded+actualcopies present/source unchanged；existingtarget sentinel保留、outside/ancestor拒绝；缺requiredfile/static/public拒绝、实源junction拒绝。
- [ ] Step2 native artifactbytes/missing/extra/emptydir/schema-bool/escape/full-duplicate/junction mutations拒绝；source真实copy seam改字节拒绝。
- [ ] Step3 node --test scripts/tests/standalone-release-policy.test.mjs ->standalone-package-red.log expectedgenuinemissingAPI failures；minimalfixedtree/copy/hash/canonicalmanifest implementation thensameGREEN及actualwholeharness纳入回归。

## Task 2: Actual artifact server ownership and HTTP smoke

**Files:** scripts/tests/probe-standalone-server.mjs (test helper, not deployed code); scripts/test-standalone-release.mjs (CLI exactlytwoabsargs: builtinput,newtarget).

**Interfaces:** generatedserver imported by Node helper `<artifact> <port> <instanceId>`; environmentfrontendEnvironment plusHOSTNAME127.0.0.1/PORT/TS17_INSTANCE_ID，仅OS/LOCAL env。No appservercode edited. CLI reports LOCALstatus/schema/manifestSHA/route-count/static-count/normalshutdown after allactualchecks, artifactpath onlyscopeowned。

Task2 exact export before implementation: async `smokeStandaloneRelease(target:string)->{status:'passed',localOnly:true,productionReady:false,routes:number,staticAssets:number,publicAssets:number,ownedResourcesClosed:true}`. New scripts/tests/standalone-release-smoke.test.mjs uses a SYNTHETIC real Node HTTP server/owned minimal next module to exercise wrapper protocol/capture/normal EOF, not a Next behavior/quality assertion; missingwrapper must actualFAIL first, corruptedbytes refuse beforechild, served mismatchingassets refuse andstillclose. Then actualcurrentNext package CLI is separate necessary proof. Helper blocks outboundnet.Socket.connect before importing server; parent onlyfetches its own randomheader loopback service.

- [ ] Step1 afterpolicyGREEN，actualCLIpackage fromsameownedbuild ->verify ->freeephemeralport ->hiddenhelper；parentstdout waitsactual Nextready line, runtime HTTPheader proof before eachcheck；所有errors有boundedcapture/timeout，不发requesttoforeignserver。
- [ ] Step2 actualpages200/HTML contains_next资产，解析真正href/src onlyowned /_next/static路径；GET CSS/JS至少各1且清单hash相同/public至少1 bytes相同，不运行browser或生产API。
- [ ] Step3 actualEOFmarker和Nextcooperative143exit，stopFixture noforce、portrebind成功、manifest重新核验。native失败保留完整日志；当前wholeharness/type/lint源保护/actual239native5same。记录完整现有artifact身份及NextWindowslocal边界后推进runbook/Minor/D25/finalfullEdge/ONEpeer/TS18，无重复TS16review。

## Preflight self-review

Step1 consumes currentstage实际input/buildidentity，不从旧next start猜包。build/static/public三树接口明确，NFT相对路径已验证，不复制原cachebackend。当前production网站/data/原node_modules不改，public许可仍TS18HOLD。Nextactualstart-server gracefulcode143来源已读；helper不改产品业务，而只增加ownedHTTPheader/EOF控制。五ReviewFocus均对应native或actualCLI assertions，无TBDinterface；整阶段门禁不被单元绿替代。
