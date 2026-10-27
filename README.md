# Turtle Soup · 海龟汤 AI 主持人

玩家通过提问还原隐藏剧情。玩法目标是让主持人回答“是 / 不是 / 是也不是 / 算是 / 与此无关”，并提供难度、会话恢复、揭晓和反馈审核。

这是一个 **Python + AI 应用项目**：FastAPI 后端、Next.js 前端、确定性规则与词面检索、免费模型兜底，以及受控反馈修复 Agent。核心工程包括幂等会话、版本化规则、反馈审计、候选审核、完整分母评测、发布回滚和数据恢复。

## 当前发布状态（2026-10-18）

**2026-10-27 更新：** 仓库已纳入 10 月 25 日上线的后台兼容、请求恢复、历史反馈及安全依赖修复；当前发行版本为 `20261025-184511-repairs`。最新结果见 [发布记录](docs/deployment-2026-10-25.md)、[修复记录](docs/repair-2026-10-25.md) 和 [仓库同步与清理](docs/repository-maintenance-2026-10-27.md)，求职展示请使用 [当前简历稿](RESUME.md)。下方 10 月 18 日成绩是对应历史版本的记录，不代表本次重新运行了整套门禁。

- 在线演示：<http://47.97.33.174/>（需要项目访问口令；当前按原部署方式使用 HTTP IP）。
- 模型：智谱 `glm-4-flash-250414`，生产真实兜底调用已验证；免费资格以供应商当前政策为准。
- 质量：110 条人工确认题的同模型、同预算对比中，纯 LLM 62.73%、冻结旧系统 50.91%、当前系统 79.09%。79.09% 是修复后同集回归成绩，不冒充新的独立盲测。
- 最终门禁：后端及离线评测 3107 通过、14 个环境相关用例明确跳过；前端 722、测试框架 103、API 冒烟 3、浏览器流程 35 全部通过，TypeScript 与 ESLint 通过。
- 运维：生产 schema 5 迁移、停写备份恢复、恢复副本启动、旧 release 回退与重新前滚均已演练；站点口令和管理员口令分离，运行数据与发布目录分离。
- 更新规则：正在玩的对局固定使用开局版本，新对局使用最新发布版本。反馈审核通过不会自动改答案，候选仍须真人确认并单独发布；生产自动修复 Agent 当前关闭。

完整验收边界见[最终验收收尾](ACCEPTANCE_CLOSEOUT_2026-10-18.md)。历史 TS 状态文档保留各阶段证据，不代表当前最终状态。

## 当前实现与边界

当前正式验收为 56/60。剩余项目是一次真人语义审核与发布、可选的域名/TLS，以及后续个人讲解学习；详情以[验收进度快照](ACCEPTANCE_PROGRESS.md)为准。

- 主持人判定链：特殊剧情/流程 → 来源绑定的整句或全分句规则（含精确元数据）→ 是否问法提醒 → 完整汤底和有界证据/历史的模型兜底；模糊相似度和宽正则不直接决定答案。
- SQLite 保存会话、消息、版本化基线、反馈、审计、Agent 任务和规则发布记录；必要业务审计同事务、HTTP 尝试独立有界保存，见[请求审计](docs/request-audit.md)。生产迁移、停写恢复和 release 回滚已验证，私密 Trace 与真实玩家数据不进入 Git。
- `create_app(Settings, model=..., soups=...)` 支持应用级数据目录、题库、模型、缓存和限流器隔离；初始化与资源释放由应用启动/关闭管理。
- 默认测试使用临时 SQLite 和固定输出的 FakeModel，不读取真实 dotenv，不允许真实模型/生产站点请求。
- 110 条正式题已完成人工确认、去重和封存；同一题集下的纯 LLM、冻结旧系统和当前系统真实比较已完成，见[评测运行器](docs/evaluation-runner.md)和[最终验收收尾](ACCEPTANCE_CLOSEOUT_2026-10-18.md)。
- 部署采用不可变 release、独立数据目录、systemd 服务和 Nginx 反向代理；当前未配置域名与 TLS。

整轮事务与请求恢复、分窗口限流、模型准入、语义规则、版本化缓存、严格事实覆盖、页面恢复和规则发布均有自动化证据。生产调用和恢复已验证；模型 79.09% 仍属于同集回归结果，不能解释为未知题上的泛化准确率。

## 技术栈

