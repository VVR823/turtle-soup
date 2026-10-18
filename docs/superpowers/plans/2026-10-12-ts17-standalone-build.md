# TS17 Owned Standalone Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL executing-plans inline/TDD, same TS17 ledger, no extra reviewers or phase confirmation. No Git/install/production/publication.

**Goal:** 用已完成物理deps副本的自有前端输入真正运行Next standalone构建，不用root依赖CLI或旧禁standalone wrapper冒充。

**Architecture:** 限定输入为project/.cache/ts07-frontend-*直接目录，所有文件/祖先/dep树无link，拒绝已有.next/私有根。只接受当前output/images config形状，闭合生成output:'standalone'/images.unoptimized:true/tracingRoot=owned input；调用OWN node_modules NextCLI。最后核对真实server.js/BUILD_ID/所有NFT路径仍在owned根内。此单元产物尚未补public/static或启动server；下一packaging/smoke单元才签完整包。

**Tech Stack:** installed Next16.2.12/Node22/TypeScript，标准fs/path/child_process；零下载。

**Spec:** docs/superpowers/specs/2026-10-12-ts17-local-release-design.md；上一精确materialization单元已原生完成。

## Global Constraints

- 只使用已完成输入`.cache/ts07-frontend-MLJK1w`，不再复制一次517MB依赖、不改变root配置/依赖/data/私密env。
- 需要NEW未构建输入，已有.next拒绝，不删除/覆盖旧artifact。
- 输入顶层允许package.json/package-lock.json/tsconfig.json/next.config.ts/postcss三扩展、src/public/node_modules；未知/隐藏/私有根拒绝，任意source/dep link拒绝。
- config只允许output:'standalone'和images:{unoptimized:true}，额外traceIncludes/cacheHandler/root属性拒绝。不扩tracingRoot、不安装新deps、不修改vendor。
- 构建必须由副本/node_modules/next/dist/bin/next运行，cwd同副本，frontendEnvironment白名单无NODE_OPTIONS/凭据，telemetry0；无真实API/provider调用。当前全部页面client-only数据请求在useEffect内，无next/font下载依赖。
- Next NFT Job每个ignore分支先拒绝relative外部路径；额外standalone entries来自ownedCLI require.resolve，全部materializeddeps在同trace根。额外手工includes/cacheHandlers被closedconfig禁止；构建后仍验证实际NFT全部路径。不是恶意第三方软件OS sandbox保证。
- gateLIVE冻结源/测试，不派peer；目录保留故障证据。

## Review Focus

1. 额外config设置会导入原workspace文件：原生closed configuration counterexamples拒绝。
2. 已有.next/rootcache/相邻alias输入：native启动前拒绝，不复用已有built artifact。
3. config/dependency真实junction：native文件系统拒绝，不读目标内容。
4. NFT可以合法用../../指向owneddeps，但不能逃出owned根：native有效/escape/absolute/link案例，路径边界而不是一刀切拒绝所有..。
5. Build退出0但入口/BUILD_ID不全：actualnativedriver须检查真实文件，缺失不签收；完整HTTP/browser留下一单元/最终Edge，不声明当前已通过。

## Task 1: Closed build inputs and trace boundary

**Files:** scripts/standalone-build-policy.mjs; scripts/tests/standalone-build-policy.test.mjs; scripts/test-standalone-build.mjs.

**Interfaces:** sync `standaloneConfiguration(config:object,directory:string)->object` returns exact output/images/root settings; `validateStandaloneBuildInput(directory:string)->{directory,nextCli,configPath}` project-owned path and physicalfile checks; `checkedTracePath(directory:string,traceFile:string,entry:string)->string` returns inside relativePOSIX actualregularfile path, rejects invalid/absolute/outside/link input. Async CLI wrapper has one absolute directory argument, expectedvalidactualparams known, exitsnonzero failure, no overrideenv/paidI/O.

- [ ] Step1 new native tests missingAPIFAIL, exactconfigresult/deep shapes/extra settings拒绝，真实未建输入接受、已有.next/非owned/私密env/dep真实junction拒绝，NFT合法owned../dep接受但escape/abs/junction拒绝。
- [ ] Step2 `node --test scripts/tests/standalone-build-policy.test.mjs` ->standalone-build-policy-red.log ExpectednativemissingmoduleFAIL。
- [ ] Step3 minimal policy；wrapper读取ownednext.config.ts用已装TStranspile/import其trustedconfig，closed validate后只在owned副本rename为next.config.source.ts、生成mjs固定config；spawn ownNextCLI build absdir --webpack，normal hiddenownedchild、无外部网络/原data，Exit0也须真实入口BUILD_ID/NFT闭合后输出boundedLOCAL JSON receipt。
- [ ] Step4 nativepolicy+wholeharness/type/lint actualselected0fail，并运行一次真实owned输入CLI到standalone-build-current.log/json；Expected actualNext EXIT0、server.js和BUILD_ID存在且所有trace路径安全。若编译失败保留原owned目录/日志，不重跑已失败source猜补配置。
- [ ] Step5 ledger真实结果与源码/产物身份、原239 hash/HEADindex；继续精确packaging/static/public/manifest和实际server HTTPsmoke子计划，之后runbook/Minor/D25/全阶段fullEdge/ONEreview。

## Self-review / rulings

此brief仅原发布scope的实际构建单元，typedshape与上一步directory接口一致；原Next config实际只有这两个render/package属性，无静默丢弃用户配置。实际Next start-server正常合作SIGTERM会exit143，后续smoke应通过EOF helper process.emit(SIGTERM, SIGTERM)驱动真实gracefulcleanup并核验端口，不将Windows强杀或未知退出当成功。SourceRegistry/模型质量/生产Linux/Docker/公开授权仍不被构建证据替代。每个ReviewFocus有native或真实构建检查，Task6前整个TS17不验收。
