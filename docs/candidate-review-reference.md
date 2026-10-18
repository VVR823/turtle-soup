# 候选审核接口参考

TS15 使用独立管理员口令审核 Agent 生成的候选。批准、发布、回滚是三个不同操作。接口验证真实存储的来源、报告和操作凭证，不把浏览器提交的摘要或勾选框当作单独发布权限。当前阶段状态见 [TS15 状态](ts15-status.md)，设计取舍见 [大白话解释](candidate-review-explanation.md)。

## 开启条件与边界

- 数据库必须已有校验通过的 003。接口不创建缺失数据库、不自动迁移；默认应用初始化仍到 002。
- 每次请求使用独立 `X-Admin-Token`。站点口令、玩家和模型没有批准/发布能力。
- `ENABLE_AGENT` 默认 false。索引、候选读取和人工操作不依赖运行中的 worker，不创建模型网关；旧任务启动、状态和取消仍要求启用 worker。
- 应用工厂的 `repair_corpus` 只接受可信服务器传入的、验封完整的 `FrozenDataset`：dev/regression、1–100 案例、单一题库；拒绝 holdout、来源不一致或已修改的证明。缺题集不捏造成功报告，生产不能使用合成题集/报告证明。
- 任务仍为最多 10 次模型尝试、8 次工具尝试、180 秒；审批不重开预算。无需付费模型裁判。

## 私有 HTTP 表面

路径前缀：`/api/feedback/admin`。GET 固定路由模板限流 30 次/分钟，修改操作 20 次/分钟。更换路径 UUID 不会获得新的限流桶。

| 方法与相对路径 | 输入 | 结果 |
| --- | --- | --- |
| GET `/agent-runs` | `limit` 默认 50，1–100；`start/end` 为有限非负 Unix 秒；默认最近 7 天、窗口最多 31 天；`cursor` ≤512 字符；可选 `feedbackId` | 有序最小任务摘要及 `nextCursor`，不是用户人数 |
| GET `/rule-candidates/{candidate_id}` | 规范 UUID | 完整证据或最小不可用/陈旧状态 |
| POST `/rule-candidates/{candidate_id}/approve` | 下表批准体 | 批准操作的最小凭证，不自动发布 |
| POST `/rule-candidates/{candidate_id}/reject` | 下表拒绝体 | 拒绝凭证，保留历史、不改在线答案 |
| POST `/rule-candidates/{candidate_id}/publish` | 下表发布体 | 已发布规则版本及候选凭证 |
| POST `/rule-releases/rollback` | 下表回滚体 | 目标规则版本、递增指针版本及操作凭证 |

翻页游标绑定原窗口、过滤条件和页大小；每次翻页仍需认证。读取 SQL 有界聚合，不逐条加载完整任务历史。旧启动/状态/取消接口参考 [Agent 循环](agent-loop-reference.md)。

## 修改请求字段

所有 body 为闭合 JSON，最多 32 KiB UTF-8；重复字段、未知字段、NaN/Infinity、布尔或字符串冒充版本均拒绝。版本为实际整数 `0..9223372036854775807`，涉及递增时仍须可递增；前端拒绝超出 JavaScript 安全整数范围的版本，不舍入后发送。UUID 使用规范格式，摘要为 64 位小写十六进制，规则版本为 `r1:` 加该摘要。

| 操作 | 必需字段 | 额外限制 |
| --- | --- | --- |
| 批准 | `operationKey`, `expectedReviewVersion`, `expectedProofDigest`, `answerSupported`, `contextIndependent`, `reviewNote` | 两项确认必须为真正的 true；理由 1–1000 Unicode 字符且非全空白 |
| 拒绝 | `operationKey`, `expectedReviewVersion`, `reviewNote` | 仅 pending/approved；可以拒绝陈旧候选，不恢复其材料 |
| 发布 | `operationKey`, `expectedReviewVersion`, `expectedProofDigest`, `expectedRuleVersion`, `expectedPointerVersion` | 服务器从实际已批准候选派生发布草稿，不接受外部草稿、事实、报告、角色或模型权限 |
| 回滚 | `operationKey`, `targetRuleVersion`, `expectedRuleVersion`, `expectedPointerVersion`, `reason` | 目标为不同且已验证的历史版本；理由 1–1000 非空白字符；可选 `blockRuleVersion` 使用已有暂停语义 |

相同 operationKey、路径、动作和完整内容只能重放原只读凭证。换内容、候选或动作返回 409。候选与规则操作键也不能跨动作复用。历史成功凭证不代表现在仍有执行权限；丢回复时不能自动生成新发布请求。

## 完整详情与历史

完整材料包含实际冻结的脱敏输入（玩家说法）、程序诊断、模型建议、全部事实与限定条件、突出引用事实、replace 的真实旧目标及新草稿、全部回归案例和完整分母。没有原始模型思考、租约或运输层错误原文。详情最多 512 KiB；过大时受控拒绝完整材料，不截掉失败案例凑通过。

