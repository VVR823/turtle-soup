# Turtle Soup · 秋招简历稿（2026-10-27）

项目当前已具备写入简历的工程成果。以下正文按已核实的功能与部署记录整理；职责应保留 AI 协作事实，不代表本人已经独立掌握全部实现。

## 可使用的项目描述

**许二木海龟汤自助｜AI 应用与受控反馈修复系统**

技术栈：Python、FastAPI、SQLite、Next.js、React、TypeScript、Nginx、systemd。

职责口径：负责需求定义、体验迭代与验收，采用 AI 辅助完成工程实现及测试。

- 基于规则、证据检索与大模型兜底构建 AI 海龟汤主持应用，将正常判定约束为五类结论，支持 65 道公开题目的难度配置、对局存档与反馈管理。
- 通过请求编号、SQLite 唯一约束及事务提交实现重复请求去重和断网恢复，统一保存回答、消息与计次结果，避免同一请求重复计次。
- 实现反馈审核、脱敏授权、受限 Agent 候选生成及人工审批流程，分离批准、发布与回滚权限；新会话固定规则版本，旧对局保留历史版本。
- 使用 Nginx 与 systemd 部署前后端，建立独立数据目录、数据库一致备份和可回退发行版本，并以组件、接口和浏览器测试验证关键故障与恢复场景。

展示网站：<http://47.97.33.174/>（保留访问口令，演示时由本人输入，不公开口令）。

## 使用边界

- 主应用已上线；生产自动修复 Agent 保持关闭。候选审批、发布与回滚已有隔离合成流程证据，不能写成生产无人值守自愈。
- 不使用旧稿的“97.7% 准确率”“255 条自动上线规则”“独立完成全部代码”等表述；不编造用户规模、并发量或性能提升。
- 79.09% 仅是 2026-10-18 的 110 题同集回归结果，不能写成新题泛化准确率；本稿正文不使用该百分比。
- 2026-10-27 只读核对：线上为 `20261025-184511-repairs`，三项服务 active，口令开启。本次仓库同步包含 10 月 25 日已部署修复及当前简历材料；具体提交以 Git 历史为准。
- 面试前应能解释一次完整提问、重复请求恢复、规则版本及人工发布边界。学习记录尚未证明全部掌握，不能预先写“精通”或“独立设计核心引擎”。

逐项证据见 [简历证据表](docs/resume-evidence.md)，现场演示顺序见 [项目展示](docs/showcase.md)，上线记录见 [生产发布记录](docs/deployment-2026-10-25.md)。

<details>
<summary>历史准备说明与旧稿（仅供比对，不用于投递）</summary>

# Turtle Soup · 旧简历准备入口

新版私有材料见[三方向简历草稿与证据](docs/resume-evidence.md)及[项目展示](docs/showcase.md)。先如实说明需求/体验/验收贡献和AI辅助实现，本人独立技术掌握需按[学习路线](docs/learning/project-learning-map.md)复现取证。当前398源码的3515离线通过/14明确跳过、另35 owned Edge见[实际证据](docs/a46-local-verification.md)；TS17的3231/33Edge是历史范围，均不是真实模型准确率或新版本上线证明。

下方旧稿原样保留作历史；其中独立实现、准确率、视频题集、已上线规则、Docker一键启动等表述**不获本次验收背书，不能直接粘贴投递**。新版不拿旧数字补齐未知指标。

---

# 海龟汤 AI 主持人 · 历史简历草稿（待证据核验）

> 此文保存升级前草稿，不应直接粘贴。旧准确率并非独立 holdout 证据，“全链路审计”“并发安全”等能力尚待升级验收。项目有 AI 协助，应如实描述自己的产品决策、修改、调试与学习贡献，不把未完成或尚不能解释的技术工作写成已独立实现。新版材料将在 TS-18 按证据与学习记录重写。

项目名称：许二木海龟汤自助（Turtle Soup AI Host）
定位：基于大模型的横向思考推理游戏，玩家向 AI 主持人提问，主持人被约束为「是 / 不是 / 是也不是 / 算是 / 与此无关」五选一作答。

---

## 中文版（适合国内简历）

