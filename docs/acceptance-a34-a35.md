# A34–A35 尝试审计、事务与未知用量

2026-10-15。当前398文件身份55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32。完整读取下列11个现有测试模块，逐文件匹配冻结源并从[当前完整XML](../.cache/a46/review-final.xml)核对236项，0failure/error/skip；包含在3014后端/3515离线通过中，不是新增236项，也没有重复运行门禁。

| 现有模块 | 当前实际通过 | 原断言/行为 |
| --- | ---: | --- |
| test_audit_http | 19 | 相同请求两attempt一turn，缓存/拒绝/失败/重放，外部日志失败不改变已提交结果 |
| test_audit_transactions | 12 | 开局/限次/finish/过期/评估的完整事务回滚与业务事件幂等 |
| test_audit_migrations | 27 | 001字面量固定、默认只001，显式002/独立失败回滚/旧库不自动升级 |
| test_audit_usage | 15 | 真实gateway+MockTransport观察合法/部分/未知/非法usage，重试/迟到密封 |
| test_audit_contract | 62 | 严格冻结DTO、ID/时间/字段与16KiB边界，unknown与真实0分开 |
| test_audit_fallback | 30 | SQL/文件故障、1000条/1MiB、实际IO容量8、恢复/坏尾/永久缺口 |
| test_audit_context | 11 | copied-thread隔离、同request不同event、晚到不能改旧快照或别的请求 |
| test_audit_admin | 36 | 独立权限、缺口状态、真实积压恢复、分页/过滤/坏镜像行拒绝 |
| test_typed_trace | 4 | 原诊断入口按kind/source计类；失败只留安全哈希与不完整标记 |
| test_ts09_review_regressions | 18 | 已有唯一审查永久回归：迟到IO失败、缺口/坏文件、cursor、长旧ID |
| test_request_disconnect | 2 | 实际ASGI断开后的非收费失败/密封attempt，阻塞worker不假释放 |

XML SHA256 d297ae1a7a0628f0c1e9120ffcc510086c4cedaa3b21c65aebd10cb94f78ba90，3028项/14原有明确跳过；本表236项均无跳过。此轮作者做原断言映射，不称新独立审查；原TS09审查及一次修复记录保留于[阶段状态](ts09-status.md)、[处置](ts09-review-resolution.md)。

## A34：attempt和业务提交不混为一谈

[ASGI审计](../backend/app/audit_middleware.py)在HTTP外层独立生成eventId，仅观察协议状态，不抢读body或解析响应正文。同requestId重发的真实HTTP测试要求两条不同eventId、同session/turn、前者replayed=false后者true；业务turn_committed仅一条，questionsAsked=1。重放事件charged=true记录原turn收费决定，不代表本次又收费。开局/恢复/揭晓也绑定实际ID，反复揭晓只有一个业务evaluation_created。

确定性缓存与重复请求都不制造modelCalls；鉴权401/限流429/坏body/非法JSON/体积413/未知路径404/模型503分别落attempt。无法确认response start时statusCode=null/outcome=error，不补造200；原URL/query/headers和异常原文不进入安全事件。ASGI断开后原turn failed/model_cancelled、charged=false，仍阻塞的实际worker占位；晚到答案不扣次、不改已经存下的attempt文本。

[游戏事务](../backend/app/game_store.py)将必要业务audit与session/messages/count/result/evaluation置于同一BEGIN IMMEDIATE连接内。[业务插入](../backend/app/audit_store.py)要求conn.in_transaction及已注册002 checksum；业务事件不允许借独立attempt fallback假装已提交。五类注入逐一比较完整业务表快照不变；缺audit表不能半开新局，公开仅503/audit_unavailable。metadata只在commit之后发布，回滚不能被attempt写成已收费成功。

相反，已经commit后独立attempt数据库与fallback都坏，原200仍返回，相同UUID重放仍只扣一次；有界RAM/gap明确反映缺口，不能重新问模型以“补日志”。store意外抛错也不把已提交答案改成失败重试。

## 有界降级、恢复和完整性

本地永久回归实际覆盖默认1000条上限与1MiB上限，不能覆盖旧记录腾空间；单event最多16KiB。数据库故障写验证后的安全fallback；文件也坏时RAM最多同预算且明确未持久化，超量dropped/permanentGap。stderr只固定错误分类与关联哈希；注入的玩家/凭据/路径/异常文本不会外泄。

恢复以eventId加完整payload去重：同ID异内容冲突保留、不覆盖；SQL实际commit失败不清文件，commit成功但清文件失败可再次恢复只计duplicate。坏JSON/UTF8/部分尾行/超大旧文件保留原文并保持缺口，不拼接下一行伪装合法。坏/重复键/非零丢失量的gap标记不能显示complete；可用时gap侧车与runtime_meta均保存。opaque文件不阻断独立合法RAM恢复，仍保留文件哨兵/不完整状态。

