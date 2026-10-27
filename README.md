# Turtle Soup · 海龟汤 AI 主持人

一个可以自己玩的海龟汤网站：选一道汤，向主持人提问，一点点还原故事。主持人结合题目事实、规则和模型作答，正常回答限定为“是 / 不是 / 是也不是 / 算是 / 与此无关”。

[在线演示](http://47.97.33.174/) · [项目展示](docs/showcase.md) · [本地运行与测试](docs/testing.md) · [技术文档](docs/README.md)

演示站保留访问口令，由项目所有者提供或现场输入。管理口令和模型密钥不公开。

## 玩法与实现

题库包含 65 道公开汤。选好难度后开始提问，页面会保留本局记录和剩余次数，也可以揭晓汤底。主持人先查与这道汤绑定的规则，规则未覆盖的问题再交给模型判断。

除了能玩，项目还处理了几件实际使用中需要的事：

- 网络断开或重复点击时，用原请求编号取回结果，回答和计次一起写入 SQLite。
- 玩家反馈先由管理员核对。Agent 可以给出候选规则，正式发布仍需人工操作；正在玩的局继续使用开局版本。
- 发版时分开保存程序和数据，保留数据库备份与旧版本，方便出问题时恢复。

## 一次提问如何处理

```text
Next.js 页面 → FastAPI 校验与请求去重 → 规则 / 模型判定
           → SQLite 提交回答、消息与计次 → 页面显示或按原编号恢复
```

等待模型回答时不占着数据库写事务。回答出来后，再一起保存消息和次数；页面没收到结果，也可以按原编号查询。

## 技术栈

| 部分 | 选型 |
| --- | --- |
| 前端 | Next.js 16、React 19、TypeScript、Tailwind CSS |
| 后端 | Python 3.11–3.13、FastAPI、Pydantic、LangChain |
| 存储 | SQLite：会话、消息、规则版本、反馈、审计及 Agent 任务 |
| 验证 | pytest、Vitest、Playwright、GitHub Actions |
| 部署 | Nginx、systemd、独立发行包和数据目录 |

## 本地运行与验证

需要 Node 22.17.0、Python 3.11–3.13、uv 0.12.3。首次安装依赖需要网络；默认测试使用临时数据和 FakeModel，无需模型密钥。

从仓库根目录执行以下 PowerShell 命令；Linux/macOS 安装步骤及定向测试见 [测试指南](docs/testing.md)。

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path (Get-Location) 'backend/.venv-ts01'
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.cache/uv'
uv sync --project backend --locked --group dev --python python --no-managed-python
npm ci --ignore-scripts
npm run test:offline
npm run typecheck
npm run lint
```

完整离线入口耗时较长，日常修改可以按范围选择前端或后端定向测试。启动开发服务前，先按 [后端配置说明](backend/README.md)确认模型、口令和数据目录，再在两个终端分别运行：

```powershell
& .\backend\.venv-ts01\Scripts\python.exe scripts/run-backend.py
npm run dev
```

正常开发服务会加载运行配置，提问可能调用真实模型；离线测试与正常服务使用不同入口。后端默认监听本机地址并固定一个 worker，前端通过 `NEXT_PUBLIC_API_BASE` 配置后端地址。

## 发布状态与证据

- 当前记录的线上发行版本为 `20261025-184511-repairs`，见 [发布记录](docs/deployment-2026-10-25.md)和 [修复记录](docs/repair-2026-10-25.md)。
- 代码提交 `e694077` 的远程离线检查已通过，覆盖 Ubuntu/Windows 与 Python 3.11/3.12/3.13，见 [CI 结果](https://github.com/VVR823/turtle-soup/actions/runs/40505782563)。
- 主持人生产配置使用智谱 `glm-4-flash-250414`；其免费资格以供应商政策为准。生产自动修复 Agent 当前关闭，站点按现有 HTTP IP 方式提供服务。
- 质量评测的来源、对应版本与适用范围见 [证据表](docs/resume-evidence.md)。

## 项目贡献

项目所有者负责需求定义、体验迭代与验收，前端采用 AI 辅助实现，后端、测试与文档也有 AI 协作。个人贡献按实际完成的工作描述，参考 [简历稿](RESUME.md)与 [学习路线](docs/learning/project-learning-map.md)。

[技术文档](docs/README.md)按用途提供入口；[历史归档](docs/archive/README.md)保留阶段规划、旧稿和验收记录，历史状态以各自日期为准。
