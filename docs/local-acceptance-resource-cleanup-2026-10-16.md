# 2026-10-16 本地验收与测试资源清理

用户授权继续完成本地验收；真实模型与人审材料尚无。永久禁止自动续跑、Loop、heartbeat 和定时任务。本报告只记录本轮实际执行，保留旧日志，不提交 Git、不发布或操作生产数据。

## 当前执行状态

本轮手动本地验收已结束。后端第二次完整运行于北京时间 **11:24:48–11:48:32** 执行，退出 0；单次完整结果为 **3030 通过、14 跳过、0 失败/错误**。前端最终 **584 通过**，类型检查及新增文件 lint 均通过且无警告。没有创建后续调度。

项目为 `D:\CODE\turtle-soup`，分支 `codex/ts02-storage-foundation`，HEAD `c5765b68cb251a7c566e76e2887d335d6ed6b285`。升级代码仍在未提交工作树；本地测试结果不能证明主 HEAD 包含完整升级。

## SQLite 连接生命周期

前次完整运行的 546 条 ResourceWarning 是历史测量。本轮没有关闭警告，而是在完整后端命令中把 `ResourceWarning` 和 `pytest.PytestUnraisableExceptionWarning` 均设为错误。

新增 `backend/tests/test_fixture_connection_ownership.py` 两项回归，直接检查原统计/发布测试夹具返回后连接已经关闭，并独立重新打开数据库核实 schema 5 确实提交。两项先实际失败，再在修复后通过：[RED XML](../.cache/manual3-acceptance-20261016/fixtures-valid-red.xml)、[GREEN XML](../.cache/manual3-acceptance-20261016/fixtures-green.xml)。最初一次探针曾引用错误的夹具名，保留日志，不把它算作有效 RED。

第一批只修测试中的单上下文连接：24 文件、107 处。使用 `with closing(connect(...)) as conn, conn:`，保持内层事务先提交/回滚、外层连接再关闭；未改变业务代码、测试断言或警告策略。[逐文件哈希及 AST 核验](../.cache/manual3-acceptance-20261016/fixture-connection-changes.json)。

第一次严格全量在 807 项通过后因未关闭连接停止，错误出现在 evaluation snapshot 模块 setup，原始结果 **807 passed / 1 error**，不能算全量通过。[完整日志](../.cache/manual3-acceptance-20261016/backend-full.log)、[XML](../.cache/manual3-acceptance-20261016/backend-full.xml)、[终态](../.cache/manual3-acceptance-20261016/backend-exit.json)。

继续检查发现多上下文形式 `with runtime_context(...), db._connect() as conn:` 尚未关闭连接；第二批修复 10 文件、27 处，保持 runtime 上下文及事务退出顺序。两批共 32 个不同测试文件、134 处；原文件逐字节备份在对应证据目录，AST 仅允许 closing 和事务上下文插入。[第二批核验](../.cache/manual3-acceptance-20261016/mixed-contexts/fixture-connection-changes.json)。

第二次完整执行不使用首错停止，以一次运行收集剩余错误。仍然启用上述两类警告即失败，不自动重试、不访问真实模型。[启动命令和时间](../.cache/manual3-acceptance-20261016/attempt2/backend-started.json)、[运行日志](../.cache/manual3-acceptance-20261016/attempt2/backend-full.log)。

最终单次完整 XML 含 **3044 个不同后端用例：3030 PASS / 14 SKIP / 0 FAIL / 0 ERROR**，严格资源警告模式整套通过，成功日志没有 ResourceWarning 或 PytestUnraisableExceptionWarning。旧 546 条警告保留为历史，首次失败也不改写。[完整 XML](../.cache/manual3-acceptance-20261016/attempt2/backend-full.xml)、[终态及输入零漂移](../.cache/manual3-acceptance-20261016/attempt2/backend-exit.json)、[逐项汇总](../.cache/manual3-acceptance-20261016/accepted-results.json)。这次是主环境执行，不能写成 A01 独立环境又跑了一遍。

