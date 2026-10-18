# 本地复现与读懂 Agent 任务报告

本操作只跑隔离测试，不需要模型密钥，不启用生产 Agent，也不访问实际反馈。环境需先按[离线测试指南](testing.md)准备好锁定依赖；命令从仓库根目录运行。接口语义见[参考](agent-loop-reference.md)，实际验收进度见[状态](ts14-status.md)。

## 1. 跑8条声明合成任务

```powershell
node scripts/test-backend.mjs backend/tests/test_agent_task_reports.py -q --tb=short -o cache_dir=.cache/ts14/pytest-cache --junitxml=.cache/ts14/local-task-reports.xml
```

成功应有8项通过；失败时先读具体断言，不删除案例以凑成功。每个 JUnit testcase 包含 `agent_task_report` property，值是该次真实隔离运行导出的报告，不是手写成功记录。测试 helper 仅在 `backend/testing/agent_fixtures.py`，生产代码不导入它。

## 2. 查看实际步骤和用量

```powershell
[xml]$tsLocalProof = Get-Content -LiteralPath '.cache/ts14/local-task-reports.xml' -Raw
$tsLocalReports = @($tsLocalProof.testsuites.testsuite.testcase | ForEach-Object { $_.properties.property } | Where-Object { $_.name -eq 'agent_task_report' } | ForEach-Object { $_.value | ConvertFrom-Json })
$tsLocalReports | Select-Object taskKey,state,modelAttemptsUsed,toolAttemptsUsed,observedAdapterInvocations,cleanupConfirmed
$tsLocalReports | Where-Object { $_.taskKey -eq 'tool-failed' } | ForEach-Object { $_.steps }
```

先确认8个不同 `taskKey` 和测试无失败/错误，再读报告。`steps` 有全序号、操作 ID、状态与动作/结果摘要；保留 planned 和 failed。`regressions` 有完整案例结果和计划分母。`providerAcceptedCalls` 为 null，`realProviderState=not_called`，`humanReferenceState=not_collected`，不是供应商已执行或人工已审核的证据。

`resume-nine-seven` 的前9次模型预留由测试合成播种，7次工具有实际隔离执行，新适配器仅1次；报告通过 `seededPriorReservations` 和 `observedAdapterInvocations` 区分它们。`cleanup-unknown` 的 `cleanupConfirmed=false` 是预期的安全行为，不能手动改成 true。

## 3. 检查管理与恢复边界

```powershell
node scripts/test-backend.mjs backend/tests/test_agent_http.py backend/tests/test_agent_recovery.py backend/tests/test_agent_heartbeat.py backend/tests/test_agent_shutdown.py -q --tb=short -o cache_dir=.cache/ts14/pytest-cache --junitxml=.cache/ts14/local-boundaries.xml
```

这些测试覆盖管理员独立权限、输入/版本/队列、撤权后摘要、迟到写入、阻塞心跳与关闭等，不向真实管理接口发送请求。完整前后端隔离门禁和另行页面门禁按[测试指南](testing.md)执行；单项绿灯不等于全项目或生产部署通过。

## 4. 复验独立审查发现的接线和竞态边界

```powershell
node scripts/test-backend.mjs backend/tests/test_ts14_review_regressions.py -q --tb=short -o cache_dir=.cache/ts14/pytest-cache --junitxml=.cache/ts14/local-review-boundaries.xml
```

当前14项测试包含实际提示词到兼容适配器的内存HTTP请求、数据库等待/提交期间关闭、独立心跳失败后的工具与候选/结束写入、调用前撤权、失效排队与CAS/审计回滚。这里的 HTTP 都由 MockTransport 在内存响应，不联系本地或云模型；候选报告夹具明确为合成，不证明人工语义结论。审查裁定见[逐项记录](ts14-review-resolution.md)。

## 出现不完整报告时（处理原则）

缺独立 corpus、权限撤回、材料或执行源变化、预算/期限耗尽、输入太长、清理未知，都可能正确拒绝继续。查该次实际报告的状态与已存步骤，不通过放宽限制、自动003迁移、改标签或重新送预算解决。真实模型、人审及生产接线是独立验收，不用这8条模拟记录替代。
