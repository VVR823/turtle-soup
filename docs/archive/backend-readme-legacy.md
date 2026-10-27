> 历史归档：这是早期后端说明，保留当时口径。当前配置和接口见 [后端 README](../../backend/README.md)；其他记录见 [历史目录](README.md)。

# Turtle Soup Python 后端

FastAPI + Pydantic + LangChain 承载主持人判定、会话和反馈接口。整轮事务/幂等恢复、分窗口限流和模型有界准入已完成本地验证及独立审查；语义规则纠正、动态发布和受控 Agent 尚未完成，不代表生产签收。

## 安装与测试

从**仓库根目录**执行 [统一安装/测试指南](../../docs/testing.md)。使用 `backend/pyproject.toml + uv.lock`，不要依赖旧 `.venv`、未锁定的全局包或仅靠 requirements.txt 复现传递依赖。

```bash
npm run test:backend
node scripts/test-backend.mjs backend/tests/test_settings_isolation.py -q
npm run test:offline
```

前提是已按指南安装 Python/Node 依赖。默认测试仅使用临时数据与 FakeModel；真实模型 QA 显式 opt-in，online 历史脚本默认不收集。当前数量与跳过原因见 [实施记录](../../docs/ts01-status.md)。

## 启动与配置

推荐从仓库根目录使用 `python scripts/run-backend.py`，或 `python scripts/run-backend.py --check` 仅验证配置。如果直接在 backend 工作目录启动，必须使用 `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers`，避免服务器提前相信伪造的代理头。代理信任统一由应用的 TRUSTED_PROXY_CIDRS 控制，默认不信任；站点与管理员口令必须不同。正常启动与默认离线测试不同：会加载真实配置、初始化指定数据目录，提问可能调用真实模型。使用前先核实免费资格、数据路径和访问控制；本轮没有执行真实调用或线上部署。

配置优先级：进程环境 > backend/.env > 根 .env.local。加载不修改全局环境；导入 app.main 不再读配置/建库/创建 HTTP 客户端。实例状态与启动/关闭约定见 [运行时参考](../../docs/test-runtime.md)。

## 当前接口

新增私有统计 `GET /api/metrics/admin` 与 `/api/metrics/admin/export`：独立管理口令、手动查询、完整导出边界及显式004见[参考](../../docs/metrics-reference.md)/[操作](../../docs/metrics-howto.md)/[TS16状态](../../docs/ts16-status.md)。生产未迁移部署。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/config | 站点是否启用口令 |
| GET | /api/soups | 汤面目录，不返回完整汤底 |
| POST | /api/chat | 创建会话或提交问题 |
| GET | /api/session/{session_id} | 恢复进行中会话 |
| POST | /api/evaluate | 旧版评分及揭晓 |
| POST | /api/feedback | 玩家纠错 |
| GET/POST | /api/feedback/admin... | 独立管理员口令保护的旧审核；旧 merge-verified 入口返回 410，不再直接发布规则 |
| GET | /health | 健康状态；测试模式另含实例标识 |

表格只描述既有能力，不表示所有行为已达到升级标准。限流/代理/整轮事务已有本地证据；真实部署边界未验收，旧评分、JSONL 并发和模糊检索仍由后续任务纠正。

## 关键文件

`main.py` 是纯应用工厂；`runtime.py` 持有单应用状态；`config.py` 显式加载配置；`db.py` 在启动或首次显式 CRUD 初始化新空库/验证已迁移库，已有旧库须显式离线迁移。`migrations.py` 注册不可变001与显式002，新空应用要求002，CLI默认001不变；`baselines.py` 保存/校验完整冻结基线。见 [隔离迁移指南](../../docs/migrations.md)和[请求审计](../../docs/request-audit.md)。主持人业务仍在 `ai_host.py`，FakeModel 只在测试中替代传输，不是准确率裁判。

设计取舍见 [隔离 ADR](../../docs/adr/0001-test-isolation.md)，项目入口见 [根 README](../../README.md)。
