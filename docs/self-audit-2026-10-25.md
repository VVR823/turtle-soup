# Turtle Soup 项目全面自检（2026-10-25）

> 后续修复：本报告保留自检时的原始发现与失败记录。用户随后授权的修复和复验见 [修复记录](repair-2026-10-25.md)；生产发布已完成，当前线上状态以 [发布记录](deployment-2026-10-25.md) 为准。

## 当前结论

线上核心服务运行正常，但确认存在 4 个后台功能缺陷、1 项 Agent 验收时限问题和需要优先处理的依赖安全问题，不能给出“无 bug”结论。本次为检查与报告，没有修复代码、提交、发布、变更生产业务数据或调用真实模型；没有创建自动续跑、Loop 或定时任务。

完整后端 3104 通过 / 3 失败 / 15 跳过；前端 724、框架 103、API 3 通过；浏览器全流程 32 通过 / 3 失败。后端原 3 个失败项、浏览器原 3 个失败项分别隔离复验一次，仍全部失败。检查已经结束，保留失败结论，不自动继续修复。

本报告的日志、截图与机器证据统一位于 `.cache/self-audit-20261025/`。完整浏览器追踪在 `.cache/ui-runs/` 中。

## 检查身份与边界

- 仓库：`D:/CODE/turtle-soup`。
- 分支：`codex/ts02-storage-foundation`。
- HEAD：`c9917a2ebbd541d98ae6b89dc0a93a9438e89f9e`，本地 `origin/main` 指向相同提交；本次没有执行远程 fetch，不据此宣称远程没有更新。
- 线上 release：`/opt/turtle-soup/releases/20261019-c9917a2-admin-simple`。
- 原有未提交内容：`AGENTS.md` 和 `docs/learning/LEARNING_STATE.md`，保留原样。
- 线上只读检查：服务/资源/安全配置、HTTP GET、带凭证的只读接口。报告没有保存凭证或真实反馈原文。
- 浏览器缺陷复现：实际线上前端脚本 + 浏览器内合成 API 响应，所有变更请求均拦截，未送到生产后端。图中“自检合成反馈”不是玩家数据。
- 本地测试使用仓库的隔离数据目录与 FakeModel；不等于真实模型答案正确性验收。

## 确认存在的问题

### B01 / P1：后台高级操作仍会在 HTTP 浏览器中报 UUID 错误

- 位置：`src/components/AgentReviewPanel.tsx:145`、`:155`、`:161`。
- 后台的候选审核/发布、任务启动、回滚直接调用 `crypto.randomUUID()`，没有复用玩家端已经修好的兼容实现。
- 复现：HTTP 打开后台 → 使用合成候选 → 填写拒绝理由 → 点击“拒绝候选”。两次复现均出现 `crypto.randomUUID is not a function`，没有发出变更请求，也没有给用户可恢复的错误提示。
- 浏览器实测：`isSecureContext=false`、`randomUUID=undefined`、`getRandomValues=function`。
- 影响：高级规则操作在这一环境下不可用；普通反馈的“确认反馈有效/不采纳”不经过该方法。生产 `ENABLE_AGENT=0` 且当前无候选，不能把它表述成“今天玩家游戏已全面不可用”。
- 证据：`browser-probes.json`、`uuid-admin-attempt-1.png`、`uuid-admin-attempt-2.png`。

### B02 / P2：后台反馈加载缺少超时恢复，刷新会长期锁住

- 位置：`src/app/admin/feedback/page.tsx:59` 至 `:101`；审核 POST 也没有应用级超时。
- 复现：反馈列表 GET 保持不返回，推进浏览器计时 70 秒；两次仍显示禁用的“刷新中…”，无法在页内重新查询。
- 影响：弱网或请求悬挂时需要整页重开，缺少恢复入口。70 秒为受控浏览器计时，不是对生产接口人为挂起 70 秒。
- 证据：`browser-probes.json`、`admin-request-hang.png`。

### B03 / P2：后台登录未处理浏览器存储写入失败

- 位置：`src/app/admin/feedback/page.tsx:107` 至 `:113`。
- 复现：浏览器存储可读、写入抛出配额异常 → 输入合成管理口令 → 点击“进入”；两次出现未捕获异常，停留在登录页且没有解释原因。
- 影响：存储被限制或配额异常的浏览器无法正常登录管理页。
- 证据：`browser-probes.json`、`admin-blocked-storage.png`。

