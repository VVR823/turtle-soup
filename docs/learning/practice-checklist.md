# How to 安全练习并证明自己掌握了项目

先在不动玩家数据、不调用云模型的条件下，看见一次正常问答和一次失败请求的恢复；再独立增加小测试。解释在[模块卡](core-module-cards.md)，完整运行条件在[测试指南](../testing.md)。

## 前提与边界

- 本机已具备项目锁定的 Node、uv 及 `backend/.venv-ts01` 离线依赖。以下入口使用 `uv --offline --no-sync`，缺依赖时报错，不自动安装，也不需要API密钥。
- pytest 自带临时目录、注入模型和网络/真实文件守卫。不要传 `--real-model`、`--online`、自定义 `--basetemp`，不要启动生产应用或打开真实后台。
- 以下命令只运行现有测试，产生本地测试报告；独立修改请在你自己准备的隔离练习副本完成。不要复制 `.env`、`backend/data`、根 `data`、真实题库/玩家材料，或为练习在正式成品里故意删保护逻辑。
- 本材料没有替你完成独立练习；所有个人掌握勾选初始为空。运行测试不等于所有功能都会用，也不等于真实模型、人审、线上或公开门禁通过。

## 第一次结果：三步以内

1. 打开 PowerShell，进入项目根目录并准备个人报告的父目录。这里只创建目录，不移动或删除已有报告。

   ```powershell
   Set-Location 'D:\CODE\turtle-soup'
   $LearningReportsRoot = Join-Path (Get-Location).Path '.cache/student-learning'
   New-Item -ItemType Directory -Path $LearningReportsRoot -Force | Out-Null
   ```

2. 在运行前写下预测：合成模型成功时扣1次；非法输出时扣0次；按同一编号恢复时不再增加模型调用。

3. 整块运行下面三行：生成新的随机编号目录，再运行现有HTTP恢复用例。目录若已存在会直接报错，不复用旧输出。

   ```powershell
   $LearningRun = Join-Path $LearningReportsRoot ([guid]::NewGuid().ToString('N'))
   New-Item -ItemType Directory -Path $LearningRun -ErrorAction Stop | Out-Null
   node scripts/test-backend.mjs backend/tests/test_game_request_recovery.py::test_lost_answer_or_failure_response_replays_exactly_without_another_model_call -q -o cache_dir="$LearningRun/pytest-cache" --junitxml="$LearningRun/first-question.xml"
   ```

   两个参数分支都通过时能看见 `2 passed`。测试真实调用本地应用的HTTP层，但模型是注入的合成输出，不访问网站或供应商。成功保存/失败保存后重复提交，都取回原响应。失败虽扣0次，初始非法输出可能已有两次模型尝试；游戏计数不能代替模型成本。

### What you built

你没有搭建新服务，而是在临时数据库中实际走过一轮问答、结果保存和恢复。沿[路线](project-learning-map.md)指出前端编号、后端预留、主持判断和最终提交，再做下面每张卡的反例。

## 九张卡的可运行反例

保持项目根目录和上面准备好的 `$LearningReportsRoot`。每次都完整运行对应的三行代码块，包括第一行重新生成目录；不要只重复最后一行或沿用旧的 `$LearningRun`。每个代码块、每次重跑都使用一个新的随机编号目录，缓存与XML一起写在该目录，不写入 `.cache/ts18/learning` 等作者归档。第二行不使用 `-Force`，已有目录会拒绝。随机编号只用来区分练习，不是权限证明。

当前修复后的测试应通过；“复现”指重现曾出错的输入/事件并检查现在能保护它，不是在原仓库重新引入漏洞。记录实际 `$LearningRun` 路径和XML身份，把本人练习与作者历史核验分开。

### CM01：关闭开始后禁止首次创建模型网关

```powershell
$LearningRun = Join-Path $LearningReportsRoot ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $LearningRun -ErrorAction Stop | Out-Null
node scripts/test-backend.mjs backend/tests/test_ts03_review_regressions.py::test_runtime_rejects_first_gateway_creation_after_shutdown_has_started -q -o cache_dir="$LearningRun/pytest-cache" --junitxml="$LearningRun/cm01.xml"
```

### CM02：损坏保存响应不得串局或夹带私有字段

```powershell
$LearningRun = Join-Path $LearningReportsRoot ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $LearningRun -ErrorAction Stop | Out-Null
node scripts/test-backend.mjs backend/tests/test_ts04_review_regressions.py -q -o cache_dir="$LearningRun/pytest-cache" --junitxml="$LearningRun/cm02.xml"
```

### CM03：指代需要前文，不直接命中静态捷径

```powershell
$LearningRun = Join-Path $LearningReportsRoot ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $LearningRun -ErrorAction Stop | Out-Null
node scripts/test-backend.mjs backend/tests/test_ts06_review_regressions.py -q -o cache_dir="$LearningRun/pytest-cache" --junitxml="$LearningRun/cm03.xml"
```

### CM04：完整分母和取消时的未知

```powershell
$LearningRun = Join-Path $LearningReportsRoot ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $LearningRun -ErrorAction Stop | Out-Null
node scripts/test-backend.mjs backend/eval/tests/test_runner_accounting.py::test_all_eight_decisions_and_error_column_enter_literal_denominator backend/eval/tests/test_ts12_review_regressions.py::test_cancellation_preserves_previous_current_and_remaining_cases_without_zero_guess -q -o cache_dir="$LearningRun/pytest-cache" --junitxml="$LearningRun/cm04.xml"
```

### CM05：拒绝新空白反馈，但保留旧记录与拒绝/撤回入口

