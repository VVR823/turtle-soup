# TS14 状态：本地工程验收完成，真实质量与生产门禁保留

本页区分本地机械验证和外部真实质量。TS01–14本地工程已收尾，TS14原唯一审查已完成（1 Critical/4 Important/1 Minor），一次严重/重要修复及当前整套、页面、静态和文档门禁已取得实际结果，原审查者已关闭。较小审计分类问题留TS17；不能把本地验证当真实模型质量或生产验收。[循环参考](agent-loop-reference.md)、[大白话解释](agent-loop-explanation.md)、[本地操作](agent-loop-howto.md)、[审查原报告](ts14-review-report.md)与[逐项裁定](ts14-review-resolution.md)提供入口。

## 实现范围

- 严格模型动作、持久化决策/结果、同episode一次纠错、停止/取消最小状态。
- 模型自主选择工具的有界循环、8000字符提示词、同动作一次工具重试；失败/未知记录不删除，恢复继承原10/8/180预算。
- SQLite单任务协调器、60秒租约/独立10秒心跳、在线优先原子网关准入、关闭与未知清理保守留名额。
- 管理员专用启动/状态/取消HTTP，默认关闭、显式003、不自动迁移；无候选批准/发布接口。
- 8条完整、明确声明合成的隔离任务报告；不是实际模型或真人审核记录。

## 证据（历史与当前分开）

| 快照 | 实际证据 | 边界 |
| --- | --- | --- |
| Unit1 | `unit1-final-full.xml`，2294离线通过/10skip，412 Eval通过 | 决策/停止单位快照，不含后续worker/HTTP |
| Unit2 | `unit2-final-full.xml`，2334离线通过/10skip，412 Eval通过 | 循环/恢复单位快照，不含后续worker/HTTP |
| Unit3 | `unit3-final-full.xml`，2368离线通过/10skip，412 Eval通过 | worker单位快照，不含新增HTTP/任务报告 |
| Unit4 HTTP定向 | `admin-current-selected.xml` 138通过；`admin-boundaries-selected.xml` 132通过 | 文件集合不同，不是全套数量下降；HTTP29项 |
| Unit4报告定向 | `task-report-current.xml` 43通过，含8条报告、29 HTTP及相邻恢复/条件循环 | 当前定向，不是完整全量或独立审查 |
| Unit4当前完整门禁 | `unit4-final-full.xml`，2408离线通过/10skip，412 Eval通过；`unit4-final-selected.xml` 313通过 | 独立审查前快照；API110668已正常关闭，原239完整SHA未变 |
| 文档示例与链接 | `docs-examples-current.xml` 65通过；`doc-links.csv` 5页40链接/0断链 | 修正Windows默认缓存不可写警告后复验；不是生产操作示例 |
| 页面/构建/静态 | `unit4-final-ui.xml` 29 Edge页面通过/0skip；隔离build成功；lint/typecheck均退出0、diff0 | 审查前证据；API114228及自有前端已正常关闭，cleanup0，页面后原239同完整SHA |
| 修复后当前门禁 | `review-final-full.xml` 2422离线通过/10skip，412Eval通过；`review-final-selected.xml` 338通过 | 2163后端/231前端/25Node/3API；API114884已正常关闭，原239同完整SHA |
| 修复后当前页面/静态 | `review-final-ui.xml` 29 Edge通过/0skip；隔离build成功；review-final-lint/typecheck均退出0 | API96892与自有前端正常关闭/cleanup0，页面后原239同完整SHA；不证明新增TS15审核页面 |
| 原生审查边界 | `review-controls-current.xml` 14通过 | 7个真实审查失败复现后修复，其余为正常路径/回滚保护；旧截止时间误归类回归也已修正 |
| 修复后文档例子/链接 | `review-docs-examples-current.xml` 79通过；`review-doc-links.csv` 7页96链接/0断链 | 含4个合法目录链接，不因仅检查文件而误判；实际例子不是生产运行证据 |
| 修复后8合成报告 | `review-synthetic-task-reports.json`，来自当前完整JUnit的8个实际property | 旧synthetic-task-reports.json仅为审查前历史，不覆盖原冻结证据；两者均不是真实模型或人审结果 |

证据文件位于本地 `.cache/ts14/`，未公开上传。`synthetic-task-reports.json` 从上述实际JUnit的8个property导出；测试 XML 与报告比手写总结更接近源证据。报告记录真实隔离任务ID、全步骤状态、原/现期限、预算、适配器调用、合成播种、实际清理状态和回归分母，不含玩家原文或私密模型输出。

| 合成场景 | 终态 | 模型/工具预留 | 本轮适配器调用 | 清理确认 |
| --- | --- | --- | --- | --- |
| candidate | awaiting_review，候选pending | 3/2 | 3 | true |
| counterexample | needs_human，无候选 | 2/1 | 2 | true |
| invalid | needs_human / model_output_invalid | 2/0 | 2 | true |
| tool-failed | needs_human / tool_failed | 1/2 | 1 | true |
| cancelled | cancelled / cancellation | 1/0 | 1 | true |
| deadline | needs_human / deadline | 0/0 | 0 | true |
| resume-nine-seven | needs_human，继承已用9/7 | 10/8 | 1 | true |
| cleanup-unknown | needs_human / model_unavailable | 1/0 | 1 | false |

预算不等于供应商接受次数。第7行先前9个模型预留是明示合成播种，不是10次真实云调用；第8行清理失败保留名额不是证明远端还在推理。失败工具两次失败都留在步骤中，取消时未知planned不伪造完成。

## 仍待验收 / 搁置项

| 项目 | 当前状态与原因 | 不受影响的工作 |
| --- | --- | --- |
| Unit4本地最终门禁与唯一审查 | 本地工程完成：唯一审查/一次修复、2422离线/29页面、build/lint/type、79文档示例/96链接、原239SHA；原审查者已关闭 | 直接接TS15；保留Minor和外部真实门禁，不重复已验收项 |
| A50真实免费模型安全轨迹 | HOLD，未验证账户资格/未进行真实调用 | 保留供应商适配层；不调用付费模型或以脚本假模型冒充 |
| A53八项真实人工参考 | HOLD，缺真人独立答案/审核 | 8合成场景仅证明工程路径，不关闭此门禁 |
| 独立corpus接入应用worker | 本地工程接线尚未交付，计划TS15；实际独立人审corpus仍HOLD | 交付显式可信共享输入接线与离线测试，但不能自动发现私有材料或把合成证据变成生产人审证明 |
| 生产迁移/启用/部署/公开上传 | 未执行，不在自主本地授权范围 | 本地隔离实现和说明继续；不改真实用户数据 |

修复后当前完整离线门禁和页面后均核验原239文件SHA未变：`d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a`。阶段ledger见 `docs/superpowers/plans/2026-10-10-ts14-progress.md`；旧失败和修正记录保留，本页已同步原唯一审查、逐项裁定和一次修复后的实际结果。
