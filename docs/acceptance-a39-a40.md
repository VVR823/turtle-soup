# A39–A40 规则版本与冻结任务许可

2026-10-15。本次核当前398文件/55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32。同源逐断言映射，不是新实施或重复独立审查。以下10模块完整读并绑定当前字节，[完整XML](../.cache/a46/review-final.xml)按精确classname核150通过/0skip，全部包含在3014后端/3515离线成绩内。

| 模块 | 已有实际通过 | 断言 |
| --- | ---: | --- |
| test_rule_publication | 34 | 新release/active pointer/audit原子，CAS/操作幂等/完整审核凭据绑定 |
| test_rule_suspension | 11 | 停版挡新开局/预留/揭晓/晚到提交，冻结历史与已结束结果不删 |
| test_rule_snapshots | 19 | 新旧快照、完整摘要和原来源核验，变造/重复键/外来事实拒绝 |
| test_rule_rollback | 10 | 只切pointer；可原子停坏版本；并发/重放/故障全库回滚 |
| test_candidate_review_rollback | 10 | 实际游戏旧/新答案及缓存/回滚后历史不变，调用者同事务 |
| test_versioned_rule_host | 11 | exact匹配、版本缓存隔离、旧局固定、流程优先 |
| test_task_context | 27 | 脱敏许可/rowVersion/真实turn/题库/规则/工具权限冻结、变更转人工 |
| test_agent_prompt | 9 | claimsAreGold=false、真实步骤状态、无原反馈/任意metadata或伪造历史 |
| test_feedback_catalog_authority | 7 | 旧JSONL不自动进入运行规则；显式演练与已注册DB权威分开 |
| test_agent_loop_races | 12 | 阻塞模型/工具后撤权/换owner/关闭不能提交或继续后续调用 |

XML SHA256=d297ae1a7a0628f0c1e9120ffcc510086c4cedaa3b21c65aebd10cb94f78ba90。另读[test_agent_store](../backend/tests/test_agent_store.py)中4个具名入口用例及对应实现片段（未称完整重读该模块）：create_is_persisted_idempotent_and_contains_only_checked_sanitized_context、permission_revocation_blocks_read_and_duplicate_create、current_permission_revocation_blocks_running_heartbeat、step_replay_rechecks_permission_and_does_not_refund_attempt。当前XML各存在1项、全套无failure/error；不拿整个模块数扩大此处阅读覆盖。前页隐私12、工具16和前端暂停测试是交叉依赖，不相加当新总数。

## A39：切指针不等于重写所有旧局

[发布永久回归](../backend/tests/test_rule_publication.py)实际新建release并保存完整review/suite/draft/report摘要；旧行、原题库和旧confusion内容保持原字节，新overlay只在新ruleVersion解释。发布无默认/测试模式授权器，合成authorizer不冒充真人审核。相同operation重放不重复release/audit，换body冲突；同pointer两发布仅1成功。release/pointer/operation/audit/真实commit五处故障都全库不变。

[版本化宿主](../backend/tests/test_versioned_rule_host.py)实际旧r1答“不是”、新r1答“是”、再替换答“算是”，各自cache不串；缓存命中也必须重新核完整快照，不能以命中跳过来源校验。相似问题不继承exact补丁；真实game_service给新局新overlay，不改旧局规则。不可变是受控发布代码append新行和严格摘要/来源验证的契约，不是允许持库写权限者任意SQL篡改后仍可信。

[实际回滚路径](../backend/tests/test_candidate_review_rollback.py)发布前旧局“不是”、发布后新局“是”；回滚后另开局“不是”，先前新局仍“是”，其新消息/Agent steps/candidates/release历史保持。回滚只改active pointer和必要审计；显式block坏版本另有语义，不宣称普通切pointer已修复全部旧局。拒绝回滚到已停版本、无意义同pointer和跨动词复用operation key。

[停版](../backend/tests/test_rule_suspension.py)挡原版本新预留/新开局/尚未揭晓及在途finish。实际BlockedFake返回后仍不能写消息或扣次，原历史/UUID可查，reserved到期按原规则过期，不强行伪造成功。已有结束评估可读，停版不能删结果；恢复须明确unsuspend及marker CAS，失败不半写marker/audit。

前端参见[A30–A33](acceptance-a30-a33.md)。本次又实际读[owned暂停浏览器用例](../tests/ui/feedback-review.spec.ts)该完整case，并在[当前35项XML](../.cache/ui-runs/3f5e7a43-cf84-4641-834d-ada2839b2071/junit.xml)核其通过：原ask丢发送后暂停，刷新保留pending UUID/session，双控disabled、不新开/补POST；明确解除并sync才用同UUID重发，最终只1条问题/1次扣次。测试专用停版路由有nonce/testing保护，不是生产管理绕权接口。没有重新运行35 UI或声称真实线上停版。

## A40：审批、隐私许可、模型真值是三件事

[隐私/CAS](acceptance-a36-a38.md)要求显式完整sanitized输入、人工已检查声明和审核说明，原question/hostAnswer/expectedAnswer/reason私有保留；approved不自动safeForModel，玩家不能自填许可/版本。许可只是程序记录的人工声明，不证明真人身份或正则能识别所有隐私，也不把玩家expectedAnswer当事实。

[任务冻结](../backend/app/task_context.py)从真实已存turn/HostResult摘要、session/soup/题库/规则版本与最新feedback rowVersion重建Context，包含sanitized输入摘要、固定事实scope、allowedTools，严格冻结/extra-forbid。没有可靠turn的旧导入，即使再approve+grant也feedback_trace_required转人工；不能捏一个旧Trace。超大scope/损坏审核记录/不同汤/工具越界/题库变化都NeedsHuman，不截断成可用权限、不偷偷rebase。

[当前任务store](../backend/app/agents/store.py)每次_load都重新_freeze并与原manifest.context完全比较，_guard还核run/lease/deadline；不是只在启动时检查一次。[27项Context回归](../backend/tests/test_task_context.py)确认冻结后撤权、safe仍true但rowVersion变化、原rule停用、当前题库变化、model_copy绕验证都停止；原反馈/历史保留，零模型调用。4个入口用例另实证read/duplicate-create/heartbeat/step-replay不借旧许可继续。

[Agent prompt](../backend/tests/test_agent_prompt.py)只传sanitized输入和安全程序诊断，明确claimsAreGold=false、expectedClaim仍是“我认为”的主张；事实scope只给ID/sourcePath/category。失败工具保持失败、planned仍planned，不编造成功答案或gold历史；固定输入/源身份变化需reload/人工处理。

[实际循环竞态](../backend/tests/test_agent_loop_races.py)暂停在真实模型返回或工具计算期间，分别heartbeat/cancel/revoke/takeover/shutdown。仅同owner心跳允许正常接续；撤权/换owner等保留planned不确定记录且不写candidate/finish，不再第二次模型调用。撤权发生时已发出的那次调用不能倒称从未发送或远端已撤回；真实本地owner清理/预算保守保留，不退款以无限重试。来源冲突转needs_human/source_changed，而非瞬时错误自动换基线重跑。

结论：A39–A40本地版本/停用/冻结许可行为已映射；没有生产发布/停版，没有真实人审/模型或自动脱敏保证。A36–A38单列的OS symlink跳过与全部原真实实验/生产/公开HOLD不变。下一步继续原A41–A43数据边界与A47–A60尚未逐断言映射项，避免重做已验收阶段或把现有门禁数字重复相加。