| 层 | 当前选型 |
| --- | --- |
| 前端 | Next.js 16 / React 19 / TypeScript / Tailwind CSS |
| 后端 | Python 3.11–3.13 / FastAPI / Pydantic / LangChain |
| 模型 | 保留现有供应商配置；测试使用 FakeModel，无外部模型费用 |
| 存储 | SQLite 001不可变基线、002反馈/审计、显式003 Agent任务/步骤/候选、显式004私有统计；默认启动要求002，不自动003/004，默认Agent关闭；TS15人工发布同事务与提交前新鲜度校验已完成本地审查修复 |
| 工程验证 | pytest / Vitest / API 冒烟与独立真实浏览器 UI 门禁 / GitHub Actions 配置 |

0 付费是项目约束，不是供应商永久免费的承诺。真实调用前须核实账户、模型和当天规则，不能默认免费额度覆盖所有模型与操作。

## 首次运行：不需要模型密钥

从仓库根目录运行。先准备 Node **22.17.0**、Python **3.11–3.13**、uv **0.12.3**。安装下载需要网络；随后测试不需要联网或安装浏览器。

PowerShell：

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path (Get-Location) 'backend/.venv-ts01'
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.cache/uv'
uv sync --project backend --locked --group dev --python python --no-managed-python
npm ci --ignore-scripts
npm run test:offline
npm run typecheck
```

Linux/macOS shell：

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/backend/.venv-ts01"
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --project backend --locked --group dev --python python --no-managed-python
npm ci --ignore-scripts
npm run test:offline
npm run typecheck
```

`pyproject.toml + uv.lock` 和 `package.json + package-lock.json` 是安装依据；`requirements.txt` 仅保留旧 pip 部署兼容性，不保证传递依赖复现。不要复用本机损坏的旧 `.venv`。

