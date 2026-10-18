# 完整分母评测运行器

TS12 把每道计划问题、失败和每次重复实验都保存下来。当前命令入口只用本地固定输出 FakeModel；它不读取真实模型密钥，不调用供应商，不是 Agent 工具，也不证明模型质量。

实际源码：[合同](../backend/eval/run_contracts.py)、[指标](../backend/eval/metrics.py)、[执行器](../backend/eval/runner.py)、[驱动](../backend/eval/drivers.py)、[真实冻结旧驱动](../backend/eval/frozen_old_driver.py)、[原字节装载器](../backend/eval/frozen_old_sources.py)、[比较](../backend/eval/comparison.py)、[CLI](../backend/eval/run_cli.py)。人工审核和源隔离先见[数据指南](evaluation-data.md)。

## 大白话：为什么不能只统计成功的问题

计划问10题，AI答对6题、答错2题、超时2题，整体正确率就是6/10，不能把超时删掉后写6/8。格式合法不代表语义正确；是否答对由原封存材料里的人工标准答案判断，当前合成测试声明不是实际人工审核。

前一轮AI答错，后一轮仍看到它真正答过的错误答案；不能偷偷用标准答案把历史改对。提醒、系统错误和彩蛋不进入下一轮有效问答历史，但它们仍在预测账本中。

```text
完整 FrozenDataset → 不含标准答案的输入 → 实际主持人结果
                                              ↓
                        全问题预测账本 → 完整指标/私有RunReport
                                              ↓
                             全重复RunBundle → 同范围比较
```

## 命令参考

在backend工作目录使用现有`.venv-ts01/Scripts/python.exe -m eval.run_cli`。每个参数都显式提供；路径必须绝对、无别名，输出不能已经存在。

| 命令 | 必需参数 | 结果 |
| --- | --- | --- |
| run | --dataset --output --system --repeat --fake-answer | 一个系统的全部计划重复，写私有RunBundle |
| compare | --input（一个或多个明确Bundle文件） --output | 保留全部运行的ComparisonReport |

`--system`只允许new_system/pure_llm/frozen_old；`--repeat`为1–10；`--fake-answer`为五类标准答案。没有真实provider、动态module/adapter/旧目录、默认数据目录、角色覆盖、`--only`、`--max-per-soup`或`--test-dir`。参数缩写也拒绝。

退出码0=运行/比较完整、2=incomplete但完整计划仍已保存、1=refused。**0不代表答对、不代表可以上线**。stdout只给status/code/runCount/inputCount/executionEvidence，不给问题、标准答案、审核人或原异常。帮助信息也不会执行模型。

旧`python -m app.scripts.eval_host_accuracy`和直接运行该脚本只转向同一新CLI，参数完全相同。导入旧入口不改环境、不加载db/runtime/模型。旧报告和原数据没有删除；旧99.1%是旧筛选口径，不能充当当前独立泛化证据。原旧入口源码摘要备份仅供恢复，不作为可执行冻结旧基线。

## How to 跑本地探索实验

前提：已有真实审核且封存的dev/regression材料，或明确标注为合成的工程演示快照。当前pending110不是这种材料；不能复制测试审核声明替真人确认。CLI拒绝正式holdout，避免把假模型演示当正式质量验收。

下面输入名代表操作者准备的材料，不宣称该文件现在存在。相同命令结构已在pytest独立三题合成快照中，分别通过新入口和旧安全入口实跑；不是拿真实玩家/人工标签示范。

