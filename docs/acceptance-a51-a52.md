# A51–A52：有限停止和持久化恢复

2026-10-15，当前398冻结文件/55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32。原A51/A52全文保持；A50真实模型轨迹、A53八个人工参考任务仍HOLD。本次使用executing-plans接续已批准计划、verification-before-completion核实际回执；不重新实现已验收功能、不新派审查、不运行已通过的全套门禁。

## 已有同源断言（不是本次重跑）

以下12模块本次完整读取；精确classname核[当前完整XML](../.cache/a46/review-final.xml)及冻结字节。156现有PASS/0skip已在3014后端/3515离线内，不能再相加。XML SHA256=d297ae1a7a0628f0c1e9120ffcc510086c4cedaa3b21c65aebd10cb94f78ba90。

| 模块 | 已有通过 | 实际边界 |
| --- | ---: | --- |
| [agent_store](../backend/tests/test_agent_store.py) | 36 | SQLite排队、首启、接管、预算/审计事务及幂等 |
| [agent_decisions](../backend/tests/test_agent_decisions.py) | 24 | 调用前预留、10次上限、纠错、未知尝试不退还 |
| [agent_stop](../backend/tests/test_agent_stop.py) | 16 | 最小状态、取消、原截止时间、终态与审计原子性 |
| [agent_tool_retry](../backend/tests/test_agent_tool_retry.py) | 4 | 同工具最多一次重试、持久化计数、完成结果重放 |
| [repair_agent_loop](../backend/tests/test_repair_agent_loop.py) | 9 | 无效/失败/外来动作、有界循环、最后额度不多发调用 |
| [agent_recovery](../backend/tests/test_agent_recovery.py) | 4 | planned/算完未提交/完成历史、9模型7工具剩余1/1 |
| [agent_loop_races](../backend/tests/test_agent_loop_races.py) | 12 | 阻塞模型和工具的撤权/取消/接管/关闭、候选恢复 |
| [agent_heartbeat](../backend/tests/test_agent_heartbeat.py) | 12 | 30/60秒闭合租期、续租不延长180秒 |
| [agent_worker](../backend/tests/test_agent_worker.py) | 10 | 独立心跳、SQLite队列、在线优先、10秒原生等待 |
| [agent_shutdown](../backend/tests/test_agent_shutdown.py) | 12 | 残留名额、心跳故障、线程拒绝、lifespan收尾 |
| [agent_admission](../backend/tests/test_agent_admission.py) | 3 | 实际准入竞争、清理未知阻止下一任务、过期零调用 |
| [ts14_review_regressions](../backend/tests/test_ts14_review_regressions.py) | 14 | 锁内取消/关闭、候选与finish回滚、实际派发前重查 |

## A51：次数不是现金，也不是provider收到请求的证明

[实际循环](../backend/app/agents/repair_agent.py)先原子写入decision intent/预算/审计，再经共享gateway派发；工具同样先plan。审计失败时三个一起回滚；已成功预留但未知是否发出不退款。模型每次gateway max_attempts=1，纠错与工具重试另占新预留，全局10模型/8工具；同一纠错或工具重试episode最多一次，换正文不能刷新原episode。

两个无效模型输出→model_output_invalid转人工；工具两次真实计算失败→tool_failed；外来范围动作不执行；重复operation key/并发四次只写一份intent/一次预算，改正文或借其他run冲突；不同新动作反复循环仍受10/8总上限，不宣称存在能判断所有语义循环的检测器。9/7恢复案例实际有七次相同取Trace动作，保留全部历史，不靠删历史腾预算。

首claim才写firstStartedAt及+180秒deadline，在线忙时queued仍未开始。续租/接管原checkpoint完全保留；开始后的调用、等待、重试及停机消耗同一原期限，过期任务直接needs_human、零新增调用。达到10次后已存的有效finish或剩余工具仍可完成，不凭空发第11次模型请求。

取消/撤权/接管/关闭/心跳失败使旧写入失效；实际SQLite等待BEGIN及最后commit均有独立反例，不能只检查入口。候选写入和finish在锁内取消时整事务回滚，安全门禁不被模型自称成功替代。适配器构造阻塞后、真正派发前重新检查原预留和权限，已撤销数据不再发出；对已经发出的远端内容不能撤回。

关闭先停止准入并发取消信号；blocked本地调用未退出时cleanupConfirmed=false、active_agent仍1，第二任务留queued。适配器close失败即使调用线程退出仍保守占位，后续任务不再启动；只有真实退出且清理确认才释放。应用默认Agent关闭、003不足不建线程/网关、不隐式迁移。10秒独立心跳测试用事件推进，另有原生wait(10.0)断言；不是假称真实远端推理已强停。

## A52：三个点的真实独立进程补验

已有恢复测试是在同一测试进程内重新drive持久化账本。本次额外[缓存探针](../.cache/a46/a52_process_recovery_probe.py)实际用固定本地Python `-I -B` 启动另一个PID，新的Runtime/AgentStore重开同一自有临时SQLite；剥离provider/auth/trace环境、父子进程均装原NetworkGuard与数据路径护栏，不使用真实模型/用户数据。

| 父进程已提交后停止推进的位置 | 新进程实际结果 |
| --- | --- |
| 模型intent为planned，未有结果 | 原未知intent保留；另预留一次模型纠错→转人工，模型总2/工具0 |
| 已算完get_turn_trace，但未提交tool结果 | 原planned/空结果保留；新工具尝试重算并提交，再finish→转人工，模型2/工具2 |
| candidate已经保存但未finish | 原候选和两个步骤不变；新进程finish→awaiting_review，同candidateId且仅一条pending候选，模型1/工具2 |

三个都保留原截止时间和完整原步骤前缀，接管使用新lease；父进程旧lease再心跳全部拒绝且数据库dump不变。候选场景使用原声明为synthetic的存储报告fixture，不冒充实际回归/真人金标，更不批准或发布候选。独立进程确实重新加载落盘数据；这里用受控lease到期时钟，不是杀死OS进程、断电或远端网络exactly-once演练。

实际命令：`backend/.venv-ts01/Scripts/python.exe -I -B .cache/a46/a52_process_recovery_probe.py`。原生2c63c7 EXIT0/[日志](../.cache/a46/a52-process-recovery.log)3 passed；[XML](../.cache/a46/a52-process-recovery.xml)3/0失败/0错误/0跳过、4.670秒，SHA256=893384d481ca6aae673bb68d101d9bab42dd42e7b3e85f2d52e5682008949a11。探针SHA256=9d4b0abc0845004d77ed261e35bb465683d3952b334da18e871b969dd287b551。anyio预导入产生一条assert-rewrite warning，未关闭护栏；本次3项不是永久套件新增，不把3515改为3518，也不与A49三项混加。

既有9/7案例真实持久化后只剩1/1；完成结果重放不重扣、不再次执行；不明模型/工具意图保留旧记录并耗新预算。过期原deadline、取消/过期续租及旧owner完成写入均拒绝。当地预留数、provider接收数及可能的网络重复调用明确不同。

结论：A51/A52本地预算、停止、心跳与三个跨进程恢复点已有具体证据。A50/A53真实模型/人工参考依赖不因此解除。继续A54–A60与原C/IR/OV+SG逐项审计，不暂停整体目标、不要求阶段确认。
