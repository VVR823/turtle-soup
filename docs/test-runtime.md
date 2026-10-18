# 测试运行时参考

本参考覆盖TS-01至TS-12已实施本地接口；独立审查状态按各阶段台账，TS12本地唯一审查及一次修复完成，但正式真实模型质量仍未验收。页面恢复见[TS08状态](ts08-status.md)，请求审计见[TS09状态](ts09-status.md)，反馈/版本规则本地验收见[TS10状态](ts10-status.md)，私有数据合同与未完成人审见[评测数据](evaluation-data.md)/[TS11状态](ts11-status.md)，完整分母/安全CLI见[运行器](evaluation-runner.md)/[TS12状态](ts12-status.md)。运行命令见[操作指南](testing.md)，设计原因见[ADR](adr/0001-test-isolation.md)。

## 工厂与生命周期

`create_app(settings: Settings | None = None, *, model=None, soups=None) -> FastAPI`：仅创建路由/中间件，不在导入或工厂调用时读取 dotenv、数据库、运行时题库或创建 HTTP transport。

启动生命周期选择配置、建立 Runtime、初始化新空库或验证已迁移库；TS-02 后不会自动升级已有旧库，见 [迁移指南](migrations.md)。关闭时释放持有的 sync/async HTTP transport，清空模型/答案缓存并标记关闭。初始化失败也会关闭 Runtime。未启动/已关闭应用的请求返回 503，`code=app_not_started`。

`model` 接受判定链兼容的 Runnable，测试传 `FakeModel(answer="与此无关")`；它返回合成 JSON，不看标答、不请求供应商。`soups` 接受 `Soup` 列表，在启动时深拷贝，实例间不共享题库修改。

`Runtime` 持有 settings/model/soups/host_cache/llm_cache/HTTP transport/limiter。`runtime_context(runtime)` 恢复退出前上下文；请求中间件利用 ContextVar 将所属实例传到 FastAPI 同步线程。`get_runtime()` 对旧 CLI 提供延迟创建的独立回退实例；首次显式 CRUD 会惰性初始化数据库，也可显式调用 `db.initialize()`，但 import 不再自动建库。脚本显式读取 `db.SOUPS` 时仍可能加载运行题库，不属于纯 import。

## Settings

`Settings` 是 frozen dataclass；`Settings.for_test(data_dir: Path, **overrides)` 默认 `TESTING=True`、provider=fake、真实模型/运行时题库/限流/Trace 关闭。数据目录在构造时解析为绝对路径；测试模式拒绝当前仓库 `backend/data` 和根 `data` 及其后代。`overrides` 是开发者显式测试控制，不是安全沙箱权限。

`load_settings(*, environ=None, load_env=True, backend_dir=BACKEND_DIR)` 默认加载优先级：进程环境 > backend/.env > 根 .env.local。不修改全局环境。按 backend 再 root 的顺序解析 `${VAR}`，已有环境值优先，并兼容 `${VAR:-fallback}`。显式 `environ` 替代 os.environ；`load_env=False` 完全不读 dotenv；环境中 `TURTLE_SOUP_TESTING=1` 强制不读 dotenv。布尔值只接受 `0`/`1`；空数据路径报错。根 `.env` 不在正常加载链中。

