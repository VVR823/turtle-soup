# 2026-10-16 用户授权的手动验收

用户明确授权本轮继续验收，同时永久禁止自动续跑。本轮没有创建 Loop、heartbeat 或定时任务；结束后停止。

项目：`D:\CODE\turtle-soup`；分支：`codex/ts02-storage-foundation`；HEAD：`c5765b68cb251a7c566e76e2887d335d6ed6b285`。
源码/测试身份：403 文件，`52d0d3559ee499df8cfceb4c3f1eb5944d0d4c867f955cca88b7a3313ad67545`，本轮启动时哈希一致。

## 已完成

- `node scripts/ui-e2e-server.mjs`：35 项本机 Edge 浏览器验收通过，退出 0；自有前后端 EOF 清理退出 0。使用原受控入口新建 packaging-disabled UI 副本 `.cache/ts07-frontend-n3OXcV`，未改动或重建 C27 standalone 发布包。
- `npm run typecheck`：退出 0。
- `npm run lint`：全仓入口退出 0。
- Windows PowerShell 原保护入口确认原 239 文件摘要、HEAD、Git 索引均与旧基线一致。第一次在 PowerShell 7 下摘要校验失败；随后用原记录使用的 Windows PowerShell 核验通过，未修改基线或绕过校验。该保护核验完成时 UI 已启动，不能声称它早于所有新测试。

## 证据

- [本轮日志目录](../.cache/manual-acceptance-20261016/)
- [浏览器日志](../.cache/manual-acceptance-20261016/ui.log)
- [浏览器终态](../.cache/manual-acceptance-20261016/ui-exit.json)
- [浏览器 XML](../.cache/ui-runs/92c455de-42f8-46a5-8a24-dd1378211466/junit.xml)
- [类型与 lint 回执](../.cache/manual-acceptance-20261016/static-exits.json)
- [运行数据保护回执](../.cache/d18/manual-20261016-before.json)

## 统一离线终态

本轮从 2026-10-16 03:36:57 至 03:57:10（北京时间）运行，退出 0，无自动重试。实际命令是 `npm run test:offline -- --junitxml=.cache/manual-acceptance-20261016/backend.xml`。该附加参数没有传到后端 pytest；后端实际 XML 输出仍为默认 `.cache/ts01/pytest.xml`，终态后复制到本轮目录的 `backend.xml`，已独立解析核对。旧默认 XML 已在覆盖前另存 `prior-ts01-pytest.xml`。后续直接使用原 `npm run test:offline` 即可，避免无效附加参数。

| 检查 | 结果 |
| --- | --- |
| 后端同一次完整执行 | 3040 项：3026 通过、14 跳过、0 失败、0 错误；1180.57 秒 |
| 前端 | 27 文件、417 项通过 |
| 测试框架 | 103 项通过，0 失败/跳过 |
| API 冒烟 | 3 项通过，服务正常关闭 |
| 浏览器 | 35 项通过，0 失败/错误/跳过，两个自有服务正常关闭 |
| 类型 / 全仓 lint | 均退出 0 |

- [统一入口日志](../.cache/manual-acceptance-20261016/offline.log)、[终态回执](../.cache/manual-acceptance-20261016/offline-exit.json)、[后端 XML 副本](../.cache/manual-acceptance-20261016/backend.xml)。这是本轮实际单次完整后端执行，不再仅依赖旧分批聚合证据。
- 后端保留 1 条 `PytestCacheWarning`：原 `.pytest_cache` 写入权限不足。测试及 XML 已正常完成；没有为消除警告修改权限、删除缓存或重跑。另有 Node 颜色环境提示，原日志保留。
- 14 个跳过项仍不是通过：7 项需要显式真实模型启用，7 项为本机 symlink/Unix socket 能力限制。具体节点及原因见 XML；不能以本机结果认证其他平台或真实模型。
- 03:57:25 收尾核对：403 源码/测试哈希零漂移；原 239 运行文件摘要、HEAD 和索引与旧基线一致；无匹配本项目的活动测试进程；原自动化文件仍不存在。[收尾保护回执](../.cache/d18/manual-20261016-after.json)。

## 更新后的 A01–A60 状态

仅补齐当前版本本地工程验收范围：A30–A33 及 A36 原因当前浏览器/全入口未执行而保留的缺口已完成。A54/A56 的当前浏览器证据也已补齐，但真实语义人审仍缺，不升级整项状态。

| 状态 | 数量 | 项目 |
| --- | ---: | --- |
| 已通过（限定本地工程范围） | 47 | 原快照 42 项，加 A30、A31、A32、A33、A36 |
| 未通过 | 1 | A42：来源/独立人审/正式 holdout 未完成 |
| 进行中，现已停止 | 2 | A46、A60 |
| 未开始 | 3 | A50、A53、A59 |
| 待核实 | 7 | A01、A03、A04、A10、A54、A56、A58 |

这是验收项分布，不是项目完成率。C/IR/阶段原映射继续沿用根快照；本轮只补当前浏览器、完整离线入口、类型和 lint 证据，不外推真实模型、人审或生产通过。

## 尚未签收

原新增关键路径 100% 覆盖及注释、新环境完整后端与远程 CI/平台矩阵、真实免费模型资格、110 条草案的独立人审及正式 holdout、真实三系统比较、真实 Agent 轨迹与 8 个人工参考任务、生产停写/部署、公开交付和本人学习签收仍按根快照保留。浏览器通过不替代真实人审或上线授权。

建议后续顺序：关键路径覆盖/注释；新环境及 CI；真实免费资格与人工语料封存；真实对比/Agent/人工参考任务；有单独授权后再做生产及公开交付。当前主仓库未配置 Git remote，远程 CI 无可核运行记录。

本轮本地门禁完成，整体最终验收仍未完成。现已停止，没有运行中的测试、自动续跑、Loop 或定时任务；只能由用户下一条明确指令启动后续工作。没有修改业务源码、提交 Git、上线或公开上传。

[最终核对记录及日志哈希](../.cache/manual-acceptance-20261016/final-verification.json)。
