# 恢复协议与浏览器存储边界补测计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans。用户已授权连续执行，不等待阶段确认。

**Goal:** 给原C09/C13/C14中真实未命中的恢复/拒绝分支增加用户可见行为断言，不改变正常问法、协议或状态机。
**Architecture:** 只新增一个默认Vitest文件；真实journal/controller/localStorage，只有外部HTTP以完整DTO替代。已有正确行为允许直接绿色，明确是补测而非产品修复或伪造RED。
**Tech Stack:** 现有Vitest5.0.3/jsdom/TypeScript；复用已核官方V8 provider，不安装依赖。
**Spec:** 原TurtleSoup_升级测试计划_2026-10-06.md第14/55行100%新路径目标及C09/C13/C14；当前400源f9e13b98…及真实前端399覆盖。

## Global Constraints

- 不改产品/锁文件/原Git/真实数据；不调用模型、生产或外部网络；保留所有A01/旧覆盖原字节。
- 不为覆盖删分支、排低覆盖文件、调低门槛或把语义错答当解析异常；未达到100%继续准确记缺口。
- 新报告只写.cache/c25，后端原3040结果不重跑不重算；A01快照身份作为当时证据，不冒称新增测试已在该快照内。

## Review Focus

- 非法路由目标不读空记录后另建局；测试无效目标拒绝且合法原journal保留。
- window不存在不是空journal；读取/保存必须拒绝，真实存储原记录不变。
- 恢复GET期间另页改指针不能被旧响应覆盖；保留foreign pointer，无新POST。
- 同步按钮不能在初始化在途时重复发请求或换UUID；用事件控制HTTP完成，禁止sleep碰概率。
- HTTP状态/turn状态不匹配，以及reveal成功响应后canonical session仍playing，不能清除原意图或显示假终态。

## Task 1: 十项恢复边界与完整前端验证

**Files:** Create src/lib/recovery-protocol-boundaries.test.ts；缓存覆盖配置/证据.cache/c25；同名progress。生产文件只读。
**Interfaces:** 消费GameController和game-journal公开API；输出真实10项边界结果、默认前端全量/type/lint终态、同源覆盖及剩余分支。

- [x] 写非法目标3例、无window1例、指针竞争1例、初始化同步1例、坏状态码2例、未持久化揭晓1例、HTTP失败揭晓1例；每项注明可捕获的生产错误行为，断言真实记录/状态/网络边界。
- [x] 先跑新文件并读实际结果；实际10PASS，已有正确行为直接PASS不称RED，不改生产实现制造仪式。
- [x] 完整默认前端带覆盖实际409PASS/25files；最终类型及新文件lint退出0/空日志，首轮测试签名错误及警告修正证据保留。
- [x] 原400输入未变/新401摘要5ab57e37…，同分母新增8分支命中/零倒退；主数据/Git保护不变，唯一限定审查实际C0/I0/M0，无修复或复审待办。

## Rulings

沿用既有特性分支和未提交工作，不创建改主Git注册的工作树；新增测试不修改产品行为，TDD的真实RED仅用于实际发现缺陷时。代价是本单元不能声称修复了生产缺陷；保留真实基线和补测结果即可。
