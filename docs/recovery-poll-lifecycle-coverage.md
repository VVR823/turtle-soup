# 默认恢复轮询与取消：实际补测

2026-10-15T16:02Z最新：本地补测阶段已收尾。[真实反例资格验证](../.cache/c26/timer-cancel-qualification.md)证明旧断言漏检、新立即断言捕获；生产代码没有此缺陷也未改动。正式审批成功，不再等待用户点击或复审。两次XML均424收集/422过滤，活动目标为根正确实现和隔离错误副本：before2通过，after根通过/错误副本预期失败。下文待执行说明保留为历史，不代表仍阻塞。

2026-10-15。只新增[七项默认生命周期测试](../src/lib/recovery-poll-lifecycle.test.ts)，原401输入和产品字节不变；已有正确行为补测，不称生产缺陷修复。

最新处置：独立审查实际C0/I1/M0，指出取消后应在时间推进前立即检查timer。已仅补该断言，[最终完整416/type/lint](../.cache/c26/final-poll-verification.json)全部退出0，402身份更新为b0b2f3c7…。额外隔离副本单点反例运行两次正式审批超时、均未执行，现单独暂存，不能声称突变已验证或本单元全部收尾；详见[完整审查处置](superpowers/plans/2026-10-15-recovery-poll-review-resolution.md)。下方34d28dc8…和原416覆盖是立即断言补强前的真实测量点，保留历史不覆盖。

## 执行与问题定位

首轮[真实XML](../.cache/c26/poll-targeted.xml)为5通过/2失败，失败在fake计时器总数2/3，而非网络请求数、意图或指针断言。实际读本机jsdom Storage-impl.js74/81/89，存储每次set/remove/clear会排0ms通知，seed两次写及foreign第三次写与观察数一致。

只在两项最终零timer检查前交付0ms通知；不推进1000ms、不clearAllTimers、不改默认pause/产品。误排的1000ms轮询仍会留下并使断言失败。[修正后定向XML](../.cache/c26/poll-targeted-corrected.xml)七项全部通过。此处修正测试环境观察，不冒充产品RED→GREEN。

## 用户可见边界

- 使用真实默认pause；999ms不能发下一次GET，1000ms才继续，1999/2000ms同理，最多三次相同UUID的GET-only恢复，原提问保留。
- 页面离开可清除等待timer；syncing订阅回调离开时，已aborted信号不新建timer。
- timer触发而await续体未运行时离开，不能再查请求；迟到turn GET不能改另一页面指针、原journal或已停止UI状态。
- null/string拒绝值显示可恢复network错误，原创建UUID保留，不显示合成私密传输文本或编造已提交终态。

afterEach统一dispose并恢复真实timer；使用完整字面DTO/真实journal和localStorage，只有外部HTTP替代，无sleep碰概率、真实模型/站点或生产访问。

## 实际全量与覆盖

[运行回执](../.cache/c26/poll-verification.json)：完整26文件/416项通过，类型退出0、新文件lint退出0且日志为空。[XML](../.cache/c26/poll-full-frontend.xml)独立解析416/0failure/0error/0skip，SHA c46603ee…。[402显式身份](../.cache/c26/poll-identity.json)摘要34d28dc8b250e1c0f5f91ce23677f64a92f7acd35d4832e1ad8054538bfcb4ce；不是全仓库/支撑文件清单。

[同源比较](../.cache/c26/poll-coverage-comparison.json)确认原401零漂移、生产分支map/分母相同；新增命中controller32两面、46、135、242、262六项分支，无倒退。

| 指标 | C25完整409项 | 本次完整416项 |
| --- | --- | --- |
| 分支结果 | 1720/2032，84.64% | 1726/2032，84.94% |
| 语句 | 1725/1964，87.83% | 1738/1964，88.49% |
| 行 | 1290/1408，91.61% | 1295/1408，91.97% |
| 函数 | 398/465，85.59% | 402/465，86.45% |

[原始覆盖](../.cache/c26/poll-coverage/coverage-final.json) SHA618f4904…；[汇总](../.cache/c26/poll-coverage/coverage-summary.json) SHAc01a2acc…。整体仍有306个未命中分支结果，不是306个已知缺陷，也不是原100%新路径目标已达成。

## 审查和限制

唯一只读审查为同一Kuhn席位01a13ff3-bd08-7b90-832f-d928d2a2b4d9，本次turn01a14016-020e-7af3-a6b8-bf735963aa53实际报告已读：C0/I1/M0；一次测试修正与额外待核验按上段记录，不混用旧C25结论、不重派复审。[主保护](../.cache/d18/c26-poll-before-review-protection.json)原239、HEAD/index不变，仅由主执行者核验。

后端没有重跑，旧3026/14证据不新增总量；A01是此前421快照，不冒称包含本新文件。真实浏览器多页调度、远端停止、其它OS/CI、真实模型/人审/生产/公开仍不由本单元证明。完整任务仍见[全范围审计](upgrade-completion-audit.md)；[本单元ledger](superpowers/plans/2026-10-15-recovery-poll-lifecycle-progress.md)保存恢复点。
