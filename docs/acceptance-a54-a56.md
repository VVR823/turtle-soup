# A54–A56：人工审核、并发发布与回滚

2026-10-15。原清单要求不变；当前398冻结文件/55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32逐字节核0变更。只补原断言映射与隔离验收，不重新实施已完成TS15、不另派审查、不运行真实模型或假装真人审核。

## 已有证据范围

下列12个后端模块本次完整读取，精确classname核[当前完整XML](../.cache/a46/review-final.xml)实际217 PASS/0skip；均包含在3014后端/3515离线，不相加。原生60d62a实际退出0并核当前398字节一致；XML SHA256=d297ae1a7a0628f0c1e9120ffcc510086c4cedaa3b21c65aebd10cb94f78ba90。

| 模块 | 已有通过 |
| --- | ---: |
| [candidate_review_contracts](../backend/tests/test_candidate_review_contracts.py) | 39 |
| [candidate_review_store](../backend/tests/test_candidate_review_store.py) | 13 |
| [candidate_review_mutations](../backend/tests/test_candidate_review_mutations.py) | 22 |
| [candidate_review_corpus](../backend/tests/test_candidate_review_corpus.py) | 11 |
| [candidate_review_publication](../backend/tests/test_candidate_review_publication.py) | 22 |
| [candidate_review_races](../backend/tests/test_candidate_review_races.py) | 3 |
| [candidate_review_http](../backend/tests/test_candidate_review_http.py) | 37 |
| [candidate_review_rollback](../backend/tests/test_candidate_review_rollback.py) | 10 |
| [candidate_review_proofs](../backend/tests/test_candidate_review_proofs.py) | 19 |
| [candidate_review_boundaries](../backend/tests/test_candidate_review_boundaries.py) | 23 |
| [candidate_review_size](../backend/tests/test_candidate_review_size.py) | 2 |
| [ts15_review_regressions](../backend/tests/test_ts15_review_regressions.py) | 16 |

前端完整读取[DTO](../src/lib/agent-review-contract.test.ts)、[原上下文合同](../src/lib/agent-review-source-context.test.ts)、[真实面板测试](../src/components/AgentReviewPanel.test.tsx)、[反馈页接入](../src/app/admin/feedback/agent-review.test.tsx)，及[面板渲染](../src/components/AgentReviewPanel.tsx)。四文件与源/配置均绑定当前398；原全前端日志仅提供395 aggregate，不编造每文件独立计数或重算总量。

[owned浏览器脚本](../tests/ui/admin-agent-review.spec.ts)三条实际已通过，名称与[当前35UI XML](../.cache/ui-runs/3f5e7a43-cf84-4641-834d-ada2839b2071/junit.xml)对应：缺语料拒绝15.525秒、反馈→隐私→worker→审批丢响应原请求重放→发布→新旧会话→回滚28.333秒、撤权后最小详情/拒绝10.978秒。不是本轮重跑、真人判断或生产演示。完整UI XML SHA256=4f8c29dc93a449d783dc230c48d03ba4095cbb2280922c2116688c9815888dbc。

## A54：完整材料与显式语义确认

同一候选面板显示原始问题/原主持回复/之前实际对话、脱敏玩家说法、程序诊断、模型建议、replace旧目标→新答案、完整事实payload/来源/引用高亮、计划/尝试/通过分母及所有回归case。原上下文是仅管理员可见的stored_private_source，与玩家claim/model_summary分开，不把额外原文发送给Agent。

后端通过实际游戏写入建立原始前文，仅提问前的同会话记录进入详情：后续提问、另一会话不混入；原始与脱敏问题同时存在。缺配对/前文被改/超50轮或上下文容量时unavailable，无材料/批准proof，不截掉前文伪装空上下文。大型事实测试实际42项、保留low confidence及完整限定、7回归case、详情>200KB且≤512KB；过大来源在创建任务前拒绝，模型8000字符预算没有放宽。

两项复选框默认false：答案有完整事实支持、不依赖玩家当前上下文；必须真实boolean true与1–1000字符非空审核理由，不能用1/字符串/旧历史确认替代。只绿报告或缺任一语义确认不能批准；缺语料/来源撤回/依赖变化不产生fresh authority。界面批准“不发布”，发布必须独立动作。自动执行任务的通用授权不是这些合成材料的真人语义判定，不自动替用户勾选业务确认。

