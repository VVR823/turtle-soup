# TS08 页面状态与可靠恢复设计

## 已批准目标和设计路径

架构型子阶段：按原 TS08/A30–33/C13–15，重整已有开局/提问/揭晓/恢复之间的边界，不改变游戏规则，不增加付费服务。用户已明确授权持续自主决策、每阶段自审测试修正，无需重新逐段确认。TS07 独立审查期间只创建本设计/计划，不修改其冻结产品源码。TS07 终态审查及一次修复门禁后才能开始本阶段代码。

玩家期待：刷新不丢局；网络错误不另开新局、不重复扣数；同一问题响应丢失可以找回来；切汤/难度后旧响应不能污染新画面；已结束对局恢复原分数/汤底；网站服务失败不能假装已解锁或列表为空。仅已核验的 failed/expired/reminder 状态可以说未扣次数，不确定提交时明确“正在同步，是否提交尚未确定”。

## 现有具体问题

GamePage 初始化没有 requestId、不阻止空 session 发问；restore false 包含401/503/断网，随后自动开局覆盖 last_session；重放晚响应可覆盖已切换页面。UI错误气泡统称不会扣次数，但响应可能在服务端提交后丢失。揭晓和提问没有同步占位互斥，终态恢复清空 evaluation，揭晓/返回大厅清掉恢复指针。复盘用 emoji 猜免费状态。SiteGate 在配置失败时默认开放，口令验证只检查401，503也会保存口令。首页/难度/反馈列表把错误或非法数据当空/找不到，反馈不传 unlocked。eslint 扫描既有后端/临时缓存导致 EPERM。

## 方案比较与选型

1. 推荐：小型框架无关 GameController + 严格 HTTP DTO 解码 + 明确持久化 journal。异步业务和 storage 写入集中一个入口，React只订阅渲染；可用事件栅栏测试响应乱序与失联。成本是新增几个职责单一模块，不引入状态机依赖。
2. 全部留在 page 多个 useState/ref：改动行数较少，但初始化/同步/自动揭晓共享逻辑容易漂移、难证明持久化次序。
3. 新状态机/全局数据库依赖：当前无需跨页面复杂工作流，增加学习与维护成本，不采用。

## 模块与接口

- `src/lib/game-contract.ts`：公开 HTTP 类型/解码。SessionSnapshot（sessionId/soupId/title/surface/status/messages/questionsAsked/limit/remaining/unlocks/evaluation）；CreationResponse（sessionId/title/surface/limit/unlocks/requestId）；TurnResponse（sessionId/requestId/turnId/state/kind/reply/isFreeReminder/isWin/isReveal/limitReached/remaining/code）。严格身份、整数/布尔、状态关系和数组元素；legacy evaluation 允许 TS07旧字段，但完整字符串/数组也校验，typed分数沿用 helper。公开历史只有 DTO已有字段，绝不引入 privateHostResult/evidence。
- `src/lib/api.ts`：保留 apiFetch/ApiAuthError 兼容；增加 `ApiHttpError(status,code,requestId,retryAfterSeconds)`、`apiJson(path,init)` 和结构化响应处理。401清 token 不清对局，非2xx/非法JSON/断网不同错误。解析失败不能用 `{}` 冒充成功。Turn failed/expired HTTP503 需要在抛一般错误前识别可核验业务结果。
- `src/lib/game-journal.ts`：version1 journal，按 soupId+原level 的编码键保存 PendingCreate `{kind:'create',soupId,level,requestId}` / PendingAsk `{kind:'ask',soupId,level,sessionId,question,requestId}` / PendingReveal `{kind:'reveal',soupId,level,sessionId}`。ID来自 crypto.randomUUID，问题trim后最大500字符。读取校验版本/类型/UUID/路由，不猜损坏内容。写入失败在发POST前停止，显示存储不可用；清除和完成时必须仍为该操作身份，旧请求不能删除新pending。last_session兼容旧格式，但只在有效新会话已核验且当前generation仍有效时写入。完成/揭晓/返回大厅不自动删指针；显式“再来一局”或确认放弃不确定请求才改变恢复目标。
- `src/lib/game-controller.ts`：`GameController(target:{soupId,level}, deps:{request, journal, lastSession, now, newId})`，`getSnapshot()/subscribe(listener)/initialize()/ask(question)/reveal()/synchronize()/restart()/dispose()`。状态只有一个权威快照；同步调用先占 busy，防止双击/提问揭晓交叉。`dispose`失效generation并Abort，自有旧回调既不发布状态也不写storage。Abort不等于服务端未提交。辅助 `src/lib/use-game-controller.ts` 管理路由生命周期和React订阅，StrictMode重入使用持久化原ID；不取消/丢弃journal。

## 状态与恢复次序

`initializing → playing → asking/syncing/revealing → playing/ended`；错误快照保持当前 session/history/pending，带明确错误类别及是否可同步/显式另开。正在初始化、busy、未知提交、无session和ended都不能新提问。

初始化优先同路由pending，再同路由last_session，最后才新开。恢复401/404/410/429/503/断网不自动POST开局，保留指针并显示重新认证/已不存在/旧局不兼容/稍等再试/服务暂不可用/网络错误。没有旧局时先保存create UUID再POST；刷新/StrictMode/重试同一原始soupId/level和UUID。后端 creation_requests 现有幂等返回原局，不需要新查询API。

