# D18 唯一整项审查处置（待修复后最终验证）

实际报告：Bohr / 01a139cb-9b20-7fe3-acee-d9250292ce77，原生 wait 返回 completed（c0a12e 同次执行）；只读整项 380/ccba59...，Critical 0 / Important 1 / Minor 2，未执行测试。完整报告保留在本聊天实际工具返回和 subagent_notification 中。本文件是主代理处置摘要，不冒称原始报告逐字归档或审查者已签修复后版本。

## I1：最后提交遗漏单调预算

已检查 runner/store 实际调用链：旧最终 fence 只检查 UTC，最后 fresh verifier 可耗尽单调时间而仍提交 passed。仅新增真实合成发布/真实 host/真实 fresh verifier 夹具，在最后核验后推进单调时间至 5 或 6 秒，UTC 固定仍合法；不改答案、不跳源核验。

- RED：7a8c84 启动 / d933b0 实际 EXIT1，2 FAIL/26 deselected/6.91s；.cache/d18/review-i1-red.xml/log，失败确为 passed != incomplete。
- 修复 abc0f1 EXIT0：finish 增服务器内部可选预算 verifier，只对新 passed 在最终来源/fresh/关闭/UTC核验之后检查原双时钟预算。超时回滚原事务，沿原路径保存同一计划 incomplete/deadline，不刷新期限，不改变005或玩家路径；历史 ack 不执行此 callback。
- GREEN：51027 / e274d5 EXIT0，48 PASS/68.58s；.cache/d18/review-i1-green.xml/log。控制覆盖已答完仍超时、资源关闭、玩家表不变、同请求取同回执且不读新执行时钟。

## M1：运行状态与 case 计数矛盾

核对 result.state 的实际定义，failed 当且仅当有 counterexample；passed 至少有一个 passed case。两端原 validator 可接受一条 passed 但未答、一条 failed 但无反例、一条 incomplete 却有反例。

- RED：79697e EXIT1，后端3 FAIL/1 PASS/46 deselected，前端3 FAIL/23 PASS；.cache/d18/review-m1-red.xml/log、review-m1-frontend-red.log。
- 修复640bfc EXIT0：两端共同要求 passedCases >= passedRuns、failedRuns <= counterexampleCases <= 100*failedRuns；仅加入必然必要条件，保留合法混合 cohort 和“全部case答对但超时/清理失败而incomplete”。不改变 wire3/cursor1/005、分母或来源生产器。
- GREEN a65047 EXIT0：后端16 PASS/34 deselected/0.85s，前端26 PASS；.cache/d18/review-m1-green.xml/log、review-m1-frontend-green.log。

## M2：过时状态说明

96f0b1 EXIT0 已改设计、resume-evidence、learning map、howto-local-release、ts16-status五处当前说明：审查前冻结验证已完成，唯一审查已取得，修复后验证/产物重绑定和最终签收尚欠。不删除历史数字，不倒改原验收清单。

## 全部 Declined / 限制裁定

原审查28项裁定全部保留：零付费/真实质量HOLD；不加MCP/LangGraph/向量库/多Agent；正常玩家问法不改；in-place且不写Git历史；不fetch/造range；单席位，不按Task重派或Review Army/额外CLI；不遥测/升级/全局配置/PR；指标不重读私有context/今天corpus；损坏不变0、超时不半份、不放宽预算；不改005/cursor1/宽松补字段；不改旧4档案；不自动恢复pending/刷新期限；未测Agent动态循环等UNKNOWN；Question? Fake不是语义证据；UI响应夹具不是后台真实链/真人操作；物理依赖复制不是干净新机/Linux验证；container context不是Docker镜像；110草案人审封存HOLD；至少1真实模型轨迹HOLD；8人工参考HOLD；三方真实评测HOLD；免费资格/远程CI/生产迁移部署停写HOLD；公开许可/上传/视频/用户数字/本人掌握待独立证据；A01–A60全盘主代理另负责；哈希身份不是安全签名或OS原子隔离保证。

既有3446/14skip、35Edge、新旧包及380冻结证明仅属审查前版本。新修改不能沿用旧源绑定或旧完整门禁为新版本背书，不相加定向数字。下一步仅一次当前修复后完整门禁与新产物/新source identity绑定，然后原18阶段/A60/C24/IR24/OV+SG最终盘点；生产/人审/真实模型/公开另列HOLD，不称整体完成。

当前只读沙箱对 Git 的 worktree/路径访问失败已通过正式 require_escalated 只读核实 c0a12e EXIT0：仓库存在且顶层正确，未修Git/ACL/策略。正式审批允许本地限定补丁/离线测试；没有代批或绕过。get_goal 当前工具返回 blocked，不冒称系统目标ACTIVE；小时续跑仍保留，不因此新建重复目标。
