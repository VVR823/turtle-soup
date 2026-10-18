# A01–A12 环境、迁移与请求合同核查

2026-10-15。本页核对原条目，不修改原验收勾选，不代表生产或全部目标完成。下列245项既有结果对应当时398文件身份 `55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32`；当前应用/测试显式清单为400文件f9e13b98…，A01二版421输入另外覆盖构建文件和backend/testing支撑模块，不能把旧398身份说成当前全部输入。

## 当前既有测试证据

[完整JUnit](../.cache/a46/review-final.xml) SHA256 `d297ae1a7a0628f0c1e9120ffcc510086c4cedaa3b21c65aebd10cb94f78ba90`；[源身份](../.cache/a46/review-final-identity.json)。下列已完整读取的测试模块逐一匹配当前源摘要及XML classname；重用已实际执行的结果，不是本轮重跑或新增总数。

| backend/tests 模块 | PASS | skip |
| --- | ---: | ---: |
| test_settings_isolation | 50 | 2 |
| test_migrations | 30 | 0 |
| test_migration_cli | 12 | 0 |
| test_legacy_compatibility | 17 | 0 |
| test_request_contract | 15 | 0 |
| test_request_guards | 17 | 0 |
| test_host_contract | 21 | 0 |
| test_model_gateway | 14 | 0 |
| test_model_adapter | 11 | 0 |
| test_ts03_review_regressions | 4 | 0 |
| test_game_transactions | 21 | 0 |
| test_turn_failure_recovery | 23 | 0 |
| test_game_request_recovery | 5 | 0 |
| test_request_disconnect | 2 | 0 |
| test_evaluation_state_gate | 3 | 0 |

共245 PASS、2 skip，已在当前3515离线PASS及14 skip内，不相加。两项明确跳过为本机不支持的Unix socket和符号链接权限用例，不冒充通过。其它迁移阶段与准入证据分别复用下述已有映射，不将其重复计分。

## 逐条结论

2026-10-15 A01新接续：[实际本地干净Git检出](a01-clean-checkout.md)已建立明确标记的验证快照，而非原仓库提交或远程clone。二版421许可输入逐字节一致；独立54包Python/446包Node均按原锁安装且全部实际包版本/目录对锁核验。默认后端3040项仅收集成功、配置冒烟50通过/2平台跳过；新Node环境实际前端399、进程103、合成API3通过，类型退出0且API正常关闭。联网失败和两项缓存恢复证据保留。独立限定审查实际Critical0/Important0/Minor1，支持本地结论；Python回执旧字段的禁脚本范围已绑定澄清，原记录不改。完整新环境后端、远程CI及其它OS/Python矩阵未由此证明。

