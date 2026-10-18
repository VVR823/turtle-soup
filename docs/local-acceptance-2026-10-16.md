# 2026-10-16 本地剩余验收

用户再次授权继续，并明确“尚无材料，先完成本地项目”。真实免费模型、人工参考答案与审核记录不由代理补造；上线和公开发布不在本轮执行范围。禁止自动续跑的长期规则保持有效。

04:32 最终补充：下面的 406 项身份和 3026/14 是连接警告修复前的阶段证据，保留原记录不改写。之后已实际定位并修复一类迁移测试连接泄漏，新增 2 项后端回归；当前身份为 **407 项**（仅旧测试文件 `backend/tests/test_agent_migrations.py` 改变，新增 3 个前端测试文件和 1 个后端测试文件），业务代码仍未变。完整前端 464 通过；后端完整运行＋历史包补验＋受影响模块复验聚合为 **3028 通过、14 跳过**，不是单次最新全跑。资源警告整体仍未清零。

## 已完成的本地补测

新增 3 个测试文件、47 项用例，未改业务代码：

- `src/components/SiteGate.boundaries.test.tsx`：15 项，覆盖已存口令验证、存储拒绝、重试、重复提交、跨标签页口令变化和卸载后迟到响应。
- `src/lib/game-recovery-ownership.test.ts`：9 项，覆盖创建/问答/揭晓/重开时恢复日志清除冲突、迟到结果、取消后唤醒及已完成问答发现规则停版后的原 ID 恢复。
- `src/lib/catalog-boundaries.test.ts`：23 项，覆盖公共目录字段边界、非法难度/限额、整批拒绝和私有字段排除。

这些是既有行为的验收补测，均直接通过，不冒称发现并修复了生产缺陷或完成新业务 RED/GREEN。

最终完整前端 30 文件、464 项通过；类型检查和三个新增文件的 lint 均退出 0。[完整 XML](../.cache/manual2-acceptance-20261016/closed-frontend.xml)、[运行回执](../.cache/manual2-acceptance-20261016/closed-frontend-exits.json)、[覆盖摘要](../.cache/manual2-acceptance-20261016/closed-frontend-coverage/coverage-summary.json)。

| 生产模块 | 行覆盖 | 分支覆盖 |
| --- | ---: | ---: |
| 公共目录 catalog | 100% | 56/56 = 100% |
| 恢复日志 game-journal | 100% | 68/68 = 100% |
| SiteGate | 100% | 55/57 = 96.49% |
| game-controller | 100% | 231/234 = 98.71% |
| 全前端 | 1302/1409 = 92.40% | 1753/2032 = 86.26% |

全前端分支比旧 C27 的 1726/2032 增加 27 个命中，分母不变。分支并非全部达到 100%；279 个未命中仍保留，不删防御代码、不排除未测文件、不把这些比例冒称原目标已完成。

## 原测试计划第 6 节的入口注释核对

按原文的六类入口逐项读取，所需说明已经存在；本次没有追加生产注释或重写实现。

| 原要求 | 实际位置 |
| --- | --- |
| 会话预留/提交/过期/幂等 | `backend/app/game_store.py:226`、291、333 |
| 模型截止/取消/实际占位 | `backend/app/model_gateway.py:1`、65、72、100 |
| Agent claim/心跳/预算/恢复 | `backend/app/agents/worker.py:101` 及 `backend/app/agents/store.py` |
| draft→report→candidate→人审 | `backend/app/candidate_review.py:464` |
| 批准后的事务/CAS | `backend/app/candidate_review.py:483` 和 `backend/app/rule_publication.py` |
| E2E 自有前后端/网络边界 | `tests/ui/fixtures.ts:7` |

上述 7 个文件与旧注释核验回执的源码哈希逐个一致。旧 `.cache/a46/comments-current-identity.json` 明确记录 6 个变更文件的可执行语法未变；模型网关说明原已存在。本节只签明确列出的注释要求，不把它当成 100% 分支覆盖证明。

