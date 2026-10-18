# TS17 Owned Next Dependencies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL superpowers:executing-plans inline/TDD; shared TS17 ledger, ONE whole-stage peer only at final delivery. Autonomous authorization already supplied; no phase confirmation/Git writes/production actions.

**Goal:** 为实际standalone构建准备全部在自有目录内的前端输入，消除当前node_modules junction导致的tracingRoot逃逸风险。

**Architecture:** 复用createSterileFrontend和frontendEnvironment。先只读验证已安装node_modules全树无link/非普通文件，复制到新sterile目录内，不扩大tracingRoot至真实workspace；副本使用自己的Next CLI。输出只是LOCAL构建输入，不是已验收发布包。

**Tech Stack:** installed Node22/Next16.2.12，标准fs/path/crypto/test；不下载、不install、不改node_modules。

**Spec:** docs/superpowers/specs/2026-10-12-ts17-local-release-design.md；isolated-release的原Task2仅follow-up设计，此为其第一个独立可执行单元。

## Global Constraints

- 所有写入是projectRoot/.cache的直接新sterile子目录；实际目录祖先/配置/源不能link或redirect。保留故障证据、不递归删除目录。
- 原dep目录只读，复制全24124普通文件约517MB，本机实际70GB可用；之后仍按当前树验证，旧数字不是永久空间保证。
- 不复制工作区data/backend/private/.env/Git/tests；新seed后端单元独立，不读原seed。构建dep是已装软件，不因此声称全面密钥扫描/来源许可。
- createSterileFrontend仅创建本次新目录内明确node_modules junction；只在核对其actuallink目标等于本次验证dep根时unlink这一个自己刚创建的link，随即用普通目录副本替代。不能对已有artifact/dependency目录做recursive delete。
- Inputs重复前后bytes/hash核验；所有dep副本必须普通文件、摘要一致；source变化拒绝，不签收、不重试覆写。
- frontendEnvironment净化与telemetry禁用保持；NextCLI必须副本/node_modules/next/dist/bin/next，configoutputFileTracingRoot只等于该副本，严禁原deps路径/真实workspace宽根。
- 此单元不构建/启动服务/部署/上传，旧page build仍不是standalone证据；真正构建、traces检查、server/static/public精确清单与HTTP冒烟需下一份精确brief。
- ONE gate LIVE时冻结源码，normal approvals，不要求用户点击。

## Review Focus

1. 已安装dep根或任一ancestor link到别的目录：输入校验先拒绝，不能靠复制后扫描阻止已读取的逃逸。
2. dep树内部真实junction/非普通文件：native夹具拒绝，target不创建；不偷偷dereference或skip未知文件。
3. 原source复制途中改字节：复制后原bytes与dest摘要不符拒绝；使用真实fs.copyFileSync seam变异合成字节，不断言mock调用。
4. 复制后的node_modules仍link回原安装：native物理目录验证+原source修改不影响副本，输出不依赖旧cwd/deps。
5. root/.cache已有junction或cache目标别名：创建sterile副本前拒绝，不写真实别的目录。

## Task 1: Materialized standalone build input

**Files:** create scripts/standalone-input-policy.mjs, scripts/tests/standalone-input-policy.test.mjs; modify package.json test:harness after selectedGREEN.

**Interfaces:** synchronous `prepareStandaloneFrontend(projectRoot:string) -> {directory:string, dependencies:{files:number,bytes:number,digest:string}}`; consumes existing createSterileFrontend(root,cache) and frontendEnvironment in futurewrapper. No arbitrary target/output/config input, root absolute, existing node_modules. digest is SHA256 of sorted POSIX path/SHA256 records, not proof of npm provenance.

- [ ] Step1 test dynamic missing module mustFAIL；fixtureknownfrontendconfig/src/public+installeddep3files，其中dep文件字节canary不同于privatecanary；实际输出src/public/配置存在、private/backend/env不在，node_modules是regular directory，copies bytes相同，修改originaldeps不影响copy，files3/bytes手算/digest64hex。
- [ ] Step2 native source/cache/dependency junction3cases、missingdepfile读失败与source变化真实copy seam fail；源、外部canary不变；拒绝发生在创建新sterile目录之前（source变化则保留故障目录）。
- [ ] Step3 `node --test scripts/tests/standalone-input-policy.test.mjs` -> .cache/ts17/standalone-input-red.log；ExpectedmissingAPI genuineFAIL，不是collectionerror。
- [ ] Step4 minimalimplementation：先祖先lstat/realpath、已存在cache非link验证、dep目录全树regularfile SHA inventory；createSterileFrontend；验证且仅unlink新link；mkdir物理node_modules，逐文件copy+hash；重新inventory源集合/hash与before相等；return物理目录+汇总，失败不删除/falsegreen。
- [ ] Step5 同native+frontend-build-policy+backend release/harness actualnpm regression ->0FAIL，真实installedtree准备一次保留artifact输入及摘要报告；不启动Next或签收standalone。全项目当前验证仍在TS17最终交付。

## Self-review / preflight ruling

已读取installed output.md、collect-build-traces.js及copyTracedFiles真实实现；NFT Job.ignoreFn对function/string/array所有分支先拒绝relative '..'+sep，直接extra standalone server entries来自require.resolve，因此启动自己的NextCLI及全部physicaldeps位于owned trace根内很重要。当前next.config只有output/images且无外部cacheHandler/traceIncludes。Next构建前下一brief还须锁定配置允许项、入口/root边界与实际所有trace路径核验；不把这份输入准备计划当作最终包计划。ReviewFocus各点均有native用例；它只覆盖发布scope单元，runbook/Minor/D25/fullEdge/ONEreview及TS18仍保留。原239/HEAD/index不动，无phasepause。