```powershell
Push-Location D:\CODE\turtle-soup\backend
try {
  .\.venv-ts01\Scripts\python.exe -m eval.run_cli run `
    --dataset D:\CODE\turtle-soup\backend\eval\private\checked-regression.json `
    --output D:\CODE\turtle-soup\backend\eval\private\pure-run-new.json `
    --system pure_llm --repeat 3 --fake-answer 不是
  .\.venv-ts01\Scripts\python.exe -m eval.run_cli run `
    --dataset D:\CODE\turtle-soup\backend\eval\private\checked-regression.json `
    --output D:\CODE\turtle-soup\backend\eval\private\host-run-new.json `
    --system new_system --repeat 3 --fake-answer 不是
  .\.venv-ts01\Scripts\python.exe -m eval.run_cli run `
    --dataset D:\CODE\turtle-soup\backend\eval\private\checked-regression.json `
    --output D:\CODE\turtle-soup\backend\eval\private\old-run-new.json `
    --system frozen_old --repeat 3 --fake-answer 不是
  .\.venv-ts01\Scripts\python.exe -m eval.run_cli compare `
    --input D:\CODE\turtle-soup\backend\eval\private\pure-run-new.json `
            D:\CODE\turtle-soup\backend\eval\private\host-run-new.json `
            D:\CODE\turtle-soup\backend\eval\private\old-run-new.json `
    --output D:\CODE\turtle-soup\backend\eval\private\comparison-new.json
} finally { Pop-Location }
```

全部决策和收尾完成时比较退出0，保留三系统各三轮的9份完整报告；实际三题合成测试已生成9报告/27决策并严格读回。若只提供两个系统，仍退出2并列出缺失frozen_old的3轮，不能包装成三方实验。某次未尝试完或收尾不明时停止后续模型创建，仍生成全部计划重复，剩余题逐条记未尝试/error。以上全是假模型工程材料，不是正式质量验收。

验证时读`read_run_bundle(Path(...))`和`verify_comparison_report(...)`，不要只看stdout。缺题、丢掉最后一次重复、重复runId/重复系统槽位、换种子/预算/模型、改标签后重新计算摘要都会拒绝。既有输出换新名字，不删除旧报告取得“成功”。新写入中途失败保留部分新文件，不声称硬件掉电安全。

## Python接口与证明范围

| 接口 | 职责 |
| --- | --- |
| run_dataset(snapshot, *, system, driver, repeat_index, repeat_count, clock, utc_now) | 验证完整快照，串行执行全部case，关闭自有driver，封存报告 |
| driver.decide(EvaluationInput, *, deadline) / close() | 返回严格DriverOutcome / 已知收尾bool；可信程序接口，不是任意Python安全沙箱 |
| NewSystemDriver(settings=for_test, fake_model=FakeModel) | 真正handle_host_response，显式Soup/p1/r1，应用局部runtime，无数据库/lifespan |
| PureLLMDriver(...) | 真正call_llm和严格五类JSON协议，绕过规则/是否分类；提醒题可能判错，如实统计 |
| FrozenOldDriver(...) | 真正TS01完整原代码/Fake-only raw桥接；旧JSON失败文本回退共用case累计1–2次预算，不修好旧答案后比较 |
| UnavailableOldDriver | 没有安全可信冻结旧执行器时逐条未尝试/driver_unavailable，不执行旧源码 |
| BudgetedGateway | 真正限制deadline/最多1–2次预留；一个主持决策仅一个model invoke，不能再调用重置预算 |
| compute_metrics(records) | 无I/O纯函数，完整分母、分类、汤级、延迟和用量 |
| verify_run_report / verify_run_bundle / verify_comparison_report | 严格读回、原快照/标签绑定、全输入/重复/范围和指标重算 |

EvaluationInput只有caseId/soupId/p1/question/puzzle/history/system，没有expectedLabel、review、proposedLabel、来源组。HistoryTurn只含实际成功五类answer及版本，按汤/p1/会话、系统、repeat隔离。生产渲染器保留完整汤底，最多12个完整有效turn、8000字符；无法装入固定事实则context_too_large，不截汤底。纯LLM/新宿主链未导出真实裁剪轮数，contextTurnsIncluded记null；冻结旧宿主保留原最近10条message，即最多5完整turn，实际模型派发时按窗口记录，非模型路径仍null。inputChars来自实际invoke消息，不从提示文字猜。

PredictionRecord保留每题实际kind归类、固定errorCode、版本、耗时、预留次数和可空tokens，不保存问题全文、原始输出或推理。它所在RunReport带完整私有DatasetProof，**不能公开上传报告**。摘要防悄悄改变/内部不一致，不能认证审核人身份、真实模型身份、真实语义正确性或操作系统已结束线程。

complete表示全部决策尝试过且可信producer确认资源收尾，不表示全部正确。实际尝试后的429/invalid/timeout仍可构成完整运行；未尝试或未知收尾则false。用户显示“是”但协议非法/版本错误不能获得合法答案资格。

可信driver如果已经观测到超过声明预算的预留，是程序合同违规：停止、关闭自有资源，拒绝整份合法评测证明，不能把真实预留次数改成0来生成“同预算”报告。这不同于普通模型/provider失败，后者仍逐题保存。固定CLI真实预算包装器不会授予超额预留。

## 指标口径

固定真值6行：五类答案+reminder；预测7列：同6类+error。所有格总和必须等于inputCount。整体accuracy含全部失败；answerAccuracy分母含所有真值answer，失败/误提醒不能删。五类macro-F1固定五类平均，零支持类F1=0；未定义precision/recall为null。另给各汤原始分母、提醒指标、answer/reminder/error分类表和固定错误计数。

延迟使用全部有限非负durationMs，nearest-rank P50/P95；坏/倒退时钟拒绝报告。tokens三个维度各有knownSum/knownCount/unknownCount，某次attempt缺用量，该题该维度不能只加已知重试当总数。明确零模型调用可记已知0；调用过但未提供usage为未知，不写0。modelAttemptCount是before_attempt的**本地预留数**，不是供应商实际接收请求证明，预留后取消也不退款。

比较共同绑定完整数据/p1/r1/输入ID、计划repeatCount、adapter/provider/model/seed/预算/规范化/证据类型；每系统实现/prompt/engine版本在自己的重复里不变，不要求三个不同实现的代码摘要相同。CLI固定模型身份包含fake-answer选择；纯LLM/新宿主代码摘要来自39份明确实现/执行/统计/证明文件。冻结旧宿主另绑定11份完整原字节身份、装载器、预算driver和清单，prompt来自旧host/prompt/schema，engine为host-ts01-frozen-v1。它是TS01 captured working-tree，不是未经改动的原始HEAD或历史生产全态；旧RAG去否定、坏文本归一化和5turn窗口均真实保留，默认在线严格解析不放宽。指纹不是每题完整prompt hash、安装wheel认证、审核人或真实provider身份认证。

普通Ctrl-C在执行期间表示取消：已经完成的题和重复仍保留，当前题记录cancelled，后续计划项不再调用模型但仍在分母。自有执行器保留实际本地预留及观测；任意可信driver未返回账本便中断时，当前预留数为null/未知，不编造0，比较中的完整预留总数也为未知。取消或收尾不明的报告必须incomplete，CLI保留全计划Bundle并退出2。这不是断电、强杀、反复中断清理/写文件的持久化保证；输出写入失败不能被称为已保存。

每系统保留每次完整指标，统计accuracy/answerAccuracy/macro-F1/errorRate/P50/P95/totalTokens/modelReservations的min/max/mean/总体标准差和known/unknown计数。totalTokens只有该run全部题用量已知才进入总量统计。差值按同repeatIndex配对new-minus-baseline，正/负/0全保留；缺报告列missingRuns，已有但不完整列incompleteRuns，该pair差值null并注明incomplete_run。qualityConclusion始终null。

## 限制与故障排查

每份快照/RunBundle≤100MiB、case≤5000；每系统≤10次重复；比较≤30份RunReport，输入总和及最终输出分别≤100MiB。CLI≤128个参数，每个≤2048字符；比较最多30个明确Bundle路径，展开后仍最多30run。不扫描目录/glob，不把坏文件或最差运行丢掉。

- output_exists：保留旧文件，换一个未存在名字。
- holdout_forbidden：这是假的工程运行入口，正式质量待合法人工holdout、免费账户核验和安全旧基线；不加角色覆盖。
- repetitions_invalid / scope_mismatch：缺实验或参数漂移，不能拼出公平比较；保留所有原报告重新组织完整同范围输入。
- model_timeout / cleanup未知：停止新调用，保存error/未尝试；有限close不证明远端推理被取消。
- input/bundle/report invalid：保留原文件，核对schema/重复JSON/摘要/标签绑定，不关闭守卫或重算hash冒充审核。

入口拒绝生产runtime/data、Desktop、dotenv、链接、硬链接输入和路径别名。期限约束模型等待，不承诺抢占可信CPU代码；复用本地AttemptCollector仅取严格ModelCallObservation，HTTP形状的finish封套不保存、不当真实HTTP证据。

工程测试命令和隔离/浏览器门禁见[测试指南](testing.md)，实测及未验收部分见[TS12状态](ts12-status.md)。