测试步骤、报错处理和真实模型 opt-in 见 [离线测试操作指南](docs/testing.md)。公开仓库的远程 CI 已在 Ubuntu/Windows 与 Python 3.11/3.12/3.13 矩阵通过，见 [GitHub Actions 运行记录](https://github.com/VVR823/turtle-soup/actions/runs/39137676612)。

## 本地开发与部署

从仓库根目录使用 `python scripts/run-backend.py` 启动后端，前端使用 `npm run dev`。后端入口固定一个 worker、loopback 监听，并关闭 Uvicorn 对代理头的提前改写；可信代理统一由应用配置决定。直接从 backend 目录运行时必须使用 `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers`，不能省略最后一项。它们不是隔离测试入口，启动后端会加载运行配置、初始化数据并可能调用真实模型；`python scripts/run-backend.py --check` 只检查配置，不启动服务，也不证明真实部署安全。请先阅读 [测试运行时参考](docs/test-runtime.md)，明确数据目录和配置边界。

前端通过 `NEXT_PUBLIC_API_BASE` 指定后端地址，站点口令使用 `X-Site-Token`，管理员口令使用独立的 `X-Admin-Token`。后端供应商密钥不应暴露给浏览器。

[旧部署说明](deploy/README.md)仅作历史参考，不应直接覆盖现网。当前生产发布已使用不可变 release 和独立数据目录完成迁移、恢复及回滚验证；操作原理见[本地隔离发布与恢复指南](docs/howto-local-release.md)。站点口令和管理口令必须使用不同值，相同非空配置会拒绝启动。当前 HTTP IP 能正常使用，但公开长期运行建议配置域名与免费 TLS 证书。

## 导读

- [求职项目展示](docs/showcase.md)与[简历草稿/数字证据](docs/resume-evidence.md)：AI应用主线、Agent差异和Python工程；区分AI协作及本人掌握，旧数字不替代真实成绩。
- [公开前有限盘点](docs/publication-preflight.md)：两个产物完整性、Git元数据与缺少的内容/许可/视频门禁；当前不能自动上传。
- [成品学习路线](docs/learning/project-learning-map.md)、[九模块学习卡](docs/learning/core-module-cards.md)与[安全独立练习](docs/learning/practice-checklist.md)：从一次提问到Agent/恢复，连接真实失败、源码和原生测试；材料存在不代表本人已学会，命令核验/材料审查状态以TS18 ledger为准。
- [TS17唯一审查修复](docs/ts17-review-resolution.md)与[冻结身份恢复矩阵](docs/release-recovery.md)：所有裁定和未知格保留，不将绿色本地测试当生产恢复授权。

- [TS17本地发布/恢复指南](docs/howto-local-release.md)与[资源测量参考](docs/ts17-resource-measurements.md)：合成规则命中/兜底、100模型名额申请、实际审计/trace增长与关闭已测；不是生产容量、真实模型成绩或部署通过。

- [私有统计参考](docs/metrics-reference.md)、[操作指南](docs/metrics-howto.md)、[大白话口径](docs/metrics-explanation.md)与[TS16状态](docs/ts16-status.md)：显式004、手动私有汇总/完整导出及200/1000/5000合成测量已实跑，唯一工程审查/一次修复与最终门禁已结束；原后续发布回归失败统计来源仍欠，不代表真实用户或AI修复正确率。

- [How to 运行离线测试](docs/testing.md)：安装、单项测试、失败排查、哈希检查。
- [测试运行时参考](docs/test-runtime.md)：工厂接口、配置、数据与网络边界。
- [为什么采用应用级隔离](docs/adr/0001-test-isolation.md)：设计取舍和 Windows 子进程问题。
- [TS-01 实施状态](docs/ts01-status.md)：实测证据、未验收项目和发布阻断项。
- [TS-02 实施状态](docs/ts02-status.md)与[隔离迁移指南](docs/migrations.md)：已有旧库不会在启动时自动升级；未执行生产迁移。
- [TS-07 评分状态](docs/ts07-status.md)：严格事实覆盖、null 还原、剧情分离、旧分数和真实验证边界。
- [TS-08 页面恢复状态](docs/ts08-status.md)：初始化/重复点击/断网刷新/揭晓恢复、审查修复与本地浏览器证据及保留边界。
- [为什么断网后要同步原请求](docs/game-recovery.md)：恢复原理与取舍，适合开始学习这个项目。
- [独立评测数据操作](docs/evaluation-data.md)与[TS11状态](docs/ts11-status.md)：110私有AI草案、人工审核、关联隔离、完整封存与禁止holdout回填；不是已测得的模型准确率。
- [完整分母评测](docs/evaluation-runner.md)与[TS12状态](docs/ts12-status.md)：真实宿主的离线Fake驱动、完整失败/未知用量、全重复/同预算比较、安全旧入口；本地审查修复完成，真实质量结论null。
- [Agent工具接口](docs/agent-tools-reference.md)与[大白话解释](docs/agent-tools-explanation.md)：TS13五工具、权限/幂等、固定合成回归与未批准候选预览已完成本地工程验收；真实独立题集/模型质量仍待定。
- [Agent循环参考](docs/agent-loop-reference.md)、[大白话解释](docs/agent-loop-explanation.md)、[本地复现](docs/agent-loop-howto.md)与[TS14状态](docs/ts14-status.md)：10模型/8工具/180秒、断点/取消/独立心跳、管理员最小接口、8条声明合成任务报告；本地审查/一次修复及最终门禁完成，较小审计分类问题留TS17，不冒充真实人审或自动上线。
- [候选审核接口](docs/candidate-review-reference.md)、[为什么AI建议不能直接上线](docs/candidate-review-explanation.md)与[TS15状态](docs/ts15-status.md)：真实轮次反馈、手动脱敏、任务、原问题/前文与完整证据、单独批准/发布、回滚；唯一阶段审查与一次修复回归已完成，合成浏览器验证不是人审质量或上线证明。

```text
backend/app/main.py          应用工厂、生命周期、API
backend/app/runtime.py       应用级状态与请求上下文
backend/app/ai_host.py       原主持人判定链，模型 transport 按应用持有
backend/app/db.py            会话存储与题库初始化
backend/app/testing.py       固定输出 FakeModel，不是质量裁判
backend/testing/guards.py   pytest 内容访问与网络防误用保护
backend/tests/              后端单元/契约/隔离测试
backend/eval/               独立数据/审核/封存/完整评测/比较；固定Fake CLI，不是Agent工具
backend/eval/tests/         默认数据合同门禁；合成人工声明不是真人审核
src/lib/api.test.ts          前端 API 客户端与本地存储单元测试
tests/e2e/                  隔离后端的 API 冒烟，尚非浏览器 UI 测试
tests/ui/                   另行运行的自有 Edge/Playwright 页面恢复门禁
scripts/                    本地测试入口和哈希验证
.github/workflows/          默认无真实模型凭据的测试流水线配置
```
