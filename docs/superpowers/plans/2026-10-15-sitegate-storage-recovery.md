# SiteGate 口令读取异常恢复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans。按既有本地实施授权连续执行，不逐阶段确认。

**Goal:** 浏览器在口令提交前拒绝存储读取时，保持锁屏、显示可重试错误且不发送验证；恢复存储后同一输入可正常验证。
**Architecture:** 先以真实SiteGate/Storage和合成HTTP复现，再将出错读取移入现有try/catch/finally；不更改鉴权规则、口令存储格式、后端或正常游戏流程。
**Tech Stack:** 原React/Vitest/jsdom/TypeScript，无新依赖。
**Spec:** 原C01/C15/A02/A33错误隔离和SiteGate不能把故障当验证成功；当前C26最终402/b0b2f3c7…/416前端。

## Global Constraints

- 生产编辑白名单仅src/components/SiteGate.tsx；测试新增src/components/SiteGate.storage.test.tsx。其余改动只.cache/c27及阶段docs，保护用户修改/原239/HEAD/index。
- Fake fetch仅返回合成config/catalog，不真实网络/模型/生产，不改锁、不付费、不部署/公开/提交主Git。
- C26额外反例审批超时单列待办，不绕过；先将其SUT依赖闭包绑定已有不可变A01快照，使本不相干SiteGate修复不破坏待验证来源。
- 现有前端构建产物在生产源码变化后仅作旧历史，不冒称当前新构建；交付刷新另留真实待办。

## Review Focus

- 初始检查正常、提交时才抛SecurityError：无未处理Promise、无提前请求、无保存token。
- 错误后submitting/checking必须复位，同输入恢复存储后可成功，不需刷新整页。
- 正常/401/503/坏JSON仍按既有目录合同验证，不能为恢复跳过鉴权或盲信缓存。
- C26独立诊断仍只经正常审批；快照5模块闭包不含SiteGate，来源/SHA与原SUT一致。
- 新源码不能沿用旧24前端runtime产物身份；明确遗留构建验证，不冒充全目标完成。

## Task 1: 真实复现、最小修复与验证

**Interfaces:** 消费SiteGate表单及真实getSiteToken；仅HTTP合成。输出原生RED/GREEN、完整前端417预期/type/lint/独立审查及保护证据。

- [x] 初始locked后getItem抛错的真实DOM回归已实现，覆盖错误/锁屏/无catalog请求及同输入恢复。
- [x] 原生RED实际1FAIL+Unhandledgetter，堆栈api14→unlock54；原日志与ANSI检测澄清、matcher失败均保留。
- [x] 仅移动previousToken进现有try；正确测试原组件副本RED/当前GREEN，无接口或授权放宽。
- [x] 实际完整417/type/生产+测试lint通过，403限定两文件变化，唯一独立C0/I0/M0；原239/Git保护不变。
- [x] 实际刷新物理standalone构建/2045文件新包/自有HTTP资源冒烟，未复用旧包；本机浏览器整套/全任务及C26额外反例仍单列待办。

## Rulings

使用gstack investigate/systematic-debugging先复现再修；原本地计划已授权此类错误UX，不重复阶段确认。技能升级/路由注入/遥测/远端同步/自动提交均不属本任务，不执行。Windows以本阶段显式白名单作编辑边界，不更改全局freeze/账户设置。