- **A01 本机验证快照安装/适量运行完成，整体不扩签**：[TS01原记录](ts01-status.md)的工作树副本130 PASS仅为历史；本轮实际创建新本地Git验证提交/检出、独立Python和Node环境并运行上段所列验证，没有链接或复制主依赖。Python范围3.11–3.13、锁文件与统一脚本仍可核查；本轮仅Python3.13.13/Windows11/Node22.17.0。当前锁文件SHA分别为uv `e7cbf083eb0c20a19d8b98e705ed5418b437a554f98de8c95399fc3f15c2448a`、npm `831d93c6d6c1f8636d5499ee8a9603893266f7454590574196ba866c45c5089c`。原仓库提交/远程clone和其它OS/Python矩阵不冒充已通过；完整新环境后端未重跑，[独立限定审查及minor处置](superpowers/plans/2026-10-15-a01-review-resolution.md)已结束。
- **A02 本地证据已映射**：根conftest的pytest_configure在收集前设置独立缓存临时目录、保护真实文件/URI/Windows别名、清理模型密钥并禁用追踪；默认安装NetworkGuard。Settings.for_test/FakeModel与实例级DB/缓存/口令/限流独立；模块导入禁止DB/HTTP/dotenv读，失败启动及关闭异常收尾均有断言。原239运行文件仅做保护摘要检查，不查询玩家行。socketpair/拥有的loopback可用，不拥有的本地端口、外网/DNS/UDP/Unix通道不能借机放开；不承诺抵御任意恶意native子进程。
- **A03 部分验收**：pytest.ini显式real_model/online标记，默认不执行；--real-model还要求明确免费确认。run_qa的loose_is不再放宽五类答案，四种模糊“是”负例有断言。package.json的test:offline四段与.github/workflows/offline-ci.yml的full-offline-entry调用一致；CI另有3Python×2OS后端矩阵，但配置不等于远程运行。private仓库job跳过以防新增费用，不能为了验收擅自公开仓库。远程CI实际结果仍HOLD。
- **A04 本地迁移已映射，生产停写HOLD**：001空库只建当阶段九业务表；只读旧SQLite/WAL与JSON迁往NEW目标，旧ID/时间/次数/消息保留，重复/坏记录带问题码隔离且不输出私密原文；dry-run不创建目标，路径碰撞/真实runtime路径拒绝。旧merge/cleanup禁止重启服务，HTTP管理员正确授权后仍410。002审计、003候选的阶段门禁见[A34–35](acceptance-a34-a35.md)、[A47–49](acceptance-a47-a49.md)；真实cron/timer/手工/直连等全部写入者停写见[A58–60](acceptance-a58-a60.md)，仍productionReady=false，不冒充已停生产。
- **A05 本地证据已映射**：001可重跑且ledger仅一份，校验码、未知未来版本、缺表漂移拒绝；建表/ALTER/索引/回填/ledger共20个实际SQL故障位置全部回滚原dump，连接不留事务。messages(session_id,id)索引有EXPLAIN断言；外键/integrity与快照不可更新/删除、损坏拒绝均有测试。应用导入无迁移；002/003/005各阶段原子性不由001推断，沿用对应阶段映射。
- **A06 本地证据已映射**：正常旧playing局显式迁移后可继续，历史配对/次数保留；缺题/未配对/提醒计数矛盾/终态冲突/负数等六类返回区别码、保留原消息、不编造Turn；GET/chat/evaluate均明确410。未迁移库启动拒绝且字节不变；损坏的已配置题库拒绝，不偷偷回退或创建库。三处回填故障恢复原dump；新版快照不随live题库改变。实际NEW备份/清单/回滚及完整辅助表证据见[A58–60](acceptance-a58-a60.md)，不扩展为断电或生产演练。
- **A07 本地证据已映射**：scene错误400、空/超长/错误类型/坏UUID/未知字段422；省略UUID由服务器生成，显式null UUID不接受。旧session+同soup问法200、冲突409；question=null不是ask，ask携带level即使null也不符合场景合同。重复JSON字段在解析时422，错误不回显原输入。额外真实HTTP边界见下节：500接受/501拒绝，反馈理由2000接受/2001拒绝。32KiB整包/分片及假Content-Length在handler前受控，合法CORS保留，不限制正常游戏问法为几个固定模板。
- **A08 本地证据已映射，不认证语义正确**：HostResult严格约束kind/五类answer/chargeable/errorCode组合，ProviderHostJudgment不接收业务计次或权限字段；缺字段、非法枚举、重复JSON、非JSON、额外权力字段、bool答案等进入model_output_invalid，最多两次而非伪装“与此无关”。实际system_error保持failed/零扣数、同ID原失败重放，见[A13–17](acceptance-a13-a17.md)。模型合法JSON但事实答错属于语义错误，不能冒充解析异常或本页已验证模型正确率。
- **A09 本地证据已映射**：ai_host为一次在线请求建立monotonic+45秒原期限；准入等待取10秒与原期限最小值，网络/解析/显式重试沿用原deadline。HTTPTransport(retries=0)，网关max_attempts严格1或2；只transport/output_invalid可重试，auth/quota/policy不借机换付费模型。超时/取消/清理失败不假释放owner；双阻塞与第三次真实HTTP 503/零扣数、有限等待、队列32以及统一所有权的89项已映射于[A21](acceptance-a21-admission.md)。503固定transport类别不泄provider响应；不将本地取消当远端推理已终止，不宣称45秒硬CPU抢占。
- **A10 策略负例已映射，真实免费资格HOLD**：默认未核验/未知provider、未绑定准确model与endpoint的“免费”声明都在HTTP构造前拒绝；错误不会自动换收费模型。测试只用Fake或MockTransport，本轮没有查询/调用真实供应商，也没有有日期的真实免费资格凭证；本条不能整项签收。不买额度、不使用其它/后续卡。
- **A11 本地证据已映射**：四线程屏障同create UUID/同payload只创建一局且回放同结果；相同ID改变汤/level及不同原始fallback输入明确409而非借用别人的结果。不同UUID代表有意新开两局，不进行过度内容去重。
- **A12 本地证据已映射**：两个真实同步线程争最后一个名额，一个先reserved且未扣数，另一个turn_in_progress；释放后只成功一次，问题数恰好到上限、两消息属于同Turn。完整测试包含之前一轮故总消息4，不能错说整库仅2。单独answer测试精确验证一轮两条linked消息/一次扣数；耗尽时新UUID仅免费提醒，不越限；模型等待期间另一SQLite连接可BEGIN IMMEDIATE，事务不包外部调用。

## 补足此前未直接执行的正边界

[缓存探针](../.cache/a46/a07_request_boundary_probe.py)使用现有runtime/application/client隔离夹具及根pytest收集前保护，只有合成数据。正式执行 `backend/.venv-ts01/Scripts/python.exe -I -B .cache/a46/a07_request_boundary_probe.py`，实际126d25 EXIT0，4 PASS/0failure/0error/0skip；1条anyio断言重写提醒保留，不是测试失败。不是新RED→GREEN，不改产品或永久测试，不加到3515。

[JUnit](../.cache/a46/a07-request-boundary.xml) SHA256 `1e126aa08cddde86d21f1a820e111b3e2e31284aa08305cce92f4cf22baf55b6`；探针SHA256 `de9dfa140558a282ed35ff12ea67a0a93c346deb06a6525c0ffaff640a9c42cc`。覆盖500/501、null问法、未知字段/null UUID、2000/2001反馈理由的真实ASGI响应；不证明真实模型质量、远程CI、跨平台能力或生产部署。

接续：A13–A60已有页与当前源/XML对齐后，统一核对原C01–C24、IR01–IR24、OV1–OV3、SG1及五项约束；未采集的分支覆盖率不写成100%。
