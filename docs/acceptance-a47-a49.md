# A47–A49 受限工具、候选与固定回归

2026-10-15。当前398文件/55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32。以下7模块完整读取并逐字节绑定；[当前完整XML](../.cache/a46/review-final.xml)精确classname核221通过/0skip，全部在3014后端/3515离线成绩内，不重跑/不相加。

| 模块 | 已有实际通过 | 断言 |
| --- | ---: | --- |
| test_agent_migrations | 38 | 显式003/逐SQL回滚/旧阶段保留/身份与候选正文不可变 |
| test_repair_contracts | 83 | 五工具各自强类型、拒绝任意权限/脚本/路径/报告，预算/状态严格 |
| test_repair_tools | 16 | 闭合分派/原scope/真实存储重放、许可重查、不能发布 |
| test_candidate_validation | 28 | exact语义键/replace唯一原目标/真实fact不等于结论正确 |
| test_candidate_reports | 31 | 原run/draft/context/suite/report绑定，候选幂等/不可变/仅pending |
| test_fixed_regression | 14 | 固定无云安全回归、全分母/5秒预算/缺语料不通过 |
| test_repair_corpus | 11 | 独立冻结反例/临时preview/不改标签、不收holdout或换语料 |

完整XML SHA256=d297ae1a7a0628f0c1e9120ffcc510086c4cedaa3b21c65aebd10cb94f78ba90。附加3项本轮缓存诊断下文单列，不将3515改成3518；没有修改应用/永久测试、没有新独立审查或生产/真实模型操作。

## A47：阶段先核验，模型不能选执行权限

[003迁移测试](../backend/tests/test_agent_migrations.py)实核001/002 checksum原值不变，默认001/显式002均无Agent表；显式003才注册agent_runs/agent_steps/rule_candidates和相应索引/不可变触发器。逐SQL/报告/账本故障只回滚003、原002字节状态保留；未知/缺失/checksum/索引/trigger/FK孤儿拒绝且只读。重复执行不改旧记录/报告，不补造历史run。实际Store遇002拒绝，无隐藏迁移；恢复/部署仍须独立授权与演练。

[强类型合同](../backend/tests/test_repair_contracts.py)的五工具为get_turn_trace、retrieve_truth、find_rule_conflicts、run_regression、save_candidate_rule，各有独立arguments；模型不能夹带leaseToken/runId/admin/role/path/command/datasetPath/maxCalls/自造报告。shell/python/sql/web_search/approve/publish/rollback/read_file都不能成为动作；重复JSON键/NaN/无限值/超字节也拒绝。

[工具结果](../backend/app/agents/tool_contracts.py)只返回原Context关联的sanitizedInput/ProgramDiagnostic、有限真实fact ID/来源/短excerpt及显式truncated；get_turn_trace不是任意玩家Trace文件读取器，claimsOnly=true不是gold。模型不能选凭据、路径或holdout；retrieve_truth只能原soup/p1/factScope。动作文本不映射Python执行，dispatch真未知工具拒绝且零模型/DB变化。代码能验证权限，不能承诺模型语义上永不受注入影响。

## A48：可复查不等于自动正确

[candidate validation](../backend/tests/test_candidate_validation.py)只接受exact_qa，NFC/空白/尾问号规范化不删否定/主体/数字/条件。add遇同键同答案为duplicate，反向/不同答案为conflict，不能无授权覆盖。

replace必须原同问题键、同题库/规则且唯一完整旧targetDigest；允许把旧“不是”修成新“是”，但只reviewable_replace，answerSupported/contextIndependentConfirmed仍null，进入真实人审。换主体/数字/条件、摘要变更、多旧目标、checkpoint/genre优先冲突、特殊剧情优先或指代不明均needs_human。外来fact/p1/r1、伪造事实payload或只复制版本字符串不够。

