# 本地恢复兼容矩阵（不是生产回滚授权）

2026-10-16收尾补充：新增 `test_restored_agent_acceptance.py`，在临时schema3/4/5中先持久化排队任务、关闭源Runtime、备份恢复，再由新Runtime显式执行一次实际worker/工具循环；原编号/预算保留、不会自动跑队列、再次run_once不重复消费、资源清理通过。schema4/5额外执行动态回归并生成pending候选，未自动批准发布。关联20项严格资源警告模式通过。该补充是工作区代码的合成机械证据，不把它冒称真实模型、人审或生产验证；下方原历史UNKNOWN需按此具体范围阅读，包内同3个测试体也已通过：72个业务模块来自新包，3个恢复操作辅助来自工作区且哈希核对。早期沙箱socketpair超时由标准权限流程处理，见[总表](../ACCEPTANCE_FINAL_REPORT.md)。该新增证据不自动扩签其他schema/功能格。

2026-10-14最新检查点：D18唯一整项审查处置后，当前380/6053fa…完成3456离线通过/14明确跳过、35Edge、当前新包构建/HTTP/源码绑定与新容器输入复验；原239运行数据和Git摘要未变。见[当前本地证据](d18-local-verification.md)。本页下方早于此检查点的冻结数字/“仍待”说明为历史，不当最新状态；真实模型、人审、生产、公开与原完整任务签收仍未通过。

这是**有限本机证据**。D18新矩阵在前，TS17旧冻结证据保留在后，不能将旧身份当当前源码。矩阵区分：SQLite快照是否可核验、代码包能否启动读写、恢复后哪些功能真的执行过。版本号“大于最低要求”不等于每个功能已验证；UNKNOWN不能批准开放生产写入。原玩家库、生产、真实供应商和人工语义质量仍HOLD。

## D18当前定向恢复与产物矩阵（最终整单元验收待完成）

原恢复范围与发布后passed/failed/incomplete/running四状态账本真实56PASS/4原生symlink权限skip：[XML](../.cache/d18/recovery-five-green.xml)。仅扩manifest版本白名单至5，不放宽摘要/结构/NEW目录/不可覆盖；005账本、出生证据、完整业务行和同窗口13项计数恢复后守恒，不自动执行pending。真实新解释器产物矩阵：[测试](../backend/tests/test_packaged_backend_compatibility.py)、[探针](../scripts/tests/probe-backend-compatibility.py)、[6case XML](../.cache/d18/packaged-matrix-current.xml)，69289/bf3fc0原生EXIT0/6PASS/12.54s；首4FAIL/2PASS和测试预期修正见[D18 ledger](superpowers/plans/2026-10-13-d18-progress.md)，不是修改游戏语法。

当前backend包：[25b00c8d产物](../.cache/d18-compat-25b00c8d-2791-4665-b237-aa7431569e63-artifact)，manifest SHA256 `f935f044cca99ee96149e5bcdbda2d3e414e1da29d1a54c8672cce082c50e2e5`。仅code-only/synthetic demo；每格实际新进程导入只在产物，无外网，资源正常关闭，源与包字节保留。维护backup/restore工具在当前工作树执行，再交给包内应用测试，不谎称demo包包含所有维护脚本。[当前来源绑定](../.cache/d18/current-backend-source-binding.json)核对84复制源/81Python与当前工作树及扩展交付输入身份一致，生成synthetic seed单列，不读取原seed作为绑定。

当前完整3446离线通过/14明确原skip，type/lint退出0；[377源码前后身份](../.cache/d18/final-current-before-identity.json)与after记录一致。发现原身份漏legacy requirements/CSS/图标后，[380交付输入扩展身份](../.cache/d18/current-release-inclusive-identity.json)独立保存为 `ccba59acc6ebfd1471c78618d63fecde3cf9ac97c735896496acc87c379c53c9`，不倒改377前后证据或声称新增3项当时也已捕获。legacy声明字节等于早先新backend包；CSS/图标与旧可信物理input/新build input字节同，详见ledger。完整门禁、实际构建/来源绑定各证明自己的范围，不借旧c34背书。

