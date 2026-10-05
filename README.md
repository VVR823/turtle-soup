# 许二木海龟汤自助 · Turtle Soup AI Host

一个基于大模型的「海龟汤」（情境推理）游戏。玩家向 AI 主持人提问，主持人被严格约束为只回答 **是 / 不是 / 是也不是 / 算是 / 与此无关** 五种之一，玩家通过有限次数的提问还原隐藏剧情（汤底）。

这是一个 **Python 后端 + AI Agent 方向的求职作品**，重点不在于「能聊天」，而在于把一条带确定性兜底、可观测、可量化评测的 AI 判定链路真正跑上线。

---

## ✨ 核心特性

- **约束式 AI 主持**：主持人回答被严格限制在五选一，避免大模型自由发挥导致玩法崩坏；通过「确定性规则（confusionPoints）+ 结构化规则（本格/变格、角色数）+ RAG + LLM 兜底」多级判定，兼顾规则精度与泛化能力。
- **三档难度**：许二木 / 包子 / 天一——**提问上限按每道汤分别设定**（同一道汤三档相差 5 次），提问次数越少越难；非是非题只提示、不扣次数。
- **66 道题库**：覆盖本格 / 变格、校园、悬疑、民俗等多类题材，含一个隐藏彩蛋汤。
- **全链路 Trace 日志**：每一题的判定路径（命中哪条规则、走了哪个分支、最终答案）按会话落盘，可回放、可审计。
- **端到端评测**：基于 1565 条**真实视频问答对**跑通整条判定链路（覆盖全部 65 道非彩蛋汤），**硬准确率 97.7%**，把「AI 答得对不对」从主观感受变成可量化、可复现的指标。
- **玩家反馈闭环**：玩家纠错进入后台审阅台，审核通过后每晚 0 点自动合并为主持人规则——规则进化不需要改代码。
- **线上常驻部署**：systemd 常驻服务 + 主机 nginx 反向代理，公网 IP 直接可玩；题库/规则的更新只需重启后端，玩家会话进度不丢。

---

## 🧱 技术栈

| 层 | 选型 |
| --- | --- |
| 前端 | Next.js 16 (React 19) + TypeScript + Tailwind CSS |
| 后端 | FastAPI + LangChain + Pydantic |
| 大模型 | **智谱 GLM-4-Flash**（永久免费、128K 上下文；`config.py` 支持 ollama / siliconflow / zhipu 一键切换） |
| 存储 | SQLite（`sessions.db`，会话状态）+ JSON Lines（反馈 / Trace / 已审核问答对） |
| 部署 | systemd（`turtle-backend` / `turtle-frontend`）+ 主机 nginx（:80 反代 `/api/` → :8000，其余 → :3000） |

---

## 🔧 本地开发

```bash
# 后端（FastAPI，默认 http://localhost:8000）
cd backend
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# 前端（Next.js，默认 http://localhost:3000）
npm install
npm run dev
```

前端通过 CORS 直连后端 `:8000`；访问口令由 `X-Site-Token` 头携带，服务端读取后端 `.env` 的 `SITE_PASSWORD` 校验。模型与密钥配置见 `backend/.env.example`。

---

## 🚀 线上部署（systemd + nginx）

线上是**单机 systemd 部署**（非容器）：后端与前端各由一个 systemd 服务常驻，主机 nginx 在 :80 做反向代理。

```
用户 → nginx :80 ─┬─ /api/  → turtle-backend   (127.0.0.1:8000)
                  └─ 其余    → turtle-frontend  (127.0.0.1:3000)
```

- 服务单元：`/etc/systemd/system/turtle-backend.service`、`turtle-frontend.service`
- 后端目录：`/opt/turtle-soup/backend`
- 前端目录：`/opt/turtle-soup/frontend`（Next.js standalone 产物）
- 部署脚本与详细步骤：见 [`deploy/README.md`](deploy/README.md)（`deploy_all.py` / `deploy_backend.py` / `upload_frontend.py`）

日常更新（改完题库或判定规则后）：

```bash
systemctl restart turtle-backend     # 题库 / 判定规则改动
systemctl restart turtle-frontend    # 前端改动（先重新 build 并上传产物）
```

重启耗时约 2–3 秒，会话状态存在 SQLite 中，**玩家进度不会丢**。

> 仓库里的 `docker-compose.yml`、`Dockerfile.frontend`、`backend/Dockerfile.backend` 是**早期容器化方案**，已不再用于线上——原因是容器与 systemd 曾双轨共存，80 端口被旧容器占用，导致代码更新不生效；现保留用于**本地一键拉起整套环境**。

---

## 📂 目录结构（关键文件）

