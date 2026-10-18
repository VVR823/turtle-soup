# 默认恢复轮询与取消：补测计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans。既有连续执行授权，无需阶段确认。

**Goal:** 补原C09/C13/C14真实默认计时器的轮询间隔、有限停止和页面离开取消行为，不更改产品实现。
**Architecture:** 新增默认Vitest文件，调用真实GameController/journal/localStorage及默认pause；只替代外部HTTP，以fake timers确定先后，不注入sleep代替被测计时逻辑。
**Tech Stack:** 原Vitest5.0.3/jsdom/TypeScript/本地V8 provider，无依赖安装。
**Spec:** 原测试计划C09/C13/C14和100%新路径目标；C25最终401身份5ab57e37…/409测试/84.64%。

## Global Constraints

- 不改原401字节/产品/锁文件/Git/真实数据，不调用外部服务或付费模型。
- 新证据只写.cache/c26；保留C25及A01全部历史，不重跑后端或扩称真实浏览器/生产验证。
- 既有正确行为补测允许直接绿色，不制造生产RED；若发现真正缺陷另按真实RED→GREEN执行。

## Review Focus

- 默认轮询应等待完整1000ms且至多三次，同一UUID/GET-only，不提前清除未知提交意图。
- 离开页面既取消已排队timer，也拒绝已aborted信号；监听器在syncing发布时离开是合法重入边界。
- timer已触发但await续体尚未执行时离开，不得发下一次GET；用同步advance后dispose控制顺序。
- 迟到turn GET不能在新页面改状态、journal或指针；保留原请求。
- 非Error拒绝值不向玩家泄漏原内容或丢失创建UUID，显示可恢复network错误。

## Task 1: 默认轮询生命周期七项与完整前端验证

**Files:** Create src/lib/recovery-poll-lifecycle.test.ts；.cache/c26报告/工具；同名progress。生产文件只读。
**Interfaces:** 消费GameController公开方法/subscribe与journal；输出七项默认timer/取消/错误结果、完整前端416预期（以实跑为准）、type/lint/覆盖/保护回执。

- [x] 新增正常三次1000ms轮询、pendingtimer取消、发布时取消、timer触发后取消、迟到GET取消、非Error拒绝两例；使用afterEach统一dispose/恢复真实timer，独立字面DTO/状态断言。
- [x] 定向运行实际观察；直接绿色记录为已有正确行为补测，不声称产品修复。
- [x] 冻结原401+新1文件=402显式输入，执行完整前端带覆盖/type/新文件lint，保留日志/XML/终态。
- [x] 比较同源覆盖与原401零漂移、主239/Git保护；唯一限定审查及处置后闭合，不复审已验收C25。

2026-10-15T16:02Z本地闭合：唯一审查Important已一次修正，后续正式审批的隔离副本before通过/after预期失败已实际执行；[资格证明](../../../.cache/c26/timer-cancel-qualification.md)准确记录额外根目标、过滤项与原源码未变。此为本单元完成，不是原整体目标完成。

## Rulings

沿用原特性分支/用户未提交改动，测试-only不新建主Git工作树。覆盖仍是全目标中一部分；没有证据的UI调度、远端取消及100%目标不以本机timer补测代替。