当前frontend：[独立产物](../.cache/d18-frontend-final-current-artifact)，manifest SHA256 `a61d4c431ff3102a44f9da37caec0ed48a3ca442628b64973467dacd873d0845`；[24源输入绑定](../.cache/d18/current-frontend-source-binding.json)与380/当前一致，编译包不是源文件复制。[实际HTTP](../.cache/d18/frontend-current-release.log)4页面/13static/1public、模块来源/正常关闭真实EXIT0；[两个容器输入](../.cache/d18/current-container-contexts.json)精确核验backend86/frontend2046文件，containerBuildVerified=false。当前整D18独立审查尚未完成，不是Docker/Linux/生产验收。

| 恢复schema | 当前backend产物核心 | 恢复后metrics HTTP | 未测能力 |
| --- | --- | --- | --- |
| 001 | 明确拒绝启动；输入摘要不变，无gateway/worker | 不开放 | Agent动态循环/候选操作UNKNOWN |
| 002–003 | 原局/消息读回，正常上下文提问，原UUID重放不再调用FakeModel或加次数；schema不变 | 固定503，缺004 | Agent动态循环/候选操作UNKNOWN |
| 004 | 同上，真实包代码执行，不editable回填 | wire3，发布后unknown/schema_5_required，不补0 | 恢复格Agent动态循环/发布操作UNKNOWN |
| 005 | 同上；四状态账本完整守恒另由当前工作树恢复测试证明 | wire3/partial，合成空观测0且披露覆盖缺口；不是恢复包内四状态聚合实测 | 恢复格Agent动态循环/发布操作UNKNOWN |

固定旧TS17 004包（下方VEVQiL及其固定摘要）对005真实拒绝，输入与包字节不变；不能自动退旧代码开放写入。旧包若不存在测试明确SKIP，不能冒充通过。以上仅本机合成/假模型程序边界，不是Linux安装、真实模型语义、生产停写/部署或真实用户质量。

## TS17历史冻结身份与证据口径（仅属于该旧版本）

- 当前代码/测试/锁配置的工作树摘要：`c34aaff77ab4f1b31a347efa447799e56dea8e7a79daa625c5126c557f4d0e9c`，356 文件。完整路径与逐文件摘要在[身份清单](../.cache/ts17/review-fixed-code-identity.json)。算法为相对 POSIX 路径按 JavaScript ordinal 排序，`SHA256(JSON.stringify([path,lowercase_file_SHA256] pairs))`；只读两遍核对内容没有变化。明确排除运行数据、dotenv、JSON语料、docs、缓存、Git历史和已安装依赖，不是整个电脑/私有数据的签名或公开许可证明。
- HEAD 仍是 `c5765b68cb251a7c566e76e2887d335d6ed6b285`；没有创建新提交，**HEAD 本身不能代表这些未提交的升级代码**。原始 HEAD 的功能兼容性是 UNKNOWN。
- 当前 backend code-only 合成包：[VEVQiL artifact](../.cache/ts17-backend-VEVQiL-artifact)，release-manifest SHA256 `ab61062c21dc29eaeca16234ed459415815eff10b1bb298922aaf73c2220fa85`。[只读源码绑定](../.cache/ts17/review-backend-source-binding.json)核对固定 allowlist 的77个复制文件（其中74个 app/eval Python 文件）与当前工作树一致，且 exact artifact verifier 通过。包内 `app/soups.py` 是生成的合成替身，不与原私有题库比较，不读取原 seed；不能声称全部 app 文件都是原源码副本。[真正新解释器 demo 冒烟](../.cache/ts17/metrics-source-backend-release.log)只证明该包的合成 seed/health/chat replay/来源/资源关闭，不自动证明以下 schema×功能所有格。
- 矩阵执行器：[实际恢复业务测试](../backend/tests/test_release_recovery_business.py)，是当前 `create_app` + 临时库 + FakeModel/合成确认。[修改后实际整套 XML](../.cache/ts17/review-fixed-final-verified-20261013/review-fixed-whole-sequential.xml)中的 `test_restored_schema_matrix_uses_actual_current_startup_and_business_replay[1..4]` 和 `test_latest_api_agent_publication_data_survives_restore_and_rule_rollback` 均通过，整套2774cases/0failure/0error/14skip。[唯一审查和一次修复](ts17-review-resolution.md)保留首次失败/定向复验/最终完整结果；不把旧metrics单元报告叫作修改后全项目门禁。
- 修改后 frontend 包为[当前独立产物](../.cache/ts17-standalone-review-fixed-66a0b318-7369-48d6-aaf8-55b0313b88e2)，manifest SHA256 `6348f0eb732f8e41a0a4f19643d5b9f9d6612abadac32bef28fa3e2df5fdd88e`。[源码绑定](../.cache/ts17/review-fixed-frontend-source-binding.json)核对22个生产src文件与上述身份一致；[实际HTTP冒烟](../.cache/ts17/review-fixed-standalone-release.log)核验4页面/13静态资源/1public及正常关闭。旧 `7ebe6a8c...` 仅为历史，不与当前源码配对。[两个容器输入验证](../.cache/ts17/review-fixed-container-context-verified.json)仍不等于Docker镜像验证。私有统计 wire2 需与后端同步更新，数据库 schema 编号不是 wire 编号。

