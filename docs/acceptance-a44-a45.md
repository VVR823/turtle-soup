# A44/A45 当前逐断言核查（工程证据，非真实质量）

2026-10-15当前补充：原394版本记录以下原样保留，不称当前门禁。当前398/55462476…完整3515离线/14原skip、471 Eval已在内，唯一A46审查与一次修复及35 owned UI均已终态，详见[当前验证](a46-local-verification.md)。本次重新核runner context 27与手算metrics 13到当前源和完整XML，40项均通过；[A29交叉裁定](acceptance-a22-a29.md)明确剧情评分不输入质量指标，win按error留在完整分母，不通过删特殊样本解决。真实人工金标/免费资格/三方模型成绩仍HOLD。

2026-10-14，代码身份394/432ea5862e6c6d6c7ca6666f035e0fb4d0bedb8e26b53dde6783a50c0dd7ff3f。原[A44/A45清单](../../turtle-soup-audit/TurtleSoup_秋招升级验收清单_2026-10-06.md)不改勾选；此页把原要求拆成具体行为，不靠阶段标题或文件存在判断通过。

已实际运行并读取[当前全Eval XML](../.cache/a46/task1-all-eval.xml)：430/0failure/0error/0skip，真实native52725终态16af39 EXIT0/177.87s，XML SHA3d4f6c403f29d25c965891d5a8fd1424747a79acf0ea35c28fd27167dbd74df2。其中下列四个文件实际102测试（参数化项计入），不是另加102到430。随后完整六步门禁99006尚未终态，不能据此签收整个项目。

最新补充：原99006已真实终态0，全部六步0；当前394冻结whole XML2987/0F0E14skip，2973backend+395front+103Node+3API=3474离线PASS。host_context本次完整XML实际5例通过，原239/Git/394保护均相同。上文“尚未终态”与下面该组待full是此前盘点历史，不再当当前状态；本页仍不把工程测试当真实质量或整体目标签收。

## A44：不筛掉错答、提醒或失败

- `runner.py:run_dataset` 按全部冻结case排序，每个case生成record；driver输入只有题面/固定题库/实际有效历史/system DTO，没有expectedLabel/review。driver错误、非DTO、陌生版本、timeout、未attempt都不被分类器筛掉。[runner context tests](../backend/eval/tests/test_runner_context.py)当前27项实际通过：三轮中间错误/提醒/win/异常/“是 是”都保留3条、下一轮仅继承真实有效回答；未知close/截止后仍保留所有计划行，报告incomplete。
- [metrics](../backend/eval/metrics.py)对所有严格PredictionRecord计数，error独立第7列，提醒独立真值/预测类别。[13项手算测试](../backend/eval/tests/test_runner_accounting.py)实际8个字面真值/预测得到total8、correct3、error2，accuracy3/8/errorRate2/8；quota/timeout/非法输出/unavailable/budget耗尽各保留完整分母2，不只统计成功返回。
- [report合同39项](../backend/eval/tests/test_run_contracts.py)与实际verify_run_report绑定原完整DatasetProof/inputCaseIds/inputCount/p1/r1，逐条对照原case/gold并重算metrics。删除失败行、重复case、改gold/版本/总分母、自己重新计算hash仍被拒绝；合成110输入必须manifest110=metrics110=records110，不是实际110真人金标。

以上证明当前离线工程完整分母和严格报告行为；它不证明真实provider的正确率，不能把合成正确数写成真实“100%准确”。

## A45：五类、分汤、分类/提醒、延迟、用量与上下文

- 五类macro-F1固定除5；错误/误提醒是相应真值类FN，提醒错当答案产生该类FP。8条手算F1=4/15、提醒precision1/2/recall1/3/F1=2/5，6×7矩阵合计8；未观察类F1=0，空输入accuracy/latency等null，不制造满分。输入分类矩阵2×3保留error列。
- 分汤按各自分母独立算，整体3/8不是“两汤准确率的简单平均”；small2条全正确、large6条1正确2错误，全部样本数/错误原因保留。
- P50/P95使用全部成功及失败duration的nearest-rank：字面1..8ms得到4/8ms；不是真实provider延迟/SLA。每个token维度独立knownSum/knownCount/unknownCount；没有usage时为unknown，不写0，也不把部分已知attempt总和称完整账单。
- [actual driver tests23项](../backend/eval/tests/test_eval_drivers.py)通过真实宿主/FakeModel/gateway：重试/非重试/期限/阻塞owner、未知usage保留；14个原turn的实际模型prompt仅有最后12完整有效turn，原history长度仍14；实际inputChars≤8000。contextTurnsIncluded没有直接观测时仍null，不根据猜测填数字。
- [host_context](../backend/app/host_context.py)逐整turn丢弃最旧历史，固定事实/当前提问超过8000则明确拒绝，不截断事实或删除持久历史；RunBudget/manifest固定context-v1、max12/max8000，超界/coerced政策报告拒绝。[对应host context测试](../backend/tests/test_host_context.py)源码已读；它不在本次430 Eval选择范围，当前完整99006运行中，尚不在此用该组的本次完成证据签收。

## 未完成/证据边界

A44/A45这些已观察的本地工程断言有当前源码和原生测试支撑，原真实独立标签、来源审计/holdout、真实模型实验和旧基线预算完整执行另待。A46 Task1仅旧源装载，后续driver/raw预算/固定CLI及新单元审查尚未完成。十四平台/真实opt-in skip是之前完整D18的记录，不是此430的skip；新完整结果必须读实际终态，不能用手算预填。未来源码改变时本页成为该394版本历史证据，不替新版本签收。