IO在进入executor前限制8个实际任务，SQLite连接在任何WAL/SQL前设250ms timeout。HTTP等待超时/取消不是底层worker退出；关闭只报告实际residualJobs，不冒称强制取消文件IO。迟到insert/close/终态worker失败也由原owner留缺口，不把原异常交asyncio输出。启动或显式admin恢复有界处理；SQL故障的8条积压只试一次连接，不变成1000次同步重试。

管理员status真实显示permanentGap/dropped/coverageStart/fallback/RAM/activeIO，积压恢复HTTP202仍pending不冒称完成。默认/未知覆盖起点不宣称完整；historicalAttemptsBackfilled=false，不从旧turn/Trace捏造历史HTTP统计。DB、磁盘和进程同时失效仍可能丢未持久化RAM或gap：这是公开限制，不承诺每次请求永远可追溯或跨进程文件锁/断电耐久性。

## 001与002：不将当前M2应用倒退成阶段M1

当前27项迁移回归实核001 checksum=e703a6f4ce5f102d0da973118dee3f08486b2e1f0c94a16ff5449acafe23f69b、BASE_SQL+CORE_SQL digest=abb9cd5e98f7625e3a123186167c049afb9a714b94184f67c2c67e8246006137；默认migrate/verify仍只要求001，不出现feedback/audit未来表，显式002新增与失败回滚独立，保留原报告/原数据/基线。已有001应用启动先验证再WAL，明确拒绝且源DB/WAL/SHM不改；新空应用才显式建002，不自动迁移真实旧库。

原M1事务/Trace是分阶段历史验收，不把“当前M2可以写schema001游戏”当兼容要求。[原TS04 ledger](superpowers/plans/2026-10-07-ts04-progress.md)记载在既有001 response_json中保存绑定结果、不引用未来表和原唯一审查修复；本次实际读[历史88项XML](../.cache/ts04/review-green.xml)为88/0failure/error/skip，SHA256=b6260ddd314b9ea51c6d7cb54fa8549a63cec98d7802143433cb29c78d31ee0e；[历史整后端XML](../.cache/ts04/review-full-gate.xml)为451/0failure/error/9skip，即442通过，SHA256=e44ee8b1e7aa491ec0913d2a0ccf419826aa18cece13398f31543461876e9712。这是原阶段证据，不冒充当前源重新执行M1，也不与3515相加。XML不单独证明历史源码字节，阶段ledger/审查记录的身份边界保持原样。

[现有Trace入口](../backend/app/trace_logger.py)仍默认关闭；开启的私密诊断可含问题/展示回复，不是脱敏attempt或完整历史统计。必要审计不受ENABLE_TRACE开关关闭影响；诊断写失败只固定diagnostic_trace_failed+session hash，collector记metadataTruncated，不重问/重扣。原M1独立阶段已验收，不为原断言映射重建旧分支或改写001迁移。

## A35：只保存实际观察到的安全元数据

程序绑定request/session/turn、HostVersions/source/kind/cacheHit/收费决定、有限耗时与安全errorCode；创建/旧恢复不知道旧engine/normalization时保留unversioned。错身份绑定原子拒绝并留metadataTruncated；长合法旧session ID可恢复但审计无法安全表达时省略ID、明确缺口，不能截成另一身份。必要evidence ID有限并带原数/截断标记，不放原reply/reasoning或任意metadata。

usage严格区分known/partial/unknown/invalid：provider不提供时input/output/total各null，明确给0才是0，字符串/bool/负数/NaN/无穷/过大值不冒充合法计数。任一实际调用相应分项未知时汇总仍null，保留已知单次分项，不推算另一次。重试记录两条真实调用且adapter清旧usage；未dispatch的预算拒绝零modelCalls。MockTransport返回usage异常也不把合法答案改成system_error。

配置身份不让响应任意model_name覆盖；Injected AIMessage只取受控usage_metadata，不存response_metadata密钥。超时后封存started/unknown，迟到usage不能修改旧记录或污染下一请求；observe hook故障仅标metadataTruncated，不改变合法游戏答案。这些都是本地Fake/Mock/真实gateway执行，不是实际云供应商计费验证。

结论：A34–A35当前M2行为、原001独立迁移与已验收阶段历史边界已映射；不新增代码/永久测试、不新派审查、不重复全门禁。跨OS/生产耐久性、实际模型用量与真实人审仍不由离线证据签收。下一步A36–A40公开边界、反馈CAS/导入及发布/许可冻结；[A29交叉核对](acceptance-a22-a29.md)已确认剧情评分不进入质量统计，同时保留全部样本分母，不新增筛样。