```powershell
$LearningRun = Join-Path $LearningReportsRoot ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $LearningRun -ErrorAction Stop | Out-Null
node scripts/test-backend.mjs backend/tests/test_ts10_review_regressions.py -q -o cache_dir="$LearningRun/pytest-cache" --junitxml="$LearningRun/cm05.xml"
```

### CM06：真正发送前重新检查来源许可

```powershell
$LearningRun = Join-Path $LearningReportsRoot ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $LearningRun -ErrorAction Stop | Out-Null
node scripts/test-backend.mjs backend/tests/test_ts14_review_regressions.py::test_source_is_rechecked_after_adapter_construction_before_dispatch -q -o cache_dir="$LearningRun/pytest-cache" --junitxml="$LearningRun/cm06.xml"
```

### CM07：批准/发布最后一刻证据变化，整笔提交回滚

```powershell
$LearningRun = Join-Path $LearningReportsRoot ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $LearningRun -ErrorAction Stop | Out-Null
node scripts/test-backend.mjs backend/tests/test_ts15_review_regressions.py::test_non_db_authority_change_after_necessary_audit_rolls_back_the_whole_mutation -q -o cache_dir="$LearningRun/pytest-cache" --junitxml="$LearningRun/cm07.xml"
```

### CM08：当前v3页面与完整导出能重校验，缺005来源仍是未知

```powershell
$LearningRun = Join-Path $LearningReportsRoot ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $LearningRun -ErrorAction Stop | Out-Null
node scripts/test-backend.mjs backend/tests/test_metrics_missing_source.py -q -o cache_dir="$LearningRun/pytest-cache" --junitxml="$LearningRun/cm08.xml"
```

### CM09：复制输出被破坏，不得产生成功恢复报告

```powershell
$LearningRun = Join-Path $LearningReportsRoot ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $LearningRun -ErrorAction Stop | Out-Null
node scripts/test-backend.mjs backend/tests/test_release_recovery.py::test_recovery_detects_corrupted_auxiliary_copy_not_just_unchanged_input -q -o cache_dir="$LearningRun/pytest-cache" --junitxml="$LearningRun/cm09.xml"
```

## 独立修改清单：尚未由你完成

先做观察/预测，再在个人隔离副本里选一个小练习。不要求九个一起做，不增加模型/部署平台或付费服务。

| 卡 | 自己做的小修改 | 最低通过标准 |
| --- | --- | --- |
| CM01 | 增加反复关闭的合成控制 | 无新网关，说明关闭开始与清理结束的区别 |
| CM02 | 增加同文字、新requestId的控制 | 新提问与原请求重放分开，断言计数及调用量 |
| CM03 | 增加一个否定键/不同前文的反例 | 普通模型路径保留，不能用误报系统失败求绿 |
| CM04 | 给合成矩阵加一个失败样本 | 手算新分母/错误率/未知用量，再与实际断言比较 |
| CM05 | 检查批准反馈不会自动授予模型许可 | 语义状态、隐私许可、规则发布三者不混用 |
| CM06 | 增加停止后恢复预算控制 | 已花尝试/原期限不清零，撤回许可不复活 |
| CM07 | 增加批准但未发布的控制 | 当前指针不变；旧局固定版本；回滚不删历史 |
| CM08 | 分别断言已知零与未知来源 | `null`不改成0，`complete`不冒充质量证据 |
| CM09 | 增加已存在目标的哨兵文件控制 | 拒绝覆盖，源与原目标不变，不触真实目录 |

个人练习先写测试并运行。如果真正暴露产品缺陷，应保留失败输出、找原因、最小修复再跑相关回归；若只是自己写错字段/导入/断言，要记为练习错误，不能冒称发现项目漏洞。已有保护正确时，新增控制先通过是合理的，不强造 RED 或故意删成品保护。

## 自己的证据记录模板

每个练习写一份私人记录，不上传敏感路径/原文。以下勾选由你完成，不能由AI看过文件后代勾。

- [ ] 用自己的话说出用户会遇到什么问题。
- [ ] 指出入口、被调用函数、数据保存位置和权限检查。
- [ ] 先记录预期结果及为什么，不照抄测试输出。
- [ ] 独立添加小控制或定位一个真实失败，保存自己的修改差异。
- [ ] 记录完整命令、退出码、通过/失败/跳过及原因。
- [ ] 解释修复保护了什么、没保护什么、代价是什么。
- [ ] 能不看稿回答一个变化条件，例如断网发生在提交前还是后。

记录字段：`卡号 / 日期 / 假设 / 修改文件 / AI协助范围 / 命令 / 实际结果 / 误判或修正 / 边界 / 我能独立讲清的部分`。只有这些证据实际存在，才把对应部分写成“本人掌握”。需求/迭代/验收贡献不用否认，但不能代替技术实践。

## 常见失败怎么处理

- 找不到Node/uv：核对[测试指南](../testing.md)的既有环境；不要改用未隔离生产入口。
- uv提示离线依赖缺失：停止该练习，记录缺失；不自动联网安装或读取真实配置。
- 文件/网络守卫拒绝：检查是否用了真实目录/供应商地址；不关闭守卫、不改ACL求通过。
- 测试失败：读具体断言与来源；不要把pytest收集错误、平台跳过、夹具超时写成模型答错。
- XML有skip：跳过不是通过。报告来自哪个命令、哪个版本、哪次运行要写清，不能混加历史结果。
- 想看真实模型效果：这是另一道资格/隐私/费用/样本授权门禁；上述Fake结果不能替代。

本材料的历史命令核验/唯一审查以[TS18 ledger](../superpowers/plans/2026-10-13-ts18-progress.md)为准，当前修正见[自主进度](../autonomous-progress.md)。D18本地可信采集/完整分母统计已实现并有[当前A57证据](../acceptance-a57.md)；真实模型/人审/视频、本人练习、公开及生产仍分别待定，不能用AI核验代签。
