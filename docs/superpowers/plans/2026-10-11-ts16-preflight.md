# TS16 统计设计前置调查（不是实施计划或验收证据）

2026-10-11 13:10 UTC接续：TS15原唯一审查实际交付/关闭、全部裁定与一次修复和当前2737离线/312定向/31Edge已签收，324源码/51证据最终快照逐项0变化。下面“Feynman仍在审查”是本文创建时的历史条件，已解除；本文仍只有只读预勘，不冒充正式spec、实施、性能或真实流量。下一步按原A57及测试计划实际统计条目编写正式设计/计划，沿用既定自主执行授权。

TS15唯一审查者Feynman仍在审查冻结快照。本文只记录对既有代码的只读调查，未创建统计接口、迁移或测试；不改TS15冻结文件。后续须在TS15实际收尾后，以正式spec和implementation plan接续。用户已授权按照原18阶段连续执行，沿用主代理原生实现、每阶段一位独立审查者，不新增阶段确认/提交/付费模型/生产操作。

## 原目标，不扩大范围

原实施计划TS16及A57要求：固定窗口内可复核的会话、成功计次turn、请求尝试、反馈、评审和发布候选；默认7天/最大31天，管理分页默认50/最大100，验证游标、边界、索引与批量聚合；200会话/1000turn/5000审计事件的明确合成性能测量，报告真实测得的P50/P95及资源。排除测试流量，展示审计缺口，不能将会话数称为用户人数，导出不能包含原文或敏感ID。

不需要新分析服务、Redis、数据仓库或付费分析平台。不读取实际用户库来凑成绩，不添加身份追踪/去重用户ID，不宣称人工修复建议一定语义正确。

## 已核实的现有表面

- `migrations.py`已注册001/002/003；`verify_schema`与`migrate`只接受版本1–3。默认migration001/app002不变。001/002/003 SQL/checksum不可修改；现有主干不能假定支持004。
- sessions有`created_at`、`traffic_class`（legacy/real/synthetic/test）、固定puzzle/rule版本；无稳定用户身份。历史迁移默认legacy，不可归为新增真实流量。
- turns有实际`id`、`state`、`kind`、`charged`、`created_at/completed_at`、固定puzzle/rule版本及session外键。成功计次应从completed/charged及合规answer/win统计并按turn去重，不从消息条数或HTTP尝试数推算。
- audit_events有唯一事件ID、`event_type`、`details_json`、`created_at`；`http_attempt`是请求尝试，`replayed`仍是另一次请求，不等于新增成功提问。`AuditMetadata.versions`是嵌套HostVersions，不存在独立SQL `rule_version`列。
- `idx_audit_events_time(created_at,event_type)`已存在。现有5000行原生测试观察真实reader SQL和EXPLAIN索引/SQL LIMIT，不是统计接口性能测量。
- `idx_feedback_status(status,created_at)`和`idx_agent_runs_state(state,updated_at)`已存在。sessions创建窗口、turn完成窗口、agent创建窗口及候选创建窗口没有对应创建/完成时间索引；不能凭索引名字断言新查询已有合适索引。
- feedback_items不含`traffic_class`或puzzle/rule独立列。其`source_json`可能只有unverified状态，也可能含实际linked turn/session/版本；`feedback_submitted`必要审计含反馈ID及实际runtime产生的trafficClass。直接只JOIN turn会漏掉合法无关联手工反馈；不能把这些反馈悄悄丢掉或默认归为真人。
- agent_runs真实trafficClass来自不可变manifest；候选SQLstatus是工作流，不是不可变candidate_json的pending，也不是原任务awaiting_review。统计不能重写这些历史或把人工批准等同语义准确率。
- `candidate_reviewed`审计包含approved/rejected；`candidate_published`包含实际候选/任务/批准操作绑定及from/to规则版本；generic rule_published/rollback另计。不能把同次发布的两类事件加成两次候选修复。
- audit coverageStart来自002迁移报告，声明未回填历史请求；003同样不回填历史任务。AuditStore.status提供complete/permanentGap/dropped/fallbackCount/fallbackBytes/memoryCount/memoryBytes/activeIO/coverageStart。统计GET不能自动recover；全进程审计缺口不是某时间窗精确缺失数量。

## 设计时必须明确的消费契约

1. 时间语义：会话/反馈/任务/候选创建队列按各自创建时间；成功计次按turn完成时间；请求/审核/发布事件按事件时间。当前状态分布不是历史截止时间状态，必须标清。所有子查询使用同一固定窗口和SQLite读取快照。
2. 版本语义：来源规则版本与发布后的目标版本不是同一过滤维度。反馈/请求缺版本归属时必须显示未知数量，不猜当前版本，不悄悄计为零。
3. 流量语义：仅真实分类可计入默认统计；test/synthetic/legacy/unknown分别排除/展示。允许声明合成、真实标记的离线样本复核生产过滤逻辑，但测量报告必须仍标为合成，不称真实网站流量。
4. 分母：任务失败/排队/运行/取消/转人工全部保留；发布比例须说明整个任务队列分母和创建队列口径。绿色回归/已审核/已发布不能作为真实语义修复准确率。
5. 隐私：summary/export只从明确字段白名单构造；不输出问题、背景、模型输出、审核理由、会话/turn/请求/反馈/任务/候选/操作ID，亦不以散列ID绕过限制。公开题品/公开版本筛选与敏感个体ID要明确区分。
6. 索引和迁移：若设计采用新时间范围索引，须追加明确的004注册及校验、事务/失败回滚/重复执行/旧001–003兼容测试，不修改已发布SQL/checksum，不在GET/默认启动中自动迁移，不自行迁移生产。先验证实际查询计划，不能只新增一个名为“stats”的索引。
7. 前端：管理员独立token、固定窗口回读、分页/过滤绑定、旧token/旧筛选迟到响应不能恢复私有统计；不在游戏页后台无限轮询。明确不可用/未知/缺口，与真实零计数区分。

## 安全接续点

在上述已核实表面基础上，写正式TS16设计与具体接口/字段/测试计划，再原生TDD实施。当前没有合成规模性能数据、真实统计查询结果、P50/P95或资源测量，不能填数字。原用户库、生产统计导出/部署和真实用户数字仍不读取、不公开。先完成TS15原唯一审查及一次严重/重要修复，禁止借TS16改动并发修改冻结源。
