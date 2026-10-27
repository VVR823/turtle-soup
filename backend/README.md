# Turtle Soup Python 后端

FastAPI 后端负责主持判定、对局存储、请求恢复、玩家反馈、规则审核及受控修复 Agent。生产自动 Agent 当前关闭；最近发布情况见 [2026-10-25 记录](../docs/deployment-2026-10-25.md)。

## 安装与测试

在仓库根目录按 [安装与测试指南](../docs/testing.md)准备锁定依赖。Python 依赖以 `backend/pyproject.toml` 和 `backend/uv.lock` 为准。

```bash
npm run test:backend
node scripts/test-backend.mjs backend/tests/test_settings_isolation.py -q
```

默认测试使用临时 SQLite 和 FakeModel，不加载个人模型密钥或真实运行数据。全项目离线入口为 `npm run test:offline`，远程验证见 [GitHub Actions](https://github.com/VVR823/turtle-soup/actions)。

## 启动与配置

安装依赖后，从仓库根目录使用虚拟环境中的 Python 启动。PowerShell：

```powershell
& .\backend\.venv-ts01\Scripts\python.exe scripts/run-backend.py --check
& .\backend\.venv-ts01\Scripts\python.exe scripts/run-backend.py
```

Linux/macOS 使用 `./backend/.venv-ts01/bin/python scripts/run-backend.py --check` 检查，再去掉 `--check` 启动。第一条仅检查配置，第二条启动正常服务并可能调用真实模型。启动脚本固定单 worker、本机监听并关闭 Uvicorn 的代理头提前改写；代理信任由应用的 `TRUSTED_PROXY_CIDRS` 控制。

配置优先级为进程环境、`backend/.env`、根 `.env.local`。站点口令与管理员口令使用不同值，供应商密钥仅保留在后端。启动前确认数据目录、模型资格及访问控制；已有数据库按 [迁移指南](../docs/migrations.md)显式升级。

## 常用接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| GET | `/api/config` | 站点访问配置 |
| GET | `/api/soups` | 公开汤面目录 |
| POST | `/api/chat` | 创建会话或提交问题 |
| GET | `/api/session/{session_id}` | 恢复对局 |
| POST | `/api/evaluate` | 揭晓与评分接口 |
| POST | `/api/feedback` | 玩家纠错 |
| GET/POST | `/api/feedback/admin...` | 管理员反馈处理 |
| GET | `/api/metrics/admin`、`/api/metrics/admin/export` | 私有统计查询与导出 |

管理接口使用独立管理口令。候选规则批准、发布及回滚的具体接口见 [候选审核参考](../docs/candidate-review-reference.md)，统计字段见 [统计参考](../docs/metrics-reference.md)。旧 `merge-verified` 入口返回 410。

## 代码入口

- `app/main.py`、`app/runtime.py`、`app/config.py`：应用工厂、运行状态和配置。
- `app/ai_host.py`、`app/host_evidence.py`：主持判定与来源绑定证据。
- `app/game_service.py`、`app/game_store.py`：整轮事务、请求去重与恢复。
- `app/agents/repair_agent.py`：受限工具调用、持久化任务与候选生成。
- `app/migrations.py`：数据库版本管理。

更多原理见 [技术文档](../docs/README.md)。早期后端说明已移至 [历史归档](../docs/archive/backend-readme-legacy.md)。
