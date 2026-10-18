# A57：统计口径、分页导出与合成测量

2026-10-15。原要求逐项核对，不以页面存在或总测试绿色签收真实流量/模型质量。当前398冻结源码摘要55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32；本次仅补映射及两份当前测量回执，无应用/永久测试修改、无第二审查或整套重复运行。

## 当前已有测试证据

完整读取下列10模块，精确classname核[同源完整XML](../.cache/a46/review-final.xml)：252现有PASS/0skip，含于3014后端/3515离线，不再相加。XML SHA256=d297ae1a7a0628f0c1e9120ffcc510086c4cedaa3b21c65aebd10cb94f78ba90；a57402/b56878实际退出0核计数及源码绑定。

| 模块 | 已有通过 | 原断言范围 |
| --- | ---: | --- |
| [metrics_contracts](../backend/tests/test_metrics_contracts.py) | 48 | 7/31天、50/100、闭合游标、完整UTF-8导出 |
| [metrics_http](../backend/tests/test_metrics_http.py) | 35 | 独立admin、no-store、限流/错误、100/101组导出 |
| [metrics_queries](../backend/tests/test_metrics_queries.py) | 56 | 真轮次/尝试区别、来源/排除、同快照、清理/缺口 |
| [metrics_query_plan](../backend/tests/test_metrics_query_plan.py) | 4 | 105组分页、真实EXPLAIN、两条聚合SQL/目录批量校验 |
| [metrics_benchmark](../backend/tests/test_metrics_benchmark.py) | 7 | 200/1000/5000、20样本/P50/P95、序列化/资源/失败不造数 |
| [metrics_missing_source](../backend/tests/test_metrics_missing_source.py) | 15 | 未启005/缺来源为unknown/null，不当零失败 |
| [metrics_migrations](../backend/tests/test_metrics_migrations.py) | 30 | 显式004索引、原001/002校验不改、逐故障原子性 |
| [metrics_baseline_failures](../backend/tests/test_metrics_baseline_failures.py) | 6 | SQLite真实中断/永久故障归类及连接清理 |
| [post_publication_metrics](../backend/tests/test_post_publication_metrics.py) | 50 | 四运行状态/完整case分母、出生证明、批量/同快照 |
| [post_publication_metrics_scale](../backend/tests/test_post_publication_metrics_scale.py) | 1 | 204合成统计行+5000审计、20次完整读取及started索引 |

## 固定窗口中的业务数来自哪里

[实际reader](../backend/app/metrics.py)的9计数是：会话created_at、成功计次turn completed_at、每条HTTP尝试审计、反馈提交、任务/候选创建、批准/拒绝审核动作、候选发布动作。实际测试有8条消息但只有2个成功计次轮次、同轮4个HTTP请求尝试；重放不再计轮次，reminder/system_error不算成功计次。发布同时有通用rule和candidate审计，只计candidate发布一次；拒绝不算成功修复。

半开[start,end)且跨边界turn按完成时间；任务六种当前状态和候选四种当前状态都入相应创建队列分母，分母0的发布比例null，不是0%或准确率。来源按实际observed版本，不误用修复base或当前指针；发布后复查才按publishedRuleVersion筛选。后续状态不是窗口end时刻的历史快照，不承诺翻页冻结历史。

主计数只取显式real；test/synthetic/legacy/unknown各有独立排除计数。合成夹具为了测试生产过滤可标real，但从不冒充真人流量。缺审计/分类冲突/重复JSON键/ID或时间不匹配不变成合法real；未完整关联的real保留unscopedReal，筛选前已计算，不猜当前版本。不输出用户数/唯一人数。

公开分组维度需整个合法题库及历史release的内容寻址和绑定验证；坏inactive目录503，任意登记字符串不变成公共ID。page/export不含会话/turn/feedback/run/candidate/request持有凭据或摘要、问题原文、标签、私有诊断。用敏感sessionId冒充soupId过滤422，错误也不反射输入。

## 分页、完整导出和读取资源

默认服务端结束时间和前7天（早epoch夹0），最大31天；默认50/最大100，整数边界/重复参数/未知字段/NaN/GET body拒绝。游标为规范base64url，只含窗口/过滤/limit和公开分组键，绑定原查询；105组实际50/50/5无重复无遗漏。每请求自己的短快照，summary和groups之间WAL写入可提交、该响应仍读同一快照，下一请求才见更新。

导出是单次新快照完整聚合，不拼接翻页；100组成功/101组409整份拒绝，512KiB按UTF-8字节守卫，不截掉尾部再complete=true。参数不接受limit/cursor，固定附件名/no-store。单测用精确边界与降低测试上限验证字节拒绝，不假称空导出实际达到512KiB。

专有SQLite query_only/BEGIN读事务，schema/catalog/summary/005观测/group全部共用3秒deadline，每条SQL前剩余busy_timeout缩短。真实EXPLAIN命中会话/轮次/反馈/任务/候选/审计时间索引；基础两条聚合SQL，005一条观测批次且每publication只验证一次，不逐行读私人context/messages。必要基线SELECT真实SQLITE_INTERRUPT→metrics_busy、永久坏表→metrics_unavailable；五类清理故障都尝试clear handler/rollback/close，安全503不泄露路径。

