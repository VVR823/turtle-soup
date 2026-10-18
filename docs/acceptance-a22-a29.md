# A22–A29 语义、证据、缓存与评分断言

2026-10-15。当前398源身份55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32。下列15个模块已完整读并与冻结源逐字节核对，实际当前完整XML中共311项通过；它们已包含于3014后端/3515离线成绩，不重跑、不相加。

| 模块 | 当前XML条数 | 对应断言 |
| --- | ---: | --- |
| test_semantic_rule_guards | 25 | A22/A24：否定、主体、数量、时间、条件、关系、复合、指代与弱匹配 |
| test_genre_evidence | 19 | A23：变格不是任意超自然事实，明确无魔法与类型否定 |
| test_host_evidence | 13 | A24：真实来源路径、不可变fact ID、同汤同版本与完整上下文 |
| test_exact_question_keys | 23 | A22/A25：精确规范化不删否定、数字、主体、时间、条件 |
| test_versioned_rule_host | 11 | A24/A25：同源发布覆盖、新旧规则/缓存分离、伪造快照拒绝 |
| test_versioned_host_cache | 40 | A25：1024 LRU/600秒、并发、返值隔离、上下文/模型/状态排除 |
| test_ts06_review_regressions | 21 | A22–A25：条件/指代/子集的实际HTTP回归及正常降级 |
| test_scoring_contract | 55 | A26/A27：严格二值、极性、复合证明与剧情/事实分离 |
| test_evaluation_snapshot | 38 | A26–A28：真实SQLite评分、损坏拒绝、原子保存与原样恢复 |
| test_evaluation_state_gate | 3 | A28：一份持久结果、并发重放、solved不被揭晓反转 |
| test_ts07_review_regressions | 19 | A26/A27：嵌套复合否定不制造事实覆盖，普通问法保持正常回答 |
| test_game_transactions | 21 | A29：难度缺省/非法回退、冻结难度与unlimited |
| test_public_search_boundary | 13 | A29：隐藏/解锁/公开搜索、合法揭晓与私有字段边界 |
| test_win_condition | 8 | A29：原通关条件保留，猜中式文本不是已提交的真实win |
| test_zhimengzhe_unlock | 2 | A29：实际HTTP六问后合成肯定解锁/无关不解锁 |

[当前完整XML](../.cache/a46/review-final.xml) SHA256 d297ae1a7a0628f0c1e9120ffcc510086c4cedaa3b21c65aebd10cb94f78ba90；3028/0failure/0error/14原有跳过。此表所列均是已核通过的现有测试，不把旧阶段历史数字替代当前证据。

## A22–A24：不让词面相似替代完整问题

同主体相反极性不共用答案；改主体/3与4/年份/因果或条件时不能靠部分checkpoint锁定。弱检索只返回实际存在、同版本的候选证据，不自带答案权限。事实ID绑定soupId、puzzleVersion和实际payload/sourcePath，改汤、改内容或冒领旧p1均不能复用。

两种历史对“他死了吗”等同字面指代可得到相反的明确合成回答，均保留实际历史给模型且不跨会话缓存；前者/后者/自己/本人和子集人数也有实际HTTP对照。无法完整证明的复杂/上下文语句转正常模型路径，不是直接报“异常输出”；只有问号的输入是友好免费提醒。

只有穿越且明确无魔法的合成汤，不能因“变格”标签推断有魔法；正反类型问法、低/中/未知置信事实、冲突来源均不制造本地确定性锁定。这里证明快捷分支的边界，不声称真实模型能自动识别每次语义错答；Fake回答与真实质量证据分开。

## A25：纯结果缓存与精确计数

缓存包含soup/puzzle/rule/engine/normalization/question身份，实际规则发布前后及旧对局各用自己的答案。LLM、历史依赖、win/提醒/异常、无来源marker和未固定版本均不缓存；剩余次数/玩家状态不存入缓存值。返值深复制、1025次插入的LRU淘汰、599.999秒命中/600秒失效与40并发均有现有测试。

补充直接探针验证独立手算计数：一次初始miss、一次不同否定键miss、600秒过期miss；两次命中；结果hits=2/misses=3/expirations=1/evictions=0，重复snapshot不重复计过期。

## A26/A27：事实覆盖不是还原分数

只计完整命题及来源极性一致的严格“是/不是”；“是也不是/算是”、失败、免费提醒、不可配对旧消息、玩家粘贴主持人行均不产生事实确认。重复同事实不累计成更多事实，否定整个复合命题也不能推导每个分句为假。剧情win可有plotProgress100而事实覆盖0，两者均不是独立还原评分。