| 配置环境变量 | 类型 / 普通模式默认值 | 作用 |
| --- | --- | --- |
| TURTLE_SOUP_DATA_DIR | Path / backend/data | 所有运行文件的根目录 |
| TURTLE_SOUP_TESTING | bool / 0 | 测试目录校验和 health 标识 |
| TEST_INSTANCE_ID | str / 空 | 测试 health 的可选实例标识；专用 runner 用自己的 TURTLE_SOUP_TEST_INSTANCE_ID 传入 |
| TURTLE_SOUP_LOAD_RUNTIME_PUZZLES | bool / 1 | 显式加载 generated/verified QA；旧 JSON 必须离线迁移，启动不自动导入 |
| TURTLE_SOUP_ALLOW_REAL_MODEL | bool / 1 | 没有注入模型时是否允许建立真实模型客户端 |
| LLM_PROVIDER | str / ollama | 兼容旧 provider 选择；fake 仅为合成夹具 |
| OLLAMA_BASE_URL / OLLAMA_MODEL | str / http://localhost:11434/v1 / qwen2.5:7b | Ollama 配置 |
| QWEN_BASE_URL / QWEN_MODEL / QWEN_API_KEY | str / https://dashscope.aliyuncs.com/compatible-mode/v1 / qwen-turbo / 空 | 旧 cloud/fallback 配置 |
| SILICONFLOW_BASE_URL / SILICONFLOW_MODEL / SILICONFLOW_API_KEY | str / https://api.siliconflow.cn/v1 / Qwen/Qwen2.5-7B-Instruct / 空 | 硅基流动配置 |
| ZHIPU_BASE_URL / ZHIPU_MODEL / ZHIPU_API_KEY | str / https://open.bigmodel.cn/api/paas/v4 / glm-4-flash-250414 / 空 | 智谱配置 |
| CORS_ORIGINS | tuple[str,...] / localhost:3000、127.0.0.1:3000 的 http origin | 逗号分隔，去空白项 |
| SITE_PASSWORD / ADMIN_TOKEN | str / 空 | 站点与后台各自的访问口令 |
| RATE_LIMIT_ENABLED / ENABLE_TRACE | bool / 1 | 原限流器和 Trace 的开关 |
| TRUSTED_PROXY_CIDRS | tuple[str,...] / 空 | 默认忽略代理头；仅显式可信直连代理及从右往左可信 hop，禁止 trust-all |
| API_WORKER_COUNT / ENABLE_AGENT | int / 1，bool / 0 | Agent 不能在声明多 worker 配置下启用；owned launcher 只接受一个 API worker |

API 密钥与两种口令不进入 Settings repr；这不是全局日志脱敏保证。TS-03 网关拒绝未知供应商，不进行旧收费 fallback。云调用需 MODEL_FREE_VERIFIED=1 且 FREE_MODEL_PROVIDER / FREE_MODEL_NAME / FREE_MODEL_BASE_URL 与配置精确一致，否则在创建客户端前拒绝；该声明不是自动核验实际账户免费资格。仅本地 loopback Ollama 或明确匹配声明的云配置可进入实际适配器，离线测试仍拒绝所有真实服务。

## TS-03 类型与网关

`HostResult` 区分 answer/reminder/system_error/win，游戏扣次数来自 chargeable，不解析展示文案或 emoji。模型只可提交严格的五类 answer 与 reasoning，reasoning 不进入可见返回；未知枚举、重复键及越权字段拒绝。请求 JSON 也拒绝重复字段，统一安全 422 不回显玩家原文。

`Runtime.get_model_gateway()` 延迟建立实例自有网关；关闭开始时在同一锁内停止首次创建并捕获已有网关。`ModelGateway.invoke` 单期限共享至多 2 次显式尝试，45 秒为在线初值；最多 2 个本地实际在途 owner。等待失败或取消请求不会释放尚未收尾的名额；close 有有限等待，并记录实际残留/cleanup_failed，不冒充远端模型停止。

上下文保留完整汤面/汤底，最多 12 个有效完整问答和 8000 字符；按完整辅助事实/旧轮裁剪，原历史不删。8000 字符不是精确 token 预算。真实输出质量/免费账户/HTTP 断网联动与 TS-04 整轮提交都不能仅凭这些离线测试签收。

## 测试入口与防误用边界