审批绑定candidateDraftDigest与另一个publicationDraftDigest域、原run/候选/完整report/上下文/suite/source/基线/target，并写真实审核operation receipt及业务审计；只改SQL status为approved、丢原operation或伪造回执不形成权限。改操作/目标/答案/问题/事实/证据摘要，即使重算候选摘要，仍不能借旧报告；改reportId/runId/context/suite/elapsed也拒绝。原始候选/Agent历史保持不可变，人工审核不重写awaiting_review任务结果。

独立dev/regression语料是可信服务器输入，不由模型选路径/改标签；合成语料不能用于生产、holdout/篡改/过多/异汤拒绝，运行时默认无语料不自动发现。replace在临时新release检查独立正确反例与无关规则，详见[A47–A49](acceptance-a47-a49.md)；旧错误标签要真正人审后重封存，不由Agent修成绿色。

审批和发布在最终commit重查代码/语料权限；审计写完后withdraw/replace/code变化整事务回滚。竞争语料赋值确实等待同一锁；没有只在入口检查。HTTP六入口独立admin令牌、站点令牌不能替代，错/缺401、未配置503；003不足不初始化功能表、不建网关。源已核[旧merge](../backend/app/scripts/merge_verified_qa.py)为禁写shim；[旧目录权威测试](../backend/tests/test_feedback_catalog_authority.py)证明运行时不把JSONL注入新规则，详细版本边界沿用[A39–A40](acceptance-a39-a40.md)。

## A55：同一候选和不同候选都只有一次切换

同候选两不同publish operation并发：一成功/一409，只有一个新release、active pointer仅+1。两个实际生成候选共享同语料/基线并发也同样仅一winner，另一保留approved；不把第二个候选丢掉。陈旧expectedReviewVersion/expectedRuleVersion/expectedPointerVersion/proof全部409且DB不变；无实际绑定批准凭证不能发布。

release/pointer/rule operation/candidate/review/candidate operation/两审计/commit共9注错点全回滚；shared-connection发布不另开库、不自行commit。提交成功丢ACK真实保存回执，重放只读返回原结果，不再转版；换正文/subject/verb与同operation key冲突。普通用户HTTP无admin、Agent五工具无publish、pending/rejected候选无批准路径；不是依赖模型自觉或仅隐藏按钮。

## A56：不改历史对局，回滚只切未来规则

已有实际game_service测试：发布前旧局不是、发布后新局是；回滚后新建局不是，发布后已存在的新局仍是，规则分区缓存不串。全部原消息前缀、新写入、release/候选/Agent步骤保留，历史published字段不冒充当前active；回滚目标/当前指针绑定，已active目标不是新转换。marker/pointer/operation/audit/commit五故障整库不变，跨verb重用operation拒绝；普通规则行为与暂停/旧局语义沿用[A39–A40](acceptance-a39-a40.md)。

本轮另用[缓存两例探针](../.cache/a46/a56_rejection_game_probe.py)补直接游戏证据：分别pending或approved候选，拒绝前预热旧局的“不是”；拒绝后原publish intent拒绝且DB dump不变，旧局再问和全新局仍“不是”，active pointer/release不变、候选留rejected、无Fake模型调用。候选来自实际自有Conditional/Fake循环/固定回归，不制造passing report。

实际命令`backend/.venv-ts01/Scripts/python.exe -I -B .cache/a46/a56_rejection_game_probe.py`，106405 EXIT0/[日志](../.cache/a46/a56-rejection-game.log)2 passed；[XML](../.cache/a46/a56-rejection-game.xml)2/0失败/0错误/0跳过、3.857秒，SHA256=3df58159edcd18156b4287079cc295d1dcfaaa95bbdbdb1b56e9ee24c5b31bb2。探针SHA256=11de2e27b712708ae9a3ac2ef2fab46bb3df9fc7cfa37b53ce30ea1c0a49d844；原根网络/数据护栏未关闭，有一条anyio预导入warning。不是产品RED→GREEN修复或永久测试新增，不把3515改成3517。

结论：本地A54–A56机制有来源、显示、权限、CAS和实际游戏路径证据；这些“审核理由/确认”是合成夹具，不是真人人审结论。A42/A50/A53及生产/公开门禁仍HOLD；继续A57–A60和原C/IR/OV+SG，不以该映射冒充全任务完成。