## 独立 Python 环境完整后端验收

使用既有 A01 独立锁定安装环境 `.cache/a01/checkout-v2-LZkw8i/checkout/backend/.venv-ts01`，不重复安装、不复用主环境。其 304 个后端与根 pytest 守卫输入和当前主仓库逐字节一致；该独立 Git 验证快照开始时干净。原回执已验证 54 个锁定包及模块来源。

本轮在该独立目录完整执行后端，并采集分支覆盖：2026-10-16 04:00:18–04:23:59（北京时间），退出 0；3040 项中 3025 通过、15 跳过、0 失败/错误。保留 546 条 ResourceWarning，均为未关闭数据库连接提示；它们的具体分配来源尚未逐一定位，不能声称资源警告已清零。

相对主环境多跳过的唯一项目是历史 schema-4 发布包兼容测试。原因已经定位为独立 checkout 的 `.cache` 没有该历史产物，不是运行代码失败。将主项目现有产物按固定 manifest SHA256 `ab61062c21dc29eaeca16234ed459415815eff10b1bb298922aaf73c2220fa85` 逐一核验 78 文件后，复制到独立目录的测试缓存；未复制运行数据、改写源码、重建或替换原发布包。04:24:57–04:25:00 单独运行原用例，1 通过、0 跳过，旧产物哈希不变。

因此本轮独立环境的**完整运行加单项补验聚合**为 3026 通过、14 跳过，不把原完整 XML 的 3025/15 改成 3026/14，不伪称一次无跳过重跑。余下 14 项仍为 7 项显式真实模型 opt-in、7 项 Windows symlink/Unix socket 限制。

[启动记录及实际命令](../.cache/manual2-acceptance-20261016/clean-backend-started.json)、[原始日志](../.cache/manual2-acceptance-20261016/clean-backend.log)、[304 项输入](../.cache/manual2-acceptance-20261016/backend-inputs.json)。

[完整运行终态](../.cache/manual2-acceptance-20261016/clean-backend-exit.json)、[原始 3040 项 XML](../.cache/manual2-acceptance-20261016/clean-backend.xml)、[单项补验及产物核验](../.cache/manual2-acceptance-20261016/clean-compat-exit.json)、[单项 XML](../.cache/manual2-acceptance-20261016/clean-compat.xml)、[本次实际模块和 54 包来源](../.cache/manual2-acceptance-20261016/python-environment.json)。包清单与原锁定安装完全一致；独立验证仓库收尾 Git 状态仍干净。

后端原始 coverage 包含 143 个文件，其中包含 eval 测试代码。为与旧测量严格比较，按旧报告的原 110 个生产文件逐一匹配，未漏文件，语句分母仍 12672、分支分母仍 4032：语句 11319/12672 = 89.32%，分支 3122/4032 = 77.43%，剩余 910 个分支结果。该结果是本轮完整运行测量，不把小幅变化归因于本轮前端补测，不把测试代码混入生产覆盖率。[同范围生产覆盖与缺口](../.cache/manual2-acceptance-20261016/backend-production-coverage.json)、[原始覆盖](../.cache/manual2-acceptance-20261016/clean-backend-coverage.json)。

## 收尾与尚需本地处理的事项

04:26:46 核验：原 403 项输入零漂移，仅新增上述 3 个测试文件，形成 406 项显式源码/测试身份；原 239 运行文件摘要、主 HEAD、Git 索引不变；无暂存变更、无活动项目测试进程、无自动续跑配置。[最终核对记录](../.cache/manual2-acceptance-20261016/final-verification.json)、[运行数据保护](../.cache/d18/manual2-20261016-after.json)。

原计划第 6 节的具体入口注释要求已核实；以下本地风险仍未签收，整体并未全部完成：

