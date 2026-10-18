# A18–A20本地断言与证据核对

CURRENT 2026-10-15：A20剩余缺配置/端点拒绝分支已补直接验收：[固定20操作/100项真实ASGI拒绝矩阵](acceptance-a20-admin-matrix.md)实际退出0、业务表行数不变、Fake调用0、临时合成库正常关闭；当前398零漂移、原239/Git保护不变。A20三个本地拒绝/配置断言现有行为证据；不是所有业务/生产安全认证。下方“尚待旧Trace/其余缺配置分支”的段落保留为本次矩阵之前的核对历史，不再作为当前未完成指令。

2026-10-15续核：当前398/55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32完整XML review-final.xml实际3028/0failure/0error/14skip（3014通过），SHA d297ae1a7a0628f0c1e9120ffcc510086c4cedaa3b21c65aebd10cb94f78ba90。下文bb0ab4df/3012/3513是前一冻结身份历史，当前完整离线总数为3515，不把逐模块成绩相加。

本轮完整读并核同当前指纹的test_request_guards（17）、test_feedback_http（19）、test_candidate_review_http（37）、test_metrics_http（35）共108条既有通过测试；它们是各模块总数，不冒充108条独立鉴权组合。新增已核行为：

- 管理guard：无/空/错误/站点凭据/非ASCII都不能代替admin；缺配置503；正确站点与管理凭据分离。body边界、坏长度与CORS另有真实断言。
- 反馈列表：无/站点/错admin均401，缺管理配置503；玩家不能传入safeForModel/status/version。隐私授权需独立admin、显式人审声明与CAS，且不会调用模型。
- 候选六路由list/detail/approve/reject/publish/rollback：每路由乘无/站点/错admin共18组合均401且业务状态不变。未配管理token的列表/详情/approve均503；批准、发布、回滚实际分开及幂等重放，没有自动发布。
- 统计页与export：每路由乘三种无效凭据共6组合401且no-store；每路由缺配置均503/零模型调用。旧schema也不自动迁移；导出不是绕过鉴权的另一路。

继续核对后，test_agent_http已完整读并逐字节绑定同当前398指纹：XML实际39条通过，包含无/站点/错admin启动401且没有run，已存在run的status/cancel站点凭据401且保留queued，三类路由错admin拒绝的固定audit模板，缺admin时站点token仍503/不创建run；调用者不能传工具权限、付费模型、approve等字段，也没有借Agent运行端点新增approve/publish。该模块使用真实本地gateway占位配合受控合成model，不是线上模型质量证据。

A20仍不签全部：尚待完整核旧Trace读取/管理边界、其余admin路由及反馈approve/reject所有缺配置分支；共用guard不能代替每个端点的行为证据。现已补Agent映射，不再把它列为完全未读。继续补剩余映射，不因这次A46通过而自动勾原清单，也不重跑上述已通过的既有测试。

2026-10-15。对应原验收清单，不追改原勾选，不认证生产代理配置或全部管理员端点。与当前398/bb0ab4df…完整六门禁相同的8个source/test文件已逐字节核实；实际task4-whole.xml SHA3158c026324a625b0f95ed64eac0de94a1987a74239d4b5426c12778834d4295，3026/0failure/0error/14skip。

## A18：独立窗口与一请求一次记账

实际test_rate_limit_windows九项、test_rate_limit_dependencies七项均在本次XML通过（已包含于3012后端，不相加）。FakeClock按十个分钟各30次构成300/hour：600时拒绝/retry3000，3599.999拒绝、3600放行；一分钟59.999拒绝/retry1、60放行。40并发竞争实际仅30准入；identity/endpoint/policy彼此隔离，满active-key容量不忘记已有消费，60秒后回收；hour拒绝时minute不被部分消耗。真实隔离HTTP恰好允许30而非15，第31次429/Retry-After60且requestId合法；同scope重复dependency只记一次。

源码rate_policy在同Lock内裁定全部policy后再append，不拒绝到一半计数；rate_limit以method+route、policy记request.scope checked集合，未准入不加入。未测试跨进程共享限流，不能从此页宣称全网站多worker限流或生产容量。

## A19：可信代理与32KiB门禁

实际test_proxy_identity十项与以上HTTP七项同XML通过。未信任来源伪造X-Forwarded-For无效，loopback不默认可信；显式CIDR右到左取首不可信hop，坏hop/长链退回真实peer，IPv6统一表示；全信任/非法CIDR配置拒绝。真实HTTP body32768成功、32769返回413且没有创建session，429提供Retry-After和固定业务code。源码request_guards仅缓存有界body，在路由副作用前拒绝，不吞后续断开事件。

这是当前应用层隔离规则/行为证明，真实生产前置代理、TLS和部署拓扑仍待核验。

## A20：已核部分，不签全部

实际test_audit_admin36项、test_feedback_privacy12项均在同完整XML通过：审计读/status/recover的无凭据/普通site-token/错误admin均401，未配置admin503；不能回显密钥或任意恢复路径。脱敏许可与approved分开、CAS、防自动授权/额外cloudEndpoint、原文保持、业务审计原子回滚和显式撤销有真实隔离断言，FakeModel零调用。以上与A18/A19共74条映射全部是既有3513内成绩，不重跑/不相加。

尚未在本页逐断言核完整feedback/Trace/metrics/Agent审批发布每个端点和全部管理配置分支，所以不据36+12或共用require_admin_token源码条件签整A20。后续须逐模块补齐实际HTTP断言及当前源绑定；与独立A46审查不重叠，不把范围缩成已核部分。

来源：[当前完整XML](../.cache/a46/task4-whole.xml)、[窗口测试](../backend/tests/test_rate_limit_windows.py)、[HTTP边界](../backend/tests/test_rate_limit_dependencies.py)、[代理测试](../backend/tests/test_proxy_identity.py)、[审计管理](../backend/tests/test_audit_admin.py)、[隐私许可](../backend/tests/test_feedback_privacy.py)。原18阶段/A60/C24/IR24/OV+SG保留，所有真实模型/人审/生产/公开边界不变。