## TS17历史恢复后的功能矩阵

“已验证”仅限本机上述执行器实际完成的动作。Agent 最低003/metrics最低004是源码门禁，不是恢复后的全功能测试结论；应用默认最低002、迁移CLI默认001保持不变，没有自动补003/004。

| 数据 schema | 快照原语 | 当前默认核心（合成库恢复后） | 反馈/候选/发布与回滚数据 | 动态 Agent 循环/工具重启 | 私有 metrics 恢复后 HTTP |
| --- | --- | --- | --- | --- | --- |
| 001 | 已测备份/NEW恢复与摘要 | **拒绝启动**；恢复库字节不变，无 gateway/worker，不开放写入 | UNKNOWN；缺002/003不能凭版本猜测可用 | UNKNOWN；缺003，不支持开启 | UNKNOWN；缺004，不支持查询 |
| 002 | 已测 | 已测 GET旧局、新建/提问、原编号重放；2局/2turn/4消息/各计次1，schema不变 | UNKNOWN；未在此恢复格执行候选功能 | UNKNOWN；缺003，不支持开启 | UNKNOWN；缺004，不支持查询 |
| 003 | 已测 | 同上，真实 schema003 下原记录/新写入/幂等守恒 | UNKNOWN；未在此恢复格执行审核/发布 | UNKNOWN；没有该恢复格的实际动态循环证据 | UNKNOWN；缺004，不支持查询 |
| 004 | 已测 | 同上；另有 latest-business 全链路守恒用例 | 已测最新4局/4turn/8消息及反馈/任务/候选/不可变版本；恢复后批准/发布回执重放、指针回退且原记录不丢不重；**不是新真人审批或模型质量** | UNKNOWN；恢复用例关闭实际资源并重放业务方法，不能冒充完整模型循环重启 | UNKNOWN；统计单独 HTTP 已测004，但未在该恢复用例做 metrics HTTP，不能合并成此格支持 |

上述是**当前代码调用矩阵**，不是“任意编译包都兼容”的列表。同一 artifact 另一次启动/安装环境或另一 release 必须有明确对应证据；未测包/原始旧 HEAD 均 UNKNOWN。当前包的 smoke 不抹掉这些 UNKNOWN。最新快照中的审计/Trace等辅助文件也须保持精确集合与字节；不因表面健康或schema整数就签收。

## 为什么未知时必须保持维护

1. 先拒绝新写入，并核对 API/Agent/model/audit 在途真正收尾，以及 API、cron、timer、legacy merge/cleanup、人工脚本/direct DB 的状态。LOCAL inventory 声明不能发现或关闭生产全体写入者。
2. 故障后备份**最新已提交状态**，不是发布前旧库。原语只恢复到 NEW 目录，不覆盖当前库；合法旧备份也可能丢掉新数据，业务测试有独立反例。
3. 优先关闭故障能力/回退规则指针，保留最新局、反馈、任务、版本和回执。代码回退只能引用已验证读写当前 schema/功能的 release；未知旧代码继续维护，在副本验证前滚。
4. 需要的功能格是 UNKNOWN、资源仍在途、manifest/source变化、许可/数据身份不明或恢复核对失败时，不开放生产写入、不自动启动旧 JSONL/merge/cleanup。
5. `quiescenceVerified=false`、`productionReady=false`不改成真。不是安全上线命令，未验证 TLS/SSH/真实定时任务/实际服务器容量或磁盘彻底丢失场景。

实际命令、正常关闭、源保护、symbolic-link权限跳过及容器边界见[本地 how-to](howto-local-release.md)、[资源测量](ts17-resource-measurements.md)、[阶段 ledger](superpowers/plans/2026-10-12-ts17-progress.md)。所有练习只针对本次独占的合成目录；不得照着命令换成真实玩家目录。
