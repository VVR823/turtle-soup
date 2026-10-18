# 2026-10-16 剩余前端路径核对与补验

本轮按用户要求简洁执行，只补必要边界，不以覆盖率数字代替验收。没有启动自动续跑、Loop、heartbeat或调度。

## 新执行结果

新增2文件5测试，业务代码未改：

- [日期输入测试](../src/components/MetricsPanel.reachability.test.tsx)：10000年及275761年的值可保留在测试DOM的 datetime-local 控件中，但 Date.parse 不支持；点击查询后安全提示且不发请求。只证明DOM/组件行为，不冒称新跑真实浏览器。
- [导出尺寸测试](../src/lib/metrics-export-size.test.ts)：100组、最长题目ID，分别包含JSON转义字符与Unicode，标识原样保留；额外计算当前结构的保守大小上界。没有修改TextEncoder或缩小覆盖范围。

首次新测试3PASS/2FAIL是标签写错，原日志[保留](../.cache/manual9-acceptance-20261016/targeted.log)；修正测试标签后[5PASS](../.cache/manual9-acceptance-20261016/targeted-fixed.xml)。不是产品缺陷或修复。

最终完整前端 **45文件、722 PASS/0 FAIL/0 ERROR**，北京时间12:38:13–12:38:54；类型检查（禁用增量写入）与两个新增文件lint均退出0、空日志。[完整XML](../.cache/manual9-acceptance-20261016/frontend.xml)、[日志](../.cache/manual9-acceptance-20261016/frontend.log)、[退出回执](../.cache/manual9-acceptance-20261016/exits.json)。

与上轮完整覆盖逐文件、逐branchMap、逐结果匹配，分母2032及全部映射不变，新增命中 MetricsPanel.tsx:22，旧命中无丢失。分支 **2006/2032=98.72%**，仍有26未命中；语句1932/1964=98.37%，行1398/1409=99.21%。[结果与核对](../.cache/manual9-acceptance-20261016/accepted-results.json)、[26条精确清单](../.cache/manual9-acceptance-20261016/frontend-gap-inventory.json)。

## 上轮8项优先核对的处理结果

“静态解释”只描述当前代码与正常依赖下的调用顺序，不等于用测试走到了该未命中分路，也不构成豁免。保留所有守卫及原100%目标。

| 项目 | 本轮结论与证据 |
| --- | --- |
| MetricsPanel:22 异常日期 | 新增2项实际命中并通过，已补齐该分路 |
| metrics-contract:191 导出尺寸 | 当前闭合结构最多100组，单组保守预算2048字节，固定部分实际保守上界7675字节，按16384字节计；总预算221184字节，小于524288。保留512KiB保险，不伪造无效字段或扩大合法条数凑命中 |
| game/page:133 同步显示 | 当前控制器唯一设置syncing的路径同时设置非空error，因此前面的error已使OR成立，后面的syncing结果会被短路；不是同步功能缺测的直接证据 |
| game-controller:144 接受会话 | 当前调用点先检查请求代次/所有权，再同步进入acceptSession；中间没有异步等待。保留入口重复检查；既有“dispose后迟到恢复不能发布或写结果标记”在本轮完整测试中通过 |
| game-controller:159 暂停规则 | 当前调用先检查会话/请求归属，同步调用holdSuspended，方法内部再次检查代次。正常依赖下无异步间隔；未来引入可重入存储/解码依赖应重新核对 |
| game-controller:185 重开失败 | await initialize自身捕获正常请求/存储失败；restart自己的catch主要保护等待前的同步操作。未通过抛错的订阅回调或私有状态制造过期catch；保留守卫，不能宣称精确分路已测 |
| MetricsPanel:103 失效超时 | 改筛选会取消timer并abort；换令牌/卸载由effect清理；回调中的current是额外检查。本轮既有超时释放、忽略abort的迟到结果、令牌变化和晚导出隔离测试通过；精确失效timer分路仍未命中 |
| SiteGate:46 清理归属 | active仅由effect建立并在cleanup清除，React先清理旧effect再建立新effect，unlock复用当前控制器。当前正常调用顺序不让旧cleanup清掉新控制器；既有卸载后迟到配置/口令及验证失败隔离测试本轮通过 |

导出[保守上界回执](../.cache/manual9-acceptance-20261016/export-bound-proof.json)与尺寸测试同时保留。大小结论针对**解码后的当前闭合输出**，不是声称原始网络响应无法很大。schema-3观测对象字段更多，计算同时包含unknown分支的reason作为结构超集；数值按最多24字节、枚举按64字符、题目ID按200码点每个最多6字节、版本按67ASCII字符计。固定部分使用完整processAudit结构，最终仍小于16KiB。

## 尚未签收的项目

前端26条仍按准确位置保留：上轮19条静态较低优先级，加上表7条带前提的静态解释/边界说明。**没有将它们记为已命中或豁免，也未据此签收原100%目标。** 它们不应被直接解释成26个功能故障。

后端未重跑，沿用上轮44项评分复验及历史去重集合3069PASS/14SKIP、原110文件3132/4032（剩900）的证据；未逐项风险审查的后端分支继续明示待核。[上轮风险报告](local-acceptance-risk-triage-2026-10-16.md)。

整体仍欠A42正式来源/独立人审/holdout封存、A46真实免费模型三系统对比、可克隆完整版本、CI/其他平台，以及原清单的人审/生产恢复/公开发布等证据。用户此前明确这些模型及人审材料尚无，本轮不重复索要、不伪造结果。正式60项分布不变：限定本地工程通过47、未通过1、进行中但停止2、未开始3、待核实7。

## 保护与停止

原423项输入逐文件哈希不变，仅新增2测试形成[425项身份](../.cache/manual9-acceptance-20261016/final-source-identity.json)。原239运行文件/HEAD/index由[开始](../.cache/d18/manual9-before.json)和[结束](../.cache/d18/manual9-after.json)确认不变；分支仍为codex/ts02-storage-foundation、HEAD仍c5765b68cb251a7c566e76e2887d335d6ed6b285。未提交、切分支、覆盖旧修改、接触真实模型或生产。

[最终状态](../.cache/manual9-acceptance-20261016/final-verification.json)。本轮已结束，无自动续跑。按context-save结构保存项目内证据，整体最终验收尚未完成。