### B04 / P2：“0 条待处理”会把未加载页面中的反馈漏算

- 位置：`src/app/admin/feedback/page.tsx:165`、`:268`。
- 复现：合成列表共有两条，第一页为已审核反馈，第二页为待审核反馈；首页显示“0 条待处理”，点击“加载更多”后才变成“1 条待处理”。
- 影响：管理员可能误以为工作已清空。当前生产近 30 天待处理为 0，本次没有发现真实反馈已经因此丢失；更早的历史未据此判断。
- 原因：数字来自 `visibleFeedbacks`，而文案没有限定“已加载记录中”。
- 证据：`browser-probes.json`、`admin-pending-before-pagination.png`、`admin-pending-after-pagination.png`。

### S01 / P1：线上和本地 Python 证书依赖命中已公布安全公告

- 本地锁定与实际安装、线上实际安装均为 `certifi==2026.7.22`。
- OSV 对 53 个已安装 Python 包完成查询，返回 certifi 两个编号；`GHSA-6q48-6c7w-9gw2` 与 `PYSEC-2026-4320` 是同一问题的别名，按一项计。
- 维护者于 2026-10-20 发布 emSign 根证书移除公告：相关中间证书密钥泄露，可被用于中间人攻击。确认旧依赖存在，不等于确认服务器已经遭受攻击。
- 维护者公告修复版本为 `2026.10.18`；OSV 当前修复范围建议 `2026.10.19` 或以后，升级时应采用后者并同步锁文件与生产环境。
- 公告：[certifi 维护者安全公告](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)。
- 证据：`python-audit.json`、`certifi-advisory.json`，以及本次线上实际版本查询。

## 自动化验收仍未通过的项目

### T01 / P2：Agent 测试观察窗口在本机稳定超时

完整后端与离线评测结果：**3104 通过、3 失败、15 跳过、2 条缓存权限告警**，共 3122 项，耗时 2382.56 秒。三个失败均抛出 `Owned synthetic worker did not terminate within observation window`：

1. `backend/tests/test_ui_agent_fixture.py::test_browser_fixture_real_worker_creates_own_complete_report_and_pending_candidate`。
2. `backend/tests/test_ui_agent_fixture.py::test_current_missing_corpus_is_real_unavailable_detail_not_a_fake_ready_ui`。
3. `backend/tests/test_ui_corpus_fixture.py::test_actual_withdrawal_refuses_loaded_approval_preserves_state_and_restores_original`。

三个测试共用 `test_ui_agent_fixture.py:39` 的 10 秒观察窗口。在停止其他测试后，保持原断言不变、只复验以上三项，**再次 3 项失败**，耗时 48.51 秒；不是一次偶发故障，也不能靠历史绿色成绩抵消。本次没有修改断言或放宽时限来制造通过结果。仍需核对任务耗时、测试观测窗口和原有业务预算之间的关系。

15 个跳过项为：7 个真实模型 opt-in、6 个符号链接/权限场景、1 个 Unix socket、1 个固定历史后端产物缺失。最后一项来自 `test_packaged_backend_compatibility.py:59`，不能签当前旧包兼容性。两条告警均是 `.pytest_cache/v/cache` 写入被 Windows 拒绝；定向复验使用本次独立缓存目录，没有改 ACL。

证据：`backend-full.xml`、`backend-summary.json`、`backend-recheck.xml`、`backend-recheck.log`、`offline.log`。

### 对应浏览器门禁

本轮标准浏览器门禁：**32 通过、3 失败**。三个失败均停在等待 Agent 从 `running` 变为 `awaiting_review` 的 10 秒断言：

1. `tests/ui/admin-agent-review.spec.ts:81`：可信材料缺失时拒绝审批流程。
2. `tests/ui/admin-agent-review.spec.ts:144`：反馈、授权、候选审批、发布与回滚流程。
3. `tests/ui/admin-agent-review.spec.ts:200`：撤销隐私授权后的失效候选流程。

