# 恢复协议边界：实际补测

2026-10-15。本单元只新增[10项默认测试](../src/lib/recovery-protocol-boundaries.test.ts)，生产逻辑和旧400项源输入未改；已有正确行为补测，不声称修复生产缺陷或虚构RED。

## 已实际执行

- 定向10项通过；首次类型检查发现测试mock的空参数tuple错误，仅补测试签名。首次完整回归409通过，但lint有6条未使用参数警告；保留首次记录，不称警告已清零。
- 改用显式函数泛型后，[最终运行回执](../.cache/c25/final-recovery-verification.json)三步全部退出0：完整25文件/409项前端通过，类型通过，新文件lint无输出/无警告。[真实XML](../.cache/c25/final-recovery-full-frontend.xml)独立解析409/0failure/0error/0skip，SHA19f92a42…。
- [当前401显式输入](../.cache/c25/final-recovery-identity.json)摘要5ab57e37a4ff1ea746af7f36019c5921425c28813f4e611abd96ef107c9f0e6d；只是原400清单加新测试，不冒称覆盖仓库全部支撑文件。

## 保护的行为

非法路由目标三例不能当空journal；window缺失时拒绝读写且原记录不变。恢复GET期间其它页面改保存指针，旧响应不得覆盖；初始化在途点击同步不能再发创建或换UUID。reserved配HTTP200、completed答案配HTTP503均进入协议错误，原问题/UUID保留。揭晓响应有效但canonical session仍playing时，不显示假终态或写已玩标记；揭晓HTTP503时保留原揭晓意图等待同步。

使用真实controller、journal与localStorage；只替代外部HTTP，完整DTO预期独立给定。事件控制先后，不sleep碰概率。未调用真实模型、站点或生产服务。

## 实际覆盖变化

[逐分支对比](../.cache/c25/recovery-coverage-comparison.json)在相同生产源码/相同分母下核八项新增命中、零倒退：game-controller112/139/215/224/284/293，game-journal17/36。

| 指标 | 旧完整399项 | 新完整409项 |
| --- | --- | --- |
| 分支结果 | 1712/2032，84.25% | 1720/2032，84.64% |
| 语句 | 1717/1964，87.42% | 1725/1964，87.83% |
| 行 | 1289/1408，91.54% | 1290/1408，91.61% |
| 函数 | 398/465，85.59% | 398/465，85.59% |

[最终覆盖JSON](../.cache/c25/final-frontend-recovery-coverage/coverage-final.json) SHA9e94ec2f…；[汇总](../.cache/c25/final-frontend-recovery-coverage/coverage-summary.json) SHA4d17b3ac…。game-journal分支100%只适用于该文件，整体仍有312个未命中分支结果，不等于312个已知缺陷，也没有达到原100%新路径目标。

## 审查与限制

唯一限定审查复用Kuhn席位01a13ff3-bd08-7b90-832f-d928d2a2b4d9，本单元turn01a14005-db18-7b71-8307-02a88768578a已实际完成：Critical0/Important0/Minor0。[审查范围与裁决](superpowers/plans/2026-10-15-recovery-protocol-review-resolution.md)保留四项未裁定边界；A01旧报告没有混用，不需复审或重复派审查者。

[主执行者保护回执](../.cache/d18/c25-recovery-coverage-protection.json)证明原239摘要、HEAD/index未变；不是审查者背书。后端未重跑、未改变，不生成虚构新全套总量。A01检出快照仍是新增测试之前的421输入，不冒称包含本新文件。真实模型、人审、其它OS/CI、生产、公开等完整边界仍见[全范围审计](upgrade-completion-audit.md)；恢复点见[本阶段ledger](superpowers/plans/2026-10-15-recovery-protocol-coverage-progress.md)。