14 项跳过逐个保留：7 项真实模型需要显式 opt-in，6 项原生 symlink 权限不可用，1 项 Unix socket 不可用。未改系统权限，没有用模拟调用将它们记为通过；每个用例及原因见逐项汇总和日志末尾。

## 后端生产覆盖的同范围核对

原始覆盖含 143 个文件（包括 eval 测试），没有将其混入生产覆盖。按原报告相同的 **110 个生产文件**逐一匹配，没有漏文件；语句分母 **12672**、分支分母 **4032** 均不变。

- 语句：11316/12672 = **89.30%**。
- 分支：3118/4032 = **77.33%**，仍有 **914** 个未命中分支结果。
- 相比上次完整运行的 3122 个分支命中，本次少 4 个，报告使用本次实际结果。差异定位到 `runtime.py` 的 183→185 和 `benchmark_admission.py` 的 35→36、36→38、38→35；未逐项证明差异成因，不作推断，也不据全套通过声称覆盖目标完成。

[原始覆盖](../.cache/manual3-acceptance-20261016/attempt2/backend-coverage.json)、[相同生产范围及完整缺口](../.cache/manual3-acceptance-20261016/backend-production-coverage.json)、[逐文件差异](../.cache/manual3-acceptance-20261016/backend-coverage-delta.json)。

## 前端补充验收

本轮新增测试验证既有行为，未修改生产组件或接口实现：

| 文件 | 用例数 | 核对范围 |
| --- | ---: | --- |
| `src/lib/browser-storage-boundaries.test.ts` | 21 | SSR、非法本地历史、拒绝读取、会话指针与定向清除 |
| `src/lib/private-contract-boundaries.test.ts` | 41 | 统计完整性、审计待写入、计数比例、反馈时间戳/重复行/分页与响应 |
| `src/lib/agent-review-boundaries.test.ts` | 40 | 诊断类型一致性、模型错误、队列预算、候选身份、规则新增/替换边界 |
| `src/components/FeedbackButton.boundaries.test.tsx` | 13 | 路由切换、输入聚焦、失败可重试、取消请求、表单重置 |
| `src/components/private-feedback-acceptance.test.tsx` | 5 | 普通反馈完整提交、无效表单拒绝、异常目录、候选 ID 与玩家理由 |

以上 120 项前端测试和 2 项后端回归均有实际执行记录。没有用模拟数据替代真实人审或模型质量验收。测试自身曾有关闭按钮选择不唯一、合成目录缺少 tags 等问题，仅修正测试，原失败日志保留。

前端覆盖工具需要使用既有 `.cache/a46/frontend-bound-coverage.config.mts`。本轮有两次工具配置失败（默认依赖缺失、未使用已有 custom 包装），未执行有效应用测试；其零覆盖输出不作为验收覆盖数据。随后使用原有绑定配置完整运行通过，不安装或修改依赖。

最终完整运行：**35 个文件、584 项通过，0 失败/错误**；类型检查退出 0，5 个新增前端文件 lint 退出 0 且无警告。实际执行时间为北京时间 11:30:27–11:30:59。[XML](../.cache/manual3-acceptance-20261016/frontend-complete/tests.xml)、[日志](../.cache/manual3-acceptance-20261016/frontend-complete/frontend.log)、[退出码与时间](../.cache/manual3-acceptance-20261016/frontend-complete/exits.json)。

| 同一生产范围 | 最新分支命中 | 说明 |
| --- | ---: | --- |
| `api.ts` | 86/86 = 100% | 存储与请求边界 |
| `feedback-contract.ts` | 70/70 = 100% | 私有反馈契约 |
| `agent-review-contract.ts` | 206/206 = 100% | 候选审核契约 |
| `FeedbackButton.tsx` | 80/80 = 100% | 反馈交互 |
| `metrics-contract.ts` | 163/164 = 99.39% | 保留导出大小保护分支，不删防御代码 |
| 全前端 | 1847/2032 = 90.89% | 比本轮前 1753 多 94 个命中，分母不变 |