只读核对本轮隔离 SQLite 后，三个任务最终均到达 `awaiting_review`，耗时分别为 9.729、10.025、9.711 秒，模型调用预算 3、工具预算 2。可以确认测试等待阈值与任务时长接近，不能据此认定生产 Agent 永久卡死；但这三个流程本轮未通过，也不能把其后续审批、发布和回滚步骤补记为成功。

原始日志：`ui.log`。完整 Playwright 截图、trace 与 JUnit：`../ui-runs/978c0572-44e7-4d5b-94ab-36d96998a22f/`。

停止完整测试后，使用同一份已构建前端、全新隔离后端和数据目录，仅重跑上述三个原始浏览器测试，没有改断言，也没有重跑其余 32 个通过项；**仍然 3 失败**，都停在原 10 秒等待处。复验日志 `ui-recheck.log`，追踪目录 `.cache/ui-runs/4ffdf766-3c37-40d9-811d-8155756b3aa5/`。因此不能把失败仅归因于首轮并行负载，后续需修复或论证可靠的任务观测时限。

复验夹具的最终持久记录进一步显示：前两个任务在 12.752、12.501 秒后到达 `awaiting_review`；第三个在测试结束关闭夹具时转入 `needs_human`，终止原因为 `shutting_down`，没有完成候选审核流程。原始 10 秒断言确实未满足；第三个也不能因为属于清理退出就补记为通过。证据：`ui-recheck-task-states.json`。

## 需要调整的项目

### R01：HTTP 访问口令与管理口令缺少传输加密

线上只监听 HTTP 80，后台凭证通过请求头发送。现有口令控制仍有效，但不能提供传输加密。这是此前用户已暂缓的 TLS 项目，本次记录风险，不擅自改配置，也不把已延期事项伪装成新发现的游戏 bug。

### R02：前端依赖有已知公告，需要按实际适用性更新