1. 原 100% 新路径覆盖目标仍未达成。前端 279、后端 910 个未命中分支有准确文件/行号：[前端缺口清单](../.cache/manual2-acceptance-20261016/frontend-gap-inventory.json)、上述后端生产覆盖。不能仅凭“防御分支”名称判定无需测试。
2. 546 条 SQLite ResourceWarning 的分配来源与清理仍需专门定位；本轮没有关闭警告、修改警告级别或猜测全部属于测试夹具。
3. 当前完整升级仍未进入主仓库提交；独立环境虽已验证相同后端，当前整仓可克隆 Git 版本和远程 CI/其他 OS/Python 矩阵仍无完整证据。历史产物测试另有需要保全的固定测试包依赖，不能假称一个空缓存 clone 自带该包。

本轮执行已结束，不留运行任务或后续调度。真实模型/人审事项依用户“尚无材料，先完成本地项目”的回复继续保留待验。

## 明确保留的边界

- 主仓库没有提交本轮或既有升级修改，也没有配置 remote。独立验证提交不是主仓库可公开 clone 的当前提交；A01/A03 不能据此整项签收。
- 新前端测试未改变生产输入；上一轮当前生产版本 35 项 Edge、103 项测试框架、3 项 API 冒烟的结果保留，不重复构建或重跑它们。
- 原 100% 新路径目标未完成；真实人审、免费资格、真实三系统评测/Agent 轨迹、8 人工参考任务、CI/其他平台、生产和公开交付仍待验。
- 本轮不会创建调度、Loop、heartbeat、自动重试或下一轮任务。

## SQLite 测试连接泄漏的真实 RED → GREEN

对原完整运行首类警告启用 tracemalloc 后，直接分配栈定位到 `test_agent_migrations.py:105`：`with sqlite3.connect(...) as conn` 只管理事务，不负责关闭连接。[分配栈探针](../.cache/manual2-acceptance-20261016/resource-probe.log)。该证据只定位这一类，不能据此推断全部 546 条警告的来源。

新增 `backend/tests/test_agent_migration_connections.py`，直接调用原漂移夹具，在函数返回后查询捕获连接，要求抛出“数据库已关闭”的 ProgrammingError。原代码实际 2 项失败：连接仍可查询，[原生 RED](../.cache/manual2-acceptance-20261016/connections-red.xml)。

最小修复仅在 `test_agent_migrations.py` 的 11 处 SQLite 上下文外围加 `contextlib.closing`，保留原内层 `conn` 事务提交/回滚语义，未修改业务迁移或数据库断言。随后使用 A01 独立解释器在当前主仓库重验原 38 项及新增 2 项，**40 项通过**，同时启用 `-W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning`，[GREEN XML](../.cache/manual2-acceptance-20261016/connections-green.xml)、[实际日志及命令参数](../.cache/manual2-acceptance-20261016/connections-green.log)。没有关闭或降低警告级别。

最终聚合逐项核对原 38 个测试 ID 一致，以当前模块 40 项替换旧模块 38 项，故完整验收集合变为 3042 项：3028 通过、14 明确跳过，不重复计入 38 个旧用例。[精确聚合边界](../.cache/manual2-acceptance-20261016/accepted-backend-aggregate.json)。

前述生产覆盖是修复前完整运行测量；生产文件未变，但修复测试连接后没有再次测量全量覆盖或警告数量，不能虚构“546 已降到某个数字”。本轮共新增 **49 项测试**，其余未定位的连接警告和原 100% 路径目标继续保留待办。

04:32 收尾：原 239 运行文件、主 HEAD、索引均与原基线一致；没有暂存修改或活动项目测试进程。[407 项最终输入](../.cache/manual2-acceptance-20261016/final-source-identity.json)、[最终核对](../.cache/manual2-acceptance-20261016/connections-final-verification.json)、[最终数据保护](../.cache/d18/manual2-connections-closed-after.json)。本轮已停止，不自动接续。