行覆盖 1329/1409 = 94.32%，语句 1819/1964 = 92.61%。当前仍有 185 个未命中分支结果，保留准确文件/行号，未排除文件或缩小分母：[覆盖摘要](../.cache/manual3-acceptance-20261016/frontend-complete/coverage/coverage-summary.json)、[原始覆盖](../.cache/manual3-acceptance-20261016/frontend-complete/coverage/coverage-final.json)、[缺口清单](../.cache/manual3-acceptance-20261016/frontend-gap-inventory.json)。

## 尚未签收的范围

1. 原 100% 新路径覆盖目标仍未完成。当前全范围前端有 185、后端有 914 个未命中分支结果；这些是缺口库存，不冒充原计划“新关键路径”的精确分母或缺陷数量。后续应对照原目标补足可达边界，不删防御代码、不改分母。
2. A01/A03 的主仓库完整可克隆提交、远程 CI、其他操作系统/Python 矩阵仍缺证据。本机测试无法替代这些要求。
3. A42 正式语料来源、独立人工审核、holdout seal 仍未通过；真实免费模型资格、真实评测与 Agent 轨迹、8 个参考任务和人审依用户回复保留待验。
4. 生产写入者/停写盘点、上线和公开交付未执行。

业务代码未变，所以此前同一生产版本的 35 项 Edge UI、103 项测试框架和 3 项 API 冒烟保留其原证据，没有为本轮纯测试修改重复构建或启动服务。旧的本地工程已通过 47 项不因新增测试数自动增加；A46/A60 仍受覆盖和总体交付边界限制。

正式 60 项的整体状态仍为：限定本地工程通过 47、未通过 1（A42）、进行中但已停止 2（A46/A60）、未开始 3（A50/A53/A59）、待核实 7（A01/A03/A04/A10/A54/A56/A58）。这不是完成率。A54/A56 的当前浏览器机械链路已由此前 35 项 Edge 验证，仍欠真实人审；下方历史快照表格中“当前浏览器未跑”的文字按最新覆盖说明读取。

建议继续的清单：本地先按精确缺口补充关键路径测试；A01/A03 等完整 Git 可克隆版本与实际 CI/平台矩阵；A10/A42/A46/A50/A53/A54/A56 等免费资格、正式语料、人审及真实运行材料；A04/A58 等真实停写与恢复证据；A59/A60 等单独上线/公开授权。没有材料的项目继续待验，不制造替代证明。

## 收尾保护

本轮共新增 **122 项测试（120 前端、2 后端）**。相对前次 407 项输入，32 个旧测试文件改变、6 个新测试文件加入，形成 **413 项显式输入**；生产输入未变。最终 SHA 核验零漂移，两个阶段备份及哈希链均核实：[输入身份](../.cache/manual3-acceptance-20261016/final-source-identity.json)、[修改归属核对](../.cache/manual3-acceptance-20261016/source-change-audit.json)。前端 XML 的两组既有参数化用例共用显示名，按单次 XML 中的 584 个 testcase 计数；未用显示名去重或混合多次运行。

11:50:10 核对：分支/HEAD 未变，工作树仍有 598 项状态记录（45 个已跟踪修改、553 个未跟踪文件），暂存区为空；这些包含原有升级修改，不都归本轮。未提交、切换或覆盖工作树。原 239 个运行文件摘要仍为 `d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a`，Git index 摘要仍为 `45c635efdd2844f5a8dac3cf3b6b7fbb4caa6a54a2f247f3f8cc902c4ca275f5`。[运行数据保护](../.cache/d18/manual3-after.json)、[最终 Git/进程/端口核对](../.cache/manual3-acceptance-20261016/final-verification.json)。

无活动项目测试进程，18080/18081 无监听，旧自动化配置不存在。本轮已停止，不自动接续，不开启 Loop、heartbeat 或定时任务。整体最终验收尚未完成。