- 独立设计与实现「约束式 AI 主持」判定引擎：以「确定性规则兜底 + RAG + LLM」三级链路替代纯大模型自由作答，把回答严格收敛到五种结论（是 / 不是 / 是也不是 / 算是 / 与此无关），避免玩法崩坏；核心逻辑见 `backend/app/ai_host.py`。
- 构建端到端自动化评测脚本，基于 **1565 条真实视频问答对**（全部 65 道非彩蛋汤，从 B站海龟汤实况逐批扒取+清洗）量化主持人准确率，将「答得对不对」从主观评判变成可追踪指标；硬准确率 **97.7%**，并把答错的真实问法经「评测错误→规则注入」闭环自动沉淀为主持人规则（255 条已上线）。
- 落地全链路 Trace 日志：按会话回放每道题的判定路径（命中规则 / 分支 / 最终答案），支持线上问题定位与判定审计（`backend/app/trace_logger.py`）。
- 完成 Docker Compose 容器化（nginx + 前端 + 后端三服务编排）并针对国内网络配置镜像加速；上线后出现「代码更新不生效」，排查定位为容器与 systemd 双轨共存、流量被旧容器截走，据此重新评估生产部署形态，最终线上改用 **systemd + 主机 nginx** 保证更新可靠，Docker 保留为本地一键拉起方案。
- 负责 66 道题库的结构化建模与元数据治理（难度分级、本格/变格判定、角色计数等），并设计玩家反馈闭环：用户纠错经审核后自动沉淀为确定性规则，持续降低 LLM 兜底错误。

技术栈：Python / FastAPI / LangChain / 智谱 GLM-4-Flash / React / Next.js / TypeScript / Docker / SQLite

---

## 英文版（适合外企 / 英文简历）

- Designed and shipped a constrained AI host engine that replaces free-form LLM answers with a deterministic fallback + RAG + LLM three-tier pipeline, strictly limiting responses to five verdicts (yes / no / both / partial / irrelevant) to keep the game playable.
- Built an end-to-end evaluation harness over **1,565 real video Q&A pairs** (all 65 non-egg soups, scraped and cleaned from actual Bilibili gameplay), turning host accuracy from a subjective judgment into a trackable metric — achieving **97.7% hard accuracy**, with a "eval-error → rule injection" loop that auto-promotes real player questions the host got wrong into deterministic rules (255 shipped to production).
- Implemented per-session trace logging that replays every question's decision path (rule hit / branch / final answer) for online debugging and audit (`trace_logger.py`).
- Containerized the full stack with Docker Compose (nginx + frontend + backend) plus CN mirror acceleration; after a production incident where the container stack shadowed the systemd deployment and served stale code, re-evaluated the deployment topology and moved production to **systemd + host nginx**, keeping Docker for local one-command bring-up.
- Modeled 66 puzzles with structured metadata (difficulty tiers, genre/cast-count rules) and a user-feedback loop that promotes verified corrections into deterministic rules.

Tech: Python / FastAPI / LangChain / Zhipu GLM-4-Flash / React / Next.js / TypeScript / Docker / SQLite / RAG

---

## 面试可展开的点（备用）

1. 为什么用「确定性兜底 + LLM」而不是纯 LLM？—— 规则拦截高频陷阱保证稳定，模型兜底未知问题，兼顾精度与泛化。
2. 97.7% 怎么来的 / 剩下 35 个错误为什么不动？—— 评测口径：全部 65 道非彩蛋汤用真实视频问答对评测（不掺 AI 生成的假题），视频口语里的上下文问法（"他啥意思"）单句无法独立判定、主持人给引导属正确行为，评测前剔除（2016 → 1565 条有效是否问法）；剩余错误全在 LLM 兜底分支（126 题，76.3%），是评测集外的新问法，规则注入闭环会持续吸收。数字是诚实的——之前"规则自评 100%"是评测集用了题库自动生成题的自欺，换成真实问答对后暴露，反而推动了评测方法论和规则闭环的完善。
3. Trace 怎么帮定位问题？—— 线上某题答错，直接按 session 看命中了哪条规则。
4. 部署形态怎么选的？—— 先用 Docker Compose 做到「一条命令拉起三服务」；上线后玩家反馈「改了没生效」，排查发现是容器与 systemd 双轨共存、80 端口被旧容器占着，流量根本没进新部署。据此把生产环境改成 systemd + 主机 nginx 保证更新链路可靠，Docker 留作本地统一环境——按场景选工具，不是哪个新用哪个。

</details>
