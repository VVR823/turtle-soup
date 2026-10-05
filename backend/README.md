# 海龟汤 AI 主持人 · Python 后端

本项目是「许二木海龟汤自助」的 **AI 主持人后端**，采用 **Python + FastAPI + LangChain**
实现，替代原先 Next.js 内的 TypeScript 接口，作为真正的后端服务，前端（Next.js）通过
CORS 直连本服务（默认 `http://localhost:8000`）。

> 技术定位：展示 **Python 后端工程化能力** 与 **AI 应用开发能力（LangChain 编排 LLM）**。

---

## 技术栈

| 能力 | 选型 |
| --- | --- |
| Web 框架 | FastAPI（Pydantic v2 数据校验） |
| AI 编排 | LangChain（`langchain-openai` 的 `ChatOpenAI` + `ChatPromptTemplate` + `JsonOutputParser`） |
| 大模型 | **智谱 GLM-4-Flash**（永久免费；`config.py` 支持 ollama 本地 / siliconflow / zhipu 一键切换） |
| 存储 | **SQLite**（标准库 `sqlite3`，session 问答记录，事务保证并发安全；旧版 JSON 存储首次启动自动迁移） |
| 限流 | 自研滑动窗口限流（按客户端真实 IP，`X-Forwarded-For`），防 LLM 额度被刷 |
| 测试 | pytest（44 用例：纯逻辑单测 + 双鱼/旅馆 QA 回归） |

---

## 目录结构

```
backend/
├── app/
│   ├── main.py        # FastAPI 入口：/api/soups、/api/chat、/api/evaluate、/health（含每 IP 限流）
│   ├── schemas.py     # Pydantic 模型（Soup / Checkpoint / ConfusionPoint / 请求响应）
│   ├── soups.py       # 题库（SEED_SOUPS：双鱼/织梦者/旅馆/新人/人彘/信/新世界，含易错点）
│   ├── prompts.py     # 主持人 / 复盘 System Prompt
│   ├── ai_host.py     # ★ 核心：是否类检测 → confusionPoints 兜底 → RAG → LangChain LLM 判定 / 复盘
│   ├── rag.py         # RAG 检索引擎（关键词 + 编辑距离 + bigram）
│   ├── db.py          # SQLite 会话存储 + 内存题库 + 旧 JSON 自动迁移
│   ├── rate_limit.py  # 滑动窗口限流（按真实 IP）
│   └── config.py      # 环境变量配置（LLM_PROVIDER / API Key / 口令 / 限流开关）
├── tests/
│   ├── conftest.py        # pytest 公共配置（TestClient + 限流关闭 + 会话工厂）
│   ├── test_host_logic.py # 纯逻辑单测（是否类/复合陈述/进度提示/完成度/易错点匹配）
│   ├── test_win_condition.py # 新世界彩蛋通关条件
│   ├── test_shuangyu_qa.py   # 双鱼 48 题 QA 回归
│   ├── test_hotel_qa.py      # 旅馆 10 题 QA 回归
│   └── online/           # 线上验证脚本（部署后手动跑，pytest 自动排除）
├── data/               # sessions.db（会话）+ generated_soups.json（自动生成汤）
├── requirements.txt
└── README.md
```

---

## 运行方式

### 1. 安装依赖（建议使用虚拟环境）
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. 配置密钥
复制 `.env.example` 为 `.env` 并填写：
- `LLM_PROVIDER=zhipu`（默认 ollama 本地；也可 `siliconflow` 用硅基流动）
- `ZHIPU_API_KEY=...`（GLM-4-Flash 永久免费，注册实名即可用）
- `SITE_PASSWORD=...`（可选，开启访问口令）
- `RATE_LIMIT_ENABLED=1`（限流开关，本地调试/测试可设 0）

### 3. 启动后端
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 启动前端（另开终端）
```bash
cd ..            # 回到 turtle-soup 根目录
npm run dev      # 前端跑在 http://localhost:3000，自动直连 :8000 的 Python 后端
```
浏览器访问 http://localhost:3000 即可游玩。

---

## 测试

```bash
cd backend
venv\Scripts\python.exe -m pytest tests/ -v     # 44 用例，约 10 秒（QA 会真调 LLM）
venv\Scripts\python.exe -m pytest tests/test_host_logic.py -v   # 纯逻辑，毫秒级
```

线上验证脚本（`tests/online/`，部署后手动跑）见该目录 README。

---

## API 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/soups` | 返回汤品列表（**不含完整汤底**，供大厅/难度页） |
| POST | `/api/chat` | 无 `sessionId` → 创建会话（需 `soupId` + `level`）；有 `sessionId`+`question` → 主持人作答 |
| POST | `/api/evaluate` | 根据本局问答自动评估还原完成度，并返回完整汤底 |
| GET | `/health` | 健康检查 |

限流：`/api/chat` 每 IP 每分钟 30 次 / 每小时 300 次；`/api/evaluate` 每分钟 10 次。超限返回 429。

---

## AI 主持人的三层判定（核心亮点）

每一次提问都按以下顺序处理，**确定性优先、LLM 兜底**，杜绝"该说不是却和稀泥"：

1. **是否类检测**：非"是/否"型提问只提醒、不扣次数。
2. **confusionPoints 确定性兜底**：易错问法（如"雪地是真雪吗"）用正则命中即返回标答，**先于 LLM 执行**，保证稳定。
3. **RAG checkpoint 匹配**：关键词 + 编辑距离 + bigram 相似度匹配汤底要点，命中直接返回预设判定。
4. **LangChain LLM 兜底**：以上都不命中时，用 `ChatOpenAI` 调智谱 GLM-4-Flash 判定，归一化为 5 种标准回答
   （是 / 不是 / 是也不是 / 算是 / 与此无关）。

复盘评估（`/api/evaluate`）按预设 checkpoints 规则化计算完成度（不依赖 LLM，瞬间返回），
配合彩蛋汤的 `win_condition` 通关判定与 `special_scoring` 解锁映射。