```
turtle-soup/
├── backend/
│   ├── app/
│   │   ├── main.py             # 入口：/api/soups、/api/chat、/api/evaluate、/health
│   │   ├── ai_host.py          # ★ 主持人判定核心：confusionPoints→结构化规则→RAG→LLM
│   │   ├── soups.py            # 题库（66 道）+ 每道汤的元数据
│   │   ├── prompts.py          # 主持人 / 复盘 System Prompt
│   │   ├── rag.py              # RAG 检索引擎（关键词 + 编辑距离 + bigram）
│   │   ├── trace_logger.py     # 按 session 落盘判定路径，可回放
│   │   ├── feedback_utils.py   # 玩家反馈归一化与校验
│   │   ├── db.py               # SQLite 会话存储
│   │   ├── rate_limit.py       # 滑动窗口限流（按真实 IP）
│   │   ├── config.py           # 环境变量（provider / 密钥 / 口令 / 开关）
│   │   └── scripts/
│   │       ├── eval_host_accuracy.py  # 端到端判定准确率评测
│   │       ├── inject_eval_fixes.py   # 评测错误 → 规则注入
│   │       └── inject_cps.py          # AST 精准插入易错点
│   ├── data/
│   │   ├── sessions.db                # 会话库（SQLite）
│   │   ├── verified_qa_pairs.jsonl    # 已审核问答对（启动时注入规则）
│   │   └── eval/qa_pairs/             # 真实视频问答对评测集（1565 条）
│   └── tests/                         # pytest（多汤 QA 回归 + 接口参数校验，71 用例）
├── src/                        # 前端（Next.js 应用源码）
├── deploy/                     # 部署脚本与指南
└── 讲解复习手册.md              # 逐文件讲解稿（面试自用）
```

---

## 📊 评测与质量

`backend/app/scripts/eval_host_accuracy.py` 解析标准问答集（**1565 条有效是否问法，覆盖全部 65 道非彩蛋汤**，评测文件随仓库提供于 `backend/data/eval/qa_pairs/`；**全部来自真实 B站海龟汤视频问答记录**——40 道视频源 + 25 道无源汤的评测也由对应合集视频补全，彩蛋汤新世界无判定点豁免），直接调用主持人判定函数做端到端验证：

- **硬准确率 97.7%**（正确 1500 / 错误 35 / 需复核 30，需复核的元回答不计入硬指标）。
- **评测口径（诚实、可复现）**：视频口语含大量上下文问法（"他啥意思""为什么是XX"），单句独立评测时主持人给引导属合理行为、不测判定能力——评测前用 `is_yes_no_question` 剔除这类非是否问法（2016 条中 451 条），口径 = **纯是否问法下的判定准确率**。
- **评测错误 → 规则注入闭环**：答错的真实玩家问法经 `inject_eval_fixes.py` 过滤噪音后批量生成 ConfusionPoint，写入 `verified_qa_pairs.jsonl` 自动注入各汤——评测集本身就是主持人持续进化的训练资产（255 条已注入并部署线上）。
- 剩余 35 个错误全部在 LLM 兜底分支（126 题走 LLM、准确率 76.3%），确定性规则层命中即答对。
- 修复过的典型问题：复合陈述「整句锁定」优先、爷爷「死了吗」等歧义问法的窄正则兜底、身份归属类问题误跳 RAG、评测解析对「问/答」「编号+箭头」格式的兼容、真实视频评测暴露的"规则自评 100% 虚高"。
- 报告产物：`backend/data/eval/eval_report.md` 与 `.json`。

**回归测试（改动的准入门槛）**：`backend/tests/` 共 **71 个 pytest 用例**——60 个主持人多汤 QA 回归（逐题打 `/api/chat` 比对真实视频标答）+ 11 个接口参数校验，全绿才算改动合格。

```bash
cd backend
pytest tests/ -q --ignore=tests/online      # 全量回归（online/ 为线上冒烟，需部署后手动跑）
```

**接口健壮性**：`/api/chat` 创建会话时，`level` 参数走白名单（`xuermu` / `baozi` / `tianyi`）。**缺省或非法一律回退到最严格档**——题库中除 `unlimited` 彩蛋汤外全部定义了提问上限，若像旧实现那样把非法值静默当作"不限次"，直接访问 `/game/{id}`（不带 `?level=`）就能绕过次数限制。`test_level_param.py` 已把这条锁死。

**复现评测**（clone 仓库后直接跑，无需桌面文件）：

```bash
cd backend
pip install -r requirements.txt
python -m app.scripts.eval_host_accuracy          # 自动读取仓库内置 qa_pairs/，输出报告
python -m app.scripts.eval_host_accuracy --only 双鱼,七宗罪   # 只跑指定汤
python -m app.scripts.eval_host_accuracy --test-dir <其它目录>  # 自定义评测目录
```

---

## 🔍 判定链路（主持人怎么答）

主持人收到提问后按优先级判定：

1. **彩蛋 / 胜利条件** —— 命中直接裁定
2. **confusionPoints（确定性兜底）** —— 题库内编写的窄正则 / 别名，最精确优先
3. **genre / castCount 通用规则** —— 本格 / 变格、角色数量等结构化约束
4. **是否类检测** —— 非是否问法只引导、不扣次数
5. **RAG + LLM 兜底** —— 非确定性问答交给大模型，并受五选一约束收口

这一设计让「常见陷阱」由规则精准拦截，「未知问题」由模型兜底，既稳又不容易答崩。

---

## 🔐 访问控制

- 站点访问需要口令（防滥用，非盈利），由 `X-Site-Token` 头传入；服务端读取 `.env` 中的 `SITE_PASSWORD` 校验。
- 反馈管理后台另有独立口令（`ADMIN_TOKEN`），未配置时后台接口自动关闭。
- 大模型密钥（如 `ZHIPU_API_KEY`）只在后端持有，不暴露给浏览器。

---

## 📌 备注

- 本项目为求职展示作品；服务器到期后不影响本地复现与构建。
- 当前线上站点通过 HTTP 提供服务；如需 HTTPS，需自备域名并接入证书。
- **文档同步约定**：任何代码 / 配置 / 题库 / 部署方式的改动，都要回头同步更新本 README 及 `讲解复习手册.md`，避免文档描述与真实架构脱节。