永久反例明确真实factId加“小王是医生吗→是”仍不能被机器证明正确：no_known_conflict但answerSupported=null。没有把“没发现冲突”当语义支持或自动发布保证；后续人工审批必须绑定独立参考与明确确认。

## A49：先草案后真实报告，不自证绿色

run_regression输入CandidateDraft而非待生成reportId。固定executor自己持有代码/suite/原scope和受验证dev/regression语料，使用自有Fake安全夹具，不调用线上gateway/隐式云模型。临时preview验证候选反例及无关规则；Agent不能改独立标签，旧错误标签需真实审核后另冻结。holdout、缺语料、换base、换已封存语料或源码都拒绝/不完整。

[固定回归](../backend/tests/test_fixed_regression.py)缺语料仍报告input6/attempt6/pass5/needs_corpus，不称complete；5秒预算过界保留全部输入分母与未完成标记，未知cleanup不能假true，安全反例failed不会被缺语料掩盖。报告限字节/时间/条数，来源是synthetic_fixture或deterministic_regression，不是LLM准确率。

[候选报告](../backend/tests/test_candidate_reports.py)必须来自真实planned回归动作，绑定reportId/runId/draftDigest/contextDigest/suiteManifestDigest/p1/r1；错任一字段、另一run报告、自造hash、failed/incomplete/truncated均不能作为passing候选凭证。save操作先持久化预算/意图，候选只pending；幂等不重复，原正文/report不可改，即使同run再算一份报告也不能替换已有候选的依据。

finish只引用原run候选→awaiting_review，或明确needs_human；不产生批准、不切active pointer/release。failed/cancelled/needs_human不能拿历史候选再finish成reviewable；撤权/旧lease/原deadline过期都不回写，不退还可能已发出的尝试。进入实际人工审批的三种终态另有本轮诊断如下。

### 本轮实际审批终态探针：3通过，非产品RED→GREEN

[缓存探针](../.cache/a46/a49_terminal_approval_probe.py)复用原根NetworkGuard/runtime数据护栏、自有临时SQLite和本地Conditional/Fake工具循环，先生成真实本地候选及固定回归证明；再分别模拟failed/cancelled/needs_human，携带原有效审批intent调用实际CandidateReviewStore.approve。三种均安全503/candidate_proof_invalid，DB完整dump不变、候选仍pending、无额外模型调用，不影响在线规则。

命令：`backend/.venv-ts01/Scripts/python.exe -I -B .cache/a46/a49_terminal_approval_probe.py`，原生dbdcaa实际exit0。[新XML](../.cache/a46/a49-terminal-approval-green.xml)实读3/0failure/error/skip、7.638s，SHA256=5e11727ffbe27a0960d824c4b79658a99542d285438a20f382f074d2a01eed62；[输出](../.cache/a46/a49-terminal-approval-green.log)3 passed，原fixture teardown完成。pytest启动有anyio已导入的assert-rewrite warning，未关闭网络/数据护栏，不当新安装或验证缺失。

首次53821实际exit1/[原XML](../.cache/a46/a49-terminal-approval.xml)3失败，SHA256=0487aa3e9e813d070290fdaf7dbee46853443e90669b993cfa147f5db191be63；[原输出](../.cache/a46/a49-terminal-approval.log)保留。原因是探针自定409，而原A49只要求不可批准，实际_candidate将不再兼容immutable finish的存储证明拒绝封装为安全503。按排错追踪精确错误映射后，仅纠正缓存探针预期为503并补核code，DB/候选/模型不变断言全部保留；没有改产品让它通过，不把该失败说成应用bug或功能TDD修复。最终探针SHA256=ffabfdee163d8a7c984bb8d84b887eb6fef9d2cb2b8728eda37a0b566ba84980。

结论：A47–A49本地工程与审批终态有实际覆盖。真实模型选择工具的至少1条安全轨迹/A50、8个真人参考任务/A53仍独立HOLD；固定脚本/Mock/合成三例不替代它们。继续A51–A52恢复/预算及A54–A60人工发布/交付边界。
