# 2026-10-16 游戏页面与难度边界补验

用户授权继续本地验收。本轮已结束，没有自动续跑、Loop、heartbeat、调度、真实模型、人审、生产或公开操作。

## 本轮新增与验证

新增 3 文件、**26 项测试**，未修改业务代码或既有 418 项输入：

| 文件 | 用例 | 主要验收内容 |
| --- | ---: | --- |
| `src/app/game/[id]/game-view-boundaries.test.tsx` | 20 | 不限次/较大预算、复盘键盘与关闭、未配对历史、绑定反馈、旧评分标签、导航、限流/认证、解除暂停、无效提交、显式放弃恢复后另开、已结束局重开、次数耗尽揭晓失败、缺失路由 |
| `src/app/difficulty/[id]/difficulty-view-boundaries.test.tsx` | 4 | null/省略限额的合法目录显示无限、缺失路由、旧请求迟到失败隔离 |
| `src/app/admin/feedback/default-api-origin.test.tsx` | 2 | 未配置 API 地址时使用 localhost:8000，显式空字符串时保留相对路径；管理反馈与统计一致 |

复用真实 GameController、恢复日志、公共解码和组件，仅替换网络/导航等测试边界；没有注入私有控制器状态。第一轮有 2 项新增测试失败及 1 个关联未处理错误：导航 mock 缺少 FeedbackButton 使用的 usePathname，且错误预期缺失路由仍会发请求。补齐 mock，按实际请求前拒绝行为修正断言后，20 项通过。原失败日志保留，不冒称生产缺陷 RED/GREEN。[原日志](../.cache/manual6-acceptance-20261016/game.log)、[修正后 XML](../.cache/manual6-acceptance-20261016/game-fixed.xml)。

游戏补验后的中间全量为 711 项通过；增加难度/地址 6 项后重新完整执行，最终以 `closed/` 为准：北京时间 **12:19:14–12:19:53**，**43 文件、717 项通过、0 失败/错误**，类型检查和 3 个新增文件 lint 均退出 0 且无警告。[最终 XML](../.cache/manual6-acceptance-20261016/closed/frontend.xml)、[日志](../.cache/manual6-acceptance-20261016/closed/frontend.log)、[各步终态](../.cache/manual6-acceptance-20261016/closed/exits.json)。

## 相同范围覆盖

使用原绑定配置；不改生产文件、不排除未测文件，分支分母仍 2032。

| 范围 | 分支命中 |
| --- | ---: |
| 游戏页面 | 151/155 = 97.42%（本轮新增19命中） |
| 难度页面 | 29/29 = 100%（本轮新增4命中） |
| 全前端 | **2005/2032 = 98.67%**（本轮新增25命中） |

行 1398/1409 = 99.21%，语句 1931/1964 = 98.31%，函数 458/465 = 98.49%。[覆盖摘要](../.cache/manual6-acceptance-20261016/closed/coverage/coverage-summary.json)、[原始覆盖](../.cache/manual6-acceptance-20261016/closed/coverage/coverage-final.json)。

## 剩余清单与限制

前端仍有 **27 个未命中分支结果**：[准确位置清单](../.cache/manual6-acceptance-20261016/closed-frontend-gap-inventory.json)。

| 模块 | 未命中 |
| --- | ---: |
| 管理反馈页面 | 6 |
| AgentReviewPanel | 6 |
| MetricsPanel | 5 |
| 游戏页面 | 4 |
| game-controller | 3 |
| SiteGate | 2 |
| metrics-contract | 1 |

游戏页面剩余位于 133、246、305、308 行。305/308 是 coverageValue 为空的回退，但当前 `normalizeEvaluationDisplay` 的合法旧版/新版结果都返回数字；本轮未绕过校验制造 null。246 是没有 session 却有消息时的回退，而消息列表来自该 session。133 的 syncing 条件仍保留为未命中，未据静态名称豁免。其他模块未命中同样保留，不能因接近100%就签收原100%新关键路径目标。

后续应先核对这27项的可达性和原目标映射，再决定需要补充的有效测试；后端还有上轮完整测量的914个未命中分支结果。它们不是缺陷数量，也不是原新关键路径的精确分母。不能删防御代码、缩小分母或伪造私有状态凑覆盖率。

后端输入未变，本轮未重复执行后端、构建、Edge UI、测试框架和 API 冒烟。上轮严格资源警告模式单次完整 **3030 PASS/14 SKIP**、原110生产文件 **3118/4032 = 77.33%** 仍是历史证据，不写成本轮新跑。[后端报告](local-acceptance-resource-cleanup-2026-10-16.md)。

正式60项分布不变：限定本地工程通过47、未通过1、进行中2、未开始3、待核实7。真实免费资格、正式语料、人审、真实三系统/Agent轨迹/8参考任务、Git可克隆版本、CI/其他平台、生产停写恢复和单独上线/公开授权均保留待验。

## 保护与停止

最终 **421 项输入**：原418项零漂移，仅新增3测试文件。[最终输入身份](../.cache/manual6-acceptance-20261016/final-source-identity.json)。分支 `codex/ts02-storage-foundation`、HEAD `c5765b68cb251a7c566e76e2887d335d6ed6b285` 未变。原239运行文件及HEAD/index前后核对不变：[开始保护](../.cache/d18/manual6-before.json)、[最终保护](../.cache/d18/manual6-closed-after.json)。未提交、切分支、覆盖旧修改或触碰生产。

本轮测试已结束，不自动接续；整体最终验收未完成。