- 使用官方 npm registry 完成扫描，报告 7 个依赖条目：6 high、1 critical，不能解释成 7 个可直接利用的线上漏洞。
- `next@16.2.12` 为直接生产依赖；`postcss` 为其传递依赖，`sharp` 为可选依赖。`brace-expansion`、`js-yaml`、`undici`、`zod` 为开发依赖。
- 已核对维护者公告：Windows RCE 需要 Windows 服务端；当前生产为 Linux。图片优化漏洞需相应图片处理路径，本项目配置 `images.unoptimized=true`。所查 Server Actions DoS 要求至少一个 Server Action，本仓库未发现 `use server`。不将这些条件未满足的路径称作线上已可利用漏洞。
- 官方扫描给出的整体 next 修复候选为 `16.4.3`；升级时需要评估实际变更并验证，不在自检中直接执行 `audit fix`。
- 初次默认镜像的审计接口 404，不算安全通过；后续官方 registry 查询才是有效扫描。
- 证据：`npm-audit-official.json`；[Next.js Windows 公告](https://github.com/vercel/next.js/security/advisories/GHSA-p293-qw3h-jr36)、[Server Actions 公告](https://github.com/advisories/GHSA-p3m5-59mp-jv5r)。

### R03：未处理反馈的历史入口缺失

页面只发送默认最近 7 天的列表请求，没有时间范围入口。后端允许至多 31 天区间；页面的“全部状态”“加载更多”仍受当前 7 天范围限制。超过 7 天未处理的反馈仍在库中，但在当前页面无法找回；当前线上过去 30 天待处理数为 0，未发现真实积压。

### R04：高级统计展开后仍偏技术化

默认折叠和 375px 无整页溢出已经确认；但展开后仍直接出现 UTC 时间、来源题目版本、规则版本、每页分组数，没有二级“高级筛选”。与之前确认的简化方案仍有差距。属于可用性调整，不是数据错误。

### R05：历史验收快照不能代表当前提交

`ACCEPTANCE_PROGRESS.md` 仍记录 `ace3a956...` 与 2026-10-18 的旧 release；当前 HEAD 和线上已经是 `c9917a2`。历史证据有价值，但后续交接应另附当前身份和实际复测结果，不能直接把旧版通过数搬到新版。

### R06：线上后端代码包存在一处小范围漂移与遗留脚本

- 将线上 `backend/app/**/*.py` 与启动脚本同本地 Git 跟踪文件按统一换行比较，89 个文件中 88 个一致。
- 唯一差异为 `backend/app/paths.py:9`：本地在识别 Windows NUL 设备前会去掉尾部路径分隔符，线上没有这一步；该分支只在 `os.name == 'nt'` 执行，当前 Linux 生产不受影响。
- 线上额外存在 `_deploy_check.py`、`soups_backup_20260828.py`、`soups_backup_20261005.py`。它们不是自动证明故障，但不应长期混在不可变运行代码包里；后续发布时应统一产物来源、归档备份。
- 本次只记录，没有删除线上文件，也没有覆盖正在运行的发布目录。
- 证据：`deployed-code-comparison.json`、`server-code-identity.json`、`server-paths.py`。

### R07：本地缓存权限与历史兼容产物影响验收可复现性

`.pytest_cache` 写入权限异常导致两条告警；固定历史后端包已不存在，导致一项旧包兼容测试跳过。可在后续维护中使用可写的项目内测试缓存目录，并明确哪些历史产物应保留为验收输入。本轮没有修改缓存 ACL，也没有重新制造一个冒充历史包的产物。

### R08：完整门禁耗时较长，应继续按改动范围选择验证入口

本轮后端完整运行约 39 分 42 秒；最慢单项为统计 200/1000/5000 规模测量 88.489 秒，其次为发布后统计规模用例 45.311 秒。本次全面自检运行完整门禁有必要，但日常文案或局部页面修复没有必要重复这一整套；优先相关测试，大版本或全面自检才运行完整门禁。这里仅记录耗时，不在缺少同环境对照的情况下断言出现了代码性能退化。

## 已确认正常的部分

- 前端、后端、Nginx 均 active；本轮读取的服务重启计数均为 0。
- 磁盘使用约 25%，可用约 29 GB；内存约 963 MB available，swap 未使用。
- `/`、`/admin/feedback`、`/health`、`/api/config` 返回 200。
- 未认证的题库、反馈管理、统计和任务接口返回 401。
- `/.env`、`/backend/.env`、`/data/turtle.db`、公开 `/docs` 和 `/openapi.json` 均返回 404。
- 带正确凭证的题库、反馈列表、统计和任务列表只读查询正常。未保存任何凭证。
- 65 道公开汤的各难度提问次数均为 5 的倍数。
- 线上 `ENABLE_AGENT=0`；root cron 中 Turtle Soup/合并/Agent 匹配项为 0。
- 有限的高置信 Git 跟踪文件密钥模式扫描未命中；这不是全历史凭证泄露审计。
- TypeScript 与 ESLint 本轮退出 0；本地浏览器用生产模式页面构建成功。

## 本轮测试汇总

| 检查 | 本轮实际结果 |
| --- | --- |
| 完整后端 / 离线评测 | 3104 通过，3 失败，15 跳过，2 条缓存权限告警 |
| 原后端失败项隔离复验 | 3 失败，原断言未改 |
| 前端单元 / 组件 | 45 文件、724 通过 |
| 测试 / 发布框架 | 103 通过 |
| API 冒烟 | 3 通过 |
| 标准浏览器全流程 | 32 通过，3 失败，失败原因为 10 秒等待超时 |
| 原浏览器失败项隔离复验 | 3 失败，原断言未改 |
| 类型检查 | 退出 0 |
| ESLint | 退出 0 |
| 浏览器受控异常复现 | 后台 UUID、请求悬挂、存储写入异常、分页待处理数均有复现材料 |

`npm run test:offline` 因后端失败退出 1，其 `&&` 后续步骤没有自动执行；因此前端、框架、API 使用各自原始入口单独执行并全部通过，没有重跑完整离线门禁。本轮 API 输出另有 NO_COLOR / FORCE_COLOR 环境提示，不是功能失败。

## 建议执行顺序

1. 统一后台安全编号生成，修复 HTTP 下的高级操作。
2. 更新 certifi，并评估前端依赖安全更新。
3. 修复后台请求超时、存储失败提示和分页待处理数口径。
4. 补充历史反馈查询，进一步收起统计技术参数。
5. 核对并修复 Agent 后端与浏览器的观测时限问题，再对三个对应流程做定向验证。
6. TLS 依照用户此前的延期决定处理；未来长期开放后台时优先安排。

本报告仅完成自检，不自动开始以上修复，不提交、不上线、不自动续跑。