提问：先保存完整原问题和UUID再POST；成功后完整GET会话同步权威历史/次数，避免乐观气泡重复。丢响应/409/不明503/非法body：保留pending，先GET `/api/session/{sid}/turns/{rid}`。202 reserved保持同步态，有限控时轮询最多3次/每次至少1秒，429尊重Retry-After且停止本轮；提供手动同步，不后台无限循环。查询404先核验原session存在，再允许同ID原body重发；不是new UUID。completed/failed/expired须identity/状态严格一致，才清pending并同步会话。已核验failed/expired不收费但旧请求不能重新执行；下一次显式提问才生成新ID。

揭晓：和提问同一busy入口，pending问答未明确解决时不揭晓。保存PendingReveal后POST现有evaluate（每局一次幂等）。丢响应先GETsession：ended+evaluation恢复；playing后允许重试原session的揭晓，不清局。solved和given_up显示原结果，solved但evaluation尚未创建时允许完成一次合法幂等evaluate，不退回playing。次数用尽/win可在已确认完成提问后自动进入同一揭晓通路，不能重复并发。玩家导航保留已知/未知局，不强行取消服务器请求。

## 站点闸门与列表

SiteGate配置必须HTTP成功且siteLocked为bool；暂时失败显示“服务暂不可用/重试”，不开放children。已存token也要验证列表；错误401显示锁屏，503/断网不抹token或宣称通过。unlock只在列表HTTP2xx且public列表shape有效后保存输入token。身份失败通过现有客户端处理；服务故障只是可重试错误，不推断用户失效。

首页/难度/反馈共享public目录解码和带unlocked查询，HTTP错误/非法JSON明确error+重试，空数据仅真正成功时显示为空；stale response必须generation/controller身份检查后才能set状态。已解锁隐藏汤可以在反馈选择，无本地解锁就不自行显示。复盘免费标记使用服务端isFreeReminder/已确认typed状态，不从emoji猜扣费。移动反馈按钮保留可达性，按页面底部预留或流式入口解决已观察遮挡，不做整站视觉重设计。

## 验证与安全

安装包 pre-flight：React useSyncExternalStore 的 subscribe 返回取消订阅函数、快照必须引用稳定，server snapshot 为同一初始化值。StrictMode 会对同一 hook 实例执行 setup/cleanup/setup；controller.initialize 每次建立新 generation（可重新激活已 dispose 的该实例），旧任务必须比对 generation，不使用一个可能被重新置回 false 的 disposed 布尔值代替。错误状态也发布稳定对象，不每次 getter 创建新对象。

实际 backend/test_server 默认 CORS 只覆盖3000开发地址。永久UI runner必须在测试入口明确 opt-in 自有18081 origin；新增测试专用参数/环境标识只在 Settings.for_test 分支接受固定 loopback origin，不能受任意 URL 配置扩大。原 API-only runner保持原配置与门禁。Playwright serviceWorkers='block'，路由拦截使用安装版 route.fetch/fulfill 的原有签名，丢响应先完成 owned API 请求再模拟失败。

Vitest默认真实fetch禁止，用真实controller/storage/component + 明确合成transport：StrictMode、双击、切汤/难度、unmount、乱序、存储失败、腐坏记录、全部HTTP类别、丢响应、同ID查询/重试、202预算、已结束恢复、失败与未知扣费区分。

Permanent Playwright UI runner使用已实现sterile allowlist构建，独占18081前端和18080自有guarded FakeModel API，verify testing/provider/instanceId，端口已占即失败。全新browser profile，无用户cookie/真实dotenv/模型/生产URL；拦截任何非两ownedorigin。Edge已安装Windows用它，不下载；其他OS已有Chromium可显式选择，不宣称未执行矩阵。真实后端路径用于初始化/刷新/揭晓/扣次；故障与延迟在本地transport拦截注入，记录模拟性质，不当模型质量。UIrunner复用ownedprocess bounded cleanup，失败收尾仍使gate失败，不杀旧PID/外部服务。

ESLint只扫描本项目前端及自有scripts/tests/config，globalIgnores拒绝进入 backend/.venv/.pytest_cache/.cache/.git/out/build；不改变ACL/删除旧cache。typecheck及无dotenv production-page build、完整offline/hashgate全部须实际通过，standalone包/CI OS矩阵/真实Safari仍保留发布门禁。

## 范围、自审与不确定项

审查后I1修订：不是禁止当前路由恢复自己保存的原操作。正常A→B→A导航允许读取A的journal；规范session GET核验原身份后，在generation/journal及本次捕获的last pointer仍未变的条件下接回A。只有当前页面具有此权限，旧回调仍无权限。这个修订替代“指针不是原局就一律拒绝”的解释，不是抢占未知外来pending/原子tab锁。

不增加用户账户、不改变001迁移/基线/HostResult、评分算法或收费；不购买/上传/部署。多浏览器tab没有OS级原子storage锁，不声称全局互斥；后端同ID幂等仍权威，各controller仅维护自有当前路由。跨tab指针变化应被检测并暂停覆盖，而不是自动接管陌生pending。用户明确另开可能放弃可恢复请求，界面提醒后才丢弃该pending；原数据不删除。

自审：A30由journal+controller+StrictMode/乱序测试承担；A31由HTTP分类/初始化恢复测试承担；A32由busy/请求查询/failed-vs-unknown测试承担；A33由SiteGate/目录/反馈/扫描边界承担；C15公开边界保留TS06/09，不替代管理员鉴权及生产验收。UI恢复A28在本阶段完成。无需新的外部决策，未获权事项继续搁置。