`sourceContext` 单独显示实际关联原问题、公开主持回复及这次提问之前的完整对话。它是 `stored_private_source/admin_review_only`，不是玩家理由、模型总结或追加云端许可，不加入 Agent 的 TaskContext/提示。真实消息 ID 固定原提问边界，不含后续问题或其他会话；摘要进入 v2 审核 proof，人工确认绑定该材料。最多100条前文、完整投影128KiB；缺失、不一致或超过上限返回最小 `candidate_context_unavailable`，不能静默删行或把无法核对的前文当空对话。已核验的零前文与缺材料有明确区别。

| availability | 含义 | 可否从读取获得执行权限 |
| --- | --- | --- |
| ready | 当前来源/权限/报告/代码/题集/基线证明可用于后续再验证 | 不能；仍须人工确认、当前版本及实际操作凭证 |
| historical | 来源许可仍有效，但只显示原任务固定历史 | 不能；`proofDigest=null` |
| stale | 来源或许可已变化 | 不能；只返回最小状态 |
| unavailable | 缺题集、证明损坏或其他能力缺失 | 不能；不是空成功列表或假报告 |

原任务 `awaiting_review` 和候选工作流 `pending/approved/rejected/published` 分开。候选不可变 JSON 仍记录原 pending；人工操作不重写原模型步骤、结束结果或预算。回滚后候选仍可以是 published，因为那是发布历史。

报告绑定 CandidateDraft 摘要；发布审核凭证绑定 ChangeDraft 摘要。两个摘要域不同，必须分别核验。已批准元数据还必须关联实际保存的批准操作，不能单凭一段自洽 JSON 发布。

发布在同一个 SQLite `BEGIN IMMEDIATE` 事务中保存 release、指针、候选状态、审核版本、两类操作凭证和必要审计。任一必要写入失败整体撤销。回滚只切换指针并记录新的审计，不用旧数据库覆盖新反馈/会话。新局使用新版本，旧局保留固定版本；显式暂停另按已有规则执行。

新批准/发布在最终提交锁内再次校验实际 corpus 和注册代码身份；验证后撤回/替换或代码变化会撤销同一事务全部写入，不重新运行或改签原报告。可信服务端的 `repair_corpus` 赋值与最终提交共锁，重放旧成功凭证与陈旧拒绝不要求新语料权限。源码更新不支持运行中热改：须先关闭接收、排空任务并重启，让新进程建立身份；最终复查不是跨文件系统与 SQLite 的原子锁，也不是对恶意服务器代码的防护。普通玩家请求路径未增加这项检查。

## 管理页面

玩家点击回答旁的“反馈这次回答”，反馈只绑定实际完整公共问答轮次。全局反馈和旧无关联消息不会猜测关联到最近一轮。

管理员先审核反馈，再逐项编辑脱敏输入并勾选隐私确认。保存授权不会启动任务；必须另点“显式启动修复任务”。编辑区明确区分原始预填草稿与本会话提交草稿，不冒充服务器回读证明；实际任务使用服务器保存内容，候选材料显示实际冻结输入。新版本/口令不继承旧确认或提交草稿。

候选先展示证据，语义确认默认不勾选，理由为空。批准后刷新实际状态，再单独确认发布。关闭面板不轮询；只对一个可见活动任务每次至少间隔 3 秒轮询，终态/认证失败/限流/卸载停止。网络结果不明只提供手动核对或原请求重试，不自动修改新版本。

自由填写的审核理由是管理员私有记录，不是自动隐私过滤器；不要粘贴身份、密钥。前端校验格式和跨字段一致性不替代服务器的实际内容摘要与授权验证。

## 隔离复现入口

已准备本仓库依赖后，从仓库根目录执行已有包装器：

```powershell
node scripts/test-backend.mjs backend/tests/test_candidate_review_contracts.py backend/tests/test_candidate_review_http.py
npm run test:frontend -- src/components/AgentReviewPanel.test.tsx src/app/admin/feedback/agent-review.test.tsx
node scripts/ui-e2e-server.mjs
```

Python 包装器使用既有 uv 环境、offline/no-sync；页面包装器使用本机已安装 Edge、临时数据与构建、独占测试端口，并正常关闭自有服务。不运行生产迁移/启动命令，不安装浏览器，不读取真实 dotenv。依赖/端口不足时处理具体失败，不复用未知服务，参见 [测试指南](testing.md)。命令验证机械行为，不产生真人语义审核或真实模型成绩。

对应真实测试：[HTTP](../backend/tests/test_candidate_review_http.py)、[发布](../backend/tests/test_candidate_review_publication.py)、[回滚](../backend/tests/test_candidate_review_rollback.py)、[竞态](../backend/tests/test_candidate_review_races.py)、[真实页面流程](../tests/ui/admin-agent-review.spec.ts)。