004只显式加索引/报告，不回填历史；默认迁移仍001，旧阶段读取不自动迁移/启动Agent/模型。coverage显示启用前窗口、当前进程fallback/drop/permanentGap；进程状态不是指定窗口的丢失历史。来源缺失为unknown，保留已知业务数；fallback恢复后才从缺口变实际审计计数，不补造“从未丢失”。

## 005发布后观测不混入真实业务或隐去失败

四个run状态passed/failed/incomplete/pending闭合observed分母，pendingExpired只是pending子集；全部planned包含未尝试case，counterexample/error/unsupported/notAttempted各自保留。窗口按plan startedAt，不按较晚finish；过期按本次实际服务器时间，不以窗口end冒充现在。

005前schema_5_required、必要出生证明/账本坏source_unavailable都是unknown/null；无法验证的样本不能被筛选隐藏后当0失败。实际四例队列保留1成功/1反例/1不完整/1待完成；真实计数0，test分母4；额外unknown另列。撤回当前语料不删旧出生证据，但不授权新运行。来源/操作/审计批量验证、不可变记录完整性、查询同快照/固定SQL数量与3秒预算均有实际断言。

## 本轮当前源码测量（不引用历史跑分充当前）

[既有测量器](../backend/app/scripts/benchmark_metrics.py)已完整读；[缓存捕获器](../.cache/a46/a57_current_benchmark.py)先装原NetworkGuard/数据护栏、去provider/追踪密钥，独立进程把临时根限制.cache/a46，工具只创建/清理自己唯一目录。原生1449/b0a461 EXIT0，结果[完整JSON](../.cache/a46/a57-current-benchmark.json)，SHA256=32a115adb0c60e6b923f062014100d61c29fddf38e436f9feeb337fa2d98074f；捕获器SHA256=921467f9a67500e03570ff6419173ec8675a7783556384ad04bcf3a0a8b5ff3d。

环境实际Python3.13.13/SQLite3.51.2/Windows11 build26200/20逻辑CPU。固定200会话/1000turn/5000typed审计行，3预热+20样本；独立源SQL复核real-tagged计数50会话/150成功轮/1000尝试，各排除类也完整核对。schema4的发布后复查明确unknown/schema_5_required，不冒充005真实观测。

| 当前测量 | P50 ms | P95 ms | 范围 |
| --- | ---: | ---: | --- |
| 基础完整reader | 475.5964 | 499.6982 | schema/catalog/汇总/分组/完整JSON序列化与闭合回读 |
| 005混合观测完整reader | 484.3337 | 495.1458 | 204统计行（原4+200复制）+5000测试审计，完整JSON与回读 |

基础测量资源：CPU31062.5ms、Python分配峰值9770146bytes（非RSS）、DB5332992bytes、WAL0；cleanupConfirmed=true，原临时目录确已清理。包括tracemalloc开销，不是生产SLA/并发容量；同SQL索引前后批次是独立范围，不是旧reader性能对比，不据小幅波动声称提速。

005数字来自本轮仅重跑原有单个规模测试以保存完整样本输出：原生3685/596610 EXIT0，[日志](../.cache/a46/a57-observation-scale.log)SHA256=97fe6645836590912cc2d6f57ed97f7e05234967b75f8d2159a29d73ccf0b6ac；[XML](../.cache/a46/a57-observation-scale.xml)1 PASS/0skip、17.441秒，SHA256=6e33a3e25acd4456c9ba11f0f167401bc6df93f46a8372962de72d5827e1dbc7。20样本均<3秒、每个JSON3165bytes；真实EXPLAIN命中idx_post_publication_started，每read一观测批次/一publication来源验证，不是204次验证。164test/40unknown分开完整分母、主real观测0。200复制不是200次实际执行；此测量没有单独采集CPU/RSS，不能借基础报告资源嫁接给它。

b56878实际退出0，重新排序全部样本独立核两报告nearest-rank P50/P95与20长度、基础actualSummary=expectedSummary/清理。不是新永久测试或3515之外新增通过数，不重算总门禁。历史TS16测量环境/范围不同，原报告不覆盖、不当本轮数值。

## 页面消费边界

完整读[统计DTO](../src/lib/metrics-contract.test.ts)、[观测DTO](../src/lib/metrics-observation-contract.test.ts)、[面板](../src/components/MetricsPanel.test.tsx)，属于当前395前端aggregate，不编造各文件重跑计数。按钮手动查询无自动轮询，默认7天；令牌/筛选变化和卸载清空数据、fence迟到结果/下载；fetch和body分别10秒超时释放按钮，无法取消的迟到结果也不能恢复。下载绑定返回窗口，移除分页并撤销blob；无task分母不显示成功率。

当前35UI中[真实owned统计流程](../tests/ui/admin-metrics.spec.ts)有105合成组分页/完整27组下载/测试排除/375px局部键盘横滚；[另两条005手机展示](../tests/ui/post-publication-metrics.spec.ts)是明确响应夹具，不冒充后台真实发布后采集或真人数据。真实对照/质量仍未具备。

结论：原A57的本地统计口径、窗口/分页/索引/批量、合成规模测量、排除/缺口与隐私导出已有对应证据。此处不签生产流量、模型准确率或全目标。继续A58–A60及原C/IR/OV+SG；保持原数据、零付费和独立外部门禁。