补充真实ASGI字面探针：同一明确“某人不是凶手”的合成来源下，裸“不是凶手”即使Fake回答“是”，verifiedCoverage仍0；完整“某人不是凶手吗”得到正确确认时可覆盖该已知否定事实100。两种情况reconstructionScore均null、plotProgress均null，重复揭晓与GET恢复完全相同。

这不意味着否定句一律不得分，而是不能因出现“凶手”二字就凭空给“还原满分”。前端evaluation规范化及真实GamePage结果视图分别显示事实覆盖、剧情进度、还原未独立评估；畸形新分数拒绝，历史83等旧分数仍明确标历史。

[补充探针](../.cache/a46/original-a25-a27-probes.py) SHA256 f271811b075e526e67c6aa74e829b5ad05db397fd377dc49615cba9db26e9a6d；
[实际回执](../.cache/a46/original-a25-a27-probes.json) SHA256 c033ea18704fdd170db5c78e320fd902cbc17bb4dd5e9946c0448afc553eddd0，native ccb4c7退出0，自有合成目录/Runtime正常关闭，源零漂移。是额外验收，不添加进完整回归数量。

## A28：页面刷新也保留同一已结束结果

后端重复/并发揭晓只保留一份快照，真win后仍solved且原请求可重放。实际owned Edge的“lost reveal response restores the immutable ended result through GET before retry”检查：先让真实服务器完成揭晓再丢掉响应，刷新后GET恢复相同evaluation，浏览器没有第二次揭晓POST；原session指针保留。真实win/35次耗尽自动揭晓后刷新也保留结果；旧历史fixture明确标旧口径。

该spec已完整读、与398指纹相同，并在本轮已验收的35 UI XML中找到实际通过case；不是重新启动浏览器或编造截图质量。[UI XML](../.cache/ui-runs/3f5e7a43-cf84-4641-834d-ada2839b2071/junit.xml)，SHA256 4f8c29dc93a449d783dc230c48d03ba4095cbb2280922c2116688c9815888dbc。

## A29：游戏契约与质量口径交叉核对完成（本地）

缺省/非法难度按最严格冻结值、unlimited无合成上限、隐藏/已解锁列表及原剧情win/六问解锁均有实际隔离回归。叙事plot与事实覆盖/独立还原在评分和UI中分栏，不把合成解锁成功说成真实模型准确率提升。

Ruling（2026-10-15交叉核对）：原A29要求“特殊剧情评分不混入普通模型质量指标”，并非“删除特殊剧情样本或失败行”。此前把它简称为分母排除，范围比原文更强且会冲突A44完整分母；按原文验收，不新增筛样逻辑。若误判，风险是把剧情奖励当质量；下面分别核实际数据流与反例，不仅凭搜索无字段下结论。

[评分](../backend/app/scoring.py)单独计算plotProgress，win可plot100但不生成事实/还原满分；[评测记录](../backend/eval/run_contracts.py)的PredictionRecord无completion/verifiedCoverage/reconstructionScore/plotProgress字段，继承extra-forbid严格合同。[runner](../backend/eval/runner.py)逐原case记合法五类答案/reminder/error，win明确记unexpected_host_kind/error而不是准确答案或剧情100，既不继承为后续有效问答历史也不丢该样本。[metrics](../backend/eval/metrics.py)只按expectedLabel与prediction手算全分母混淆矩阵/准确率，不读取游戏剧情评分。

本次实际绑定上述实现及[runner context测试](../backend/eval/tests/test_runner_context.py)、[手算测试](../backend/eval/tests/test_runner_accounting.py)到当前398原字节，并读当前完整XML：27+13=40项全部通过/无skip，已含在471 Eval/3515内，不重跑不相加。中间返回win的永久用例仍3行/total3、中间prediction=error、下一轮history不含win；手算8行含失败/提醒仍total8/correct3/error2。这与A44完整分母一致，不会用剧情高分装饰普通质量。[A44–A45](acceptance-a44-a45.md)保留其完整工程/真实实验限制。故原A29本地游戏契约与特殊评分隔离子项均已有证据；真实模型结果仍未证明，不以此签收整体。

## 保护与后续

本轮未改应用/永久测试；398源仍零漂移。[前次保护](../.cache/d18/a22-a29-probes-after-protection.json)与[本轮保护](../.cache/d18/a30-a35-map-after-protection.json)239文件/d9662e98…、HEAD/index均与原值一致。真实模型、独立人审、生产/公开及本人讲解能力仍不代造。A30–A35现已有各自映射文档，下一步A36–A40；不重跑已验收A46或派第二审查者。