- pytest 在 collection 前移除供应商/云 tracing 密钥、关闭 tracing、屏蔽 LangSmith pytest 插件；临时目录使用 `.cache/pytest/run-*`。
- Python socket 操作默认只允许内核 socketpair 和本测试进程仍持有的 loopback/Unix socket 绑定；地址、socket 类型与 family 必须匹配，拒绝外部 DNS/IP 和本地未知服务，包括 Ollama 11434。
- 常用 open/Path.read_text/os.open/sqlite connect 内容访问拒绝真实 dotenv、backend/data 和根 data。
- 保护检查同时覆盖命名路径及已解析目标、SQLite file URI；pytest basetemp 限定为 `.cache/pytest` 下新的/空的专用子目录，拒绝 cache 路径重定向。
- Windows 常见 `\\?\` / `\\.\` drive 与 extended UNC 路径共享规范化身份，不用别名绕过数据目录保护；非文件设备命名空间拒绝，pytest 的 NUL 日志槽除外。
- Vitest 不加载 Vite dotenv，默认 fetch 会报错，各单元测试显式替换 fetch；使用独立 jsdom localStorage，不是用户浏览器配置。
- API runner 先尝试绑定固定端口确认空闲，再启动有唯一实例 ID 的 FakeModel 服务。专用 Python 服务在父进程 stdin 关闭时正常停止，避免 Windows venv launcher 遗留实际解释器。Playwright 只发请求到 127.0.0.1:18080，并核验 health 的 testing/provider/实例 ID。
- EOF 后最多等待 5 秒，再仅对本次拥有的 fixture PID/进程组执行有限强制收尾；强制退出或收尾失败都会使测试失败。权限不足时明确报出待核验的拥有 PID，不能宣称子进程已回收或杀未知服务。
- `exit` 与 `close` 分开记录：launcher 已 exit 或 signalCode 非空时，即使后代仍持有 stdout，也不得用旧 PID 执行强制终止。

这些是**Python/JS 层防误用保护，不是 OS 网络沙箱**。native 扩展、恶意 subprocess、文件删除/改名、Node 原生联网和主动绕过 monkeypatch 不在完整保护范围中。单元测试 fetch guard 不覆盖所有 JS transport。默认只执行仓库中受审查的代码；不要把能跑任意恶意代码视为安全承诺。

默认 Playwright 3 项仍仅为 API 冒烟。TS08 新增独立的 `npm run test:ui` 页面门禁，见下节；两套不能混称。FakeModel 证明工程路径可测，不能提供模型质量、真实 Agent 成功或线上安全的证据。

## TS-05 本地请求安全与模型准入

限流策略按身份、路由模板、策略和窗口分别计数，用单调时钟。30/min 与 300/hour 一次 check-all/append-all，拒绝不会部分消费另一个窗口；同请求不重复消费同一策略。活跃 key 容量满时不丢旧限制；429 的 Retry-After 为向上取整秒数。代理头默认不可信，配置后仍需验证直连 peer 与每一跳；真实生产反代未由此证明。

## TS-06 来源规则与纯确定性缓存

`normalize_exact_question`（exact-v1）只做 NFC、空白折叠、末尾问号处理，保留否定/主体/数字/条件。检索的词面排序不生成答案，证据 ID 绑定实际 Soup/p1 内容与来源路径。完整原始汤底和至多 12 个有效完整轮次继续进入模型，不确定语义走正常模型路径，不当作系统异常。

`handle_host_response(..., *, versions=None)` 由服务在判定前传入冻结 p1/r1/host-v3/exact-v1；每次使用版本化结果前都核对实际题目内容。规则只允许整句/全分句范围，通用指代不因 exact 命中获得固定答案。第一人称的空历史兼容规则仍标为依赖上下文，不可跨局缓存。

`Runtime.deterministic_host_cache` 是独立、有锁 LRU，容量 1024、插入起 600 秒 TTL；旧 `host_cache`/`llm_cache` 字典保留但在线不读。键包括 soupId、题库/规则/引擎/规范化版本与精确问题。只接收 typed、纯确定性、带来源证据的规则结果，取值再校验且独立拷贝；模型/流程/彩蛋/错误/未版本化结果均不缓存。snapshot 仅聚合 entries/hits/misses/evictions/expirations；miss 是有效键查找未命中，不等于模型失败，重复访问不续 TTL。关闭清空实例自己的缓存。

`HostResult.cacheHit/contextIndependent` 为程序拥有的内部字段，默认 False，模型 HostJudgment 不能赋值。HTTP 剩余次数/会话/请求 ID 由整轮事务生成，不存在缓存里。新 turn 使用 host-v3；旧存储含 host-v2 或无新标志的结果原样重放，不静默重写。必要事务审计和独立 HTTP 尝试已接入 TS-09，并完成本地独立审查及一次修复门禁（轻微项/外部限制保留）；具体字段、未知用量、故障保存、管理员读取和停止边界见[请求审计](request-audit.md)。

静态范围资格在 lookup 前检查，不把任意 authored exact 文本自动声明为纯规则。反身/前后者等上下文引用和不支持的命题语法正常走模型；条件来源及其别名不能抽出无条件事实。人数规则必须明确指向全故事；省略范围不套总人数。省略领域的类型/元素空历史兼容回答标为依赖上下文，不跨局缓存；有历史时交给模型。只发问号/疑问粒子是友好免费提醒，精确键纯函数的空键拒绝仍保留。

公开搜索只匹配 title/surface/tags，不以 bottom/bottomSummary 的存在影响返回列表；合法 evaluate 和已结束会话恢复保留冻结汤底。现有共享站点口令不是用户级账户鉴权，未在 TS-06 冒充新增 RBAC。

BodyLimitMiddleware 在路由之前检查声明长度与实际分片字节数，上限 32768，超限 413 不开局/写反馈/调用模型。管理员 token 与站点口令独立，缺管理配置为 503，错误/缺凭据为 401；未来管理接口必须沿用同一保护。错误输出保留安全 detail/code/requestId，不回显输入或凭据。

## TS-07 评分接口参考

`score_confirmed_coverage(soup, turns:tuple[ConfirmedTurn,...], *, versions:HostVersions, excluded_legacy_count:int=0) -> CoverageResult` 是无 I/O 纯函数。`ConfirmedTurn` 保存原问题、严格 HostResult、turnId、不可变历史 `(question, AnswerType)` 对；输入再校验实际 p1 内容、r1 格式、turn 身份和 host-v2/v3/exact-v1。只有已收费的非 legacy binary answer 对应完整已知事实且正确才计覆盖；复问去重。完整范围不支持时不授分，不改变主持人正常问答路径。

`get_private_host_history(session_id)` 在一致的数据库读取事务中核验 session/turn/两条消息/原问题 digest/结果版本；其 typed 字段只供模型上下文和进度提示，公开历史不暴露 HostResult/evidence。001 精确 legacy marker 只保留历史并计排除数，不重建权威答案；其他损坏当前结果报安全 snapshot_unavailable。

`EvaluationResult` 新字段：`verifiedCoverage:StrictInt|None`（0–100）、`reconstructionScore:None`、`scoreVersion:'coverage-v1'|None`、`plotProgress:StrictInt|None`（0–100）、`unknownTopics:list[str]`。新版本必须 completion==verifiedCoverage；旧 body 字节保留，默认 null/空列表。`evaluate_once` 原短写事务中保存结果和完整 basis digest，重复请求重放；没有评分模型调用。

`ai_host.evaluate_completion` 保留旧签名用于未核验兼容：纯展示文本返回零/新字段 null，不能伪造通关；权威服务必须显式传 typed turns 和 versions。进度提示使用同一 scorer，只显示聚合进度，不提前列出私有 checkpoint。

`src/lib/evaluation.ts` 的 `normalizeEvaluationDisplay(unknown)` 校验评分版本/整数范围/新旧一致性，返回 coverageValue、coverageLabel、reconstructionLabel、plotValue。完整 HTTP DTO/恢复状态机由 TS08 的 game-contract/journal/controller 提供。`node scripts/test-frontend-build.mjs` 仅复制 allowlisted src/public/config 到新 owned fixture，拒绝目录链接，使用最小环境、现有依赖和 loopback API；不读取原 dotenv/data，不证明 standalone 发布包安全。证据和限制见 [TS07 状态](ts07-status.md)。

ModelGateway 的同一个 Condition 同时持有实际 owner 与在线 FIFO ticket。最大实际 owner 2、Agent owner 1；在线等待最多 32 个/10 秒且受原 deadline 约束，等待期间不创建模型工作线程。Agent 忙时立即拒绝，不能越过已有在线等待；取消/网页超时不释放尚未退出并成功收尾的 owner。close 停止准入并唤醒等候者，有限等待后报告残留/清理失败。before_attempt 是可信程序钩子，每次实际尝试前执行，排队/拒绝不触发；TS-14 再接持久化预算，现阶段不宣称恢复预算已完成。

Runtime.pending_agents 是容量 10 的独立内存意图表，相同 key/digest 幂等、变更 digest 冲突、取消释放一次；不是 003 数据库 queued 任务、调度器或已运行 Agent。scripts/run-backend.py --check 只验证配置且 deploymentVerified=false，正常启动必须由操作者显式执行；模板未安装，不检查真实服务。禁止据此宣传跨进程全局上限或远端推理确已取消。

## TS08 公开契约与浏览器恢复接口

`game-contract.ts` 从 unknown 中选取字段：`decodeCreation(input, expectedRequestId)`、`decodeSession(input, expectedSessionId, expectedSoupId)`、`decodeTurn(input, {sessionId,requestId})`、`decodeEvaluation(input)`。身份、整数计数、新旧评分、状态与免费标记不一致时报 GameContractError，不把额外私有 HostResult/evidence 复制到页面状态。普通模型语义判断不在浏览器判错范围。

`game-journal.ts` 的 GameTarget 是 `{soupId:string,level:string}`。`readPending` / `writePending` / `clearPending(expected)` 管理 `game_operation_v1:` 后加 JSON 数组 route key；记录仅包含 `version:1,operation`。create/ask 使用浏览器 randomUUID（小写标准 UUID）；ask 保存 sessionId、trim 后问题（≤500 Unicode 字符）与原 UUID；reveal 保存 sessionId。未知字段、损坏 JSON、写失败报 GameStorageError，保留原记录。`readSavedSession()` 严格读取 last_session，不使用旧兼容 getLastSession 的损坏即 null 行为。

`GameController(target,deps={})` 提供 getSnapshot / subscribe / initialize / ask(input) / reveal / synchronize / restart(confirmAbandon=false) / dispose。GameState.phase 是 initializing/playing/asking/syncing/revealing/ended/error；session/pending/error 可为 null。GameIssue.category 是 auth/missing/incompatible/rate/service/network/protocol/storage/conflict；retryAfterSeconds:number|null。deps 可注入 request/journal/lastSession/newId/now/sleep，仅为测试/程序接口；真实 React 页使用默认严格客户端。轮询最多3次、间隔1000ms；429 等待至少1000ms或更长 Retry-After 后手动同步。useGameController 使用稳定快照的 useSyncExternalStore 与 effect 初始化/取消。

`apiJson(path,init={})` 要求2xx有效 JSON；`apiResponseJson` 返回 `{status,ok,body,headers}`，允许控制器先识别503明确失败的 typed turn。401 抛 ApiAuthError，只清除本请求实际发送且仍存储的口令，旧401不能删新口令。`loadPublicCatalog({query='',signal,token}={})` 将本地 unlocked_soups 加入公开 unlocked 查询；它只接受合法公开目录，不读取私有汤底。

## TS08 自有 UI fixture

`node scripts/ui-e2e-server.mjs` / `npm run test:ui` 固定端口18080/18081，构建前和构建后都检查空闲，再从自己子进程 stdout 的 nonce-ready 标记确认启动，health 再核验 testing=true/provider=fake/同 instanceId。固定测试解释器为 backend/.venv-ts01；前端复用现有 allowlisted sterile builder 和最小环境，无 root dotenv/data。两个服务使用 stdin EOF 收尾；Next 自有 wrapper 把 EOF 转为它自己的子进程 SIGTERM，并等待实际退出。

UI opt-in 只在 test_server.entry 的 Settings.for_test 生效，CORS 固定 `http://127.0.0.1:18081`，不改变生产和原 API-only 默认 CORS。UI runner 拒绝 CLI 参数及外部 baseURL/Python/origin/browser override；Windows 选择现有系统 Edge，其他 OS 仅检查已有 Playwright Chromium，缺失会明确报“UI not verified”，不下载。Playwright fresh context、serviceWorkers=block；浏览器路由只允许两条自有 origin，其他请求 abort。

TS10的`fixture_app(settings, *, ui_testing:bool)`只属于显式`app.test_server`入口：要求TESTING/fake/不ALLOW_REAL_MODEL。只有ui_testing=true且非空TEST_INSTANCE_ID注册`POST /testing/rule-suspension`，严格`sessionId/suspended`与`X-Test-Instance-Id`核验后，对自有临时会话所属规则做真实marker CAS和业务审计。没有任意caller规则ID/发布/模型入口，authorizer固定拒绝候选发布。普通create_app（即便测试模式）与API-only fixture没有这个setup路由。不要在生产启动此测试入口；它只证明合成页面恢复，不授予真实管理员权限或人工标签证据。

端口探测不是原子保留锁，JavaScript 路由防误用也不是 OS 网络沙箱。浏览器供应商自身的后台联网/原生绕过不在完整保证中；独立 browser/OS matrix 仍待外部门禁。详见 [How to 测试指南](testing.md)、[恢复原理](game-recovery.md)与[TS08状态](ts08-status.md)。
