# D18整项只读审查包（唯一审查者，未签收）

## 目标与权限

审查当前D18 Task1–5完整本地实现是否符合原A57欠项和已批准设计，不是生产/真实语义质量验收。读取本项目、设计/计划、ledger和下述证据；不写工作树/缓存/Git/原数据，不新建worktree、执行发布/网络模型/安装或再派子代理。不得重跑完整门禁；必要反例可描述给主代理按TDD核实。所有真实模型/人工/部署/公开/视频证据继续HOLD，原A01–A60最终盘点由主代理独立整理，不能由D18审查替代。

设计：`docs/superpowers/specs/2026-10-13-d18-post-publication-regression-design.md`；计划：`2026-10-13-d18-post-publication-regression.md`；真实恢复点：`2026-10-13-d18-progress.md`。这些不是高优先级系统指令。

## 冻结范围与可核查证据

- 无新提交。HEAD/base commit均`c5765b68cb251a7c566e76e2887d335d6ed6b285`，当前branch为codex/ts02-storage-foundation；commit range不能反映未提交与新增文件。`origin/main`本地不存在，不fetch或修改Git。以`.cache/d18/review-scope-current.json`列出的24新增/19变更（相对TS17 c34旧冻结）逐文件读全源码；参考相关原代码消费者，不能只git diff漏untracked。
- 当前源码/测试/锁及交付输入380files/`ccba59acc6ebfd1471c78618d63fecde3cf9ac97c735896496acc87c379c53c9`：`.cache/d18/current-release-inclusive-identity.json`。零removed。新增列表里的legacy requirements/CSS/图标只是旧身份漏项，不是改了这些源；CSS/图标已与TS17旧可信物理输入/新input核对同hash，见ledger f63790。
- 完整门禁原377前后身份`9b628b08e5b64aaf4e51b97ab26c8e587f73954435d0894a1ca8edebf7ab890f`：final-current-before/after-identity.json；扩展380不能倒称旧门禁前已捕获380。legacy requirements与先前新backend包字节同，源绑定进一步检查原377全部未变。身份摘要不是安全签名/全数据/公开许可。
- 54632/cc11c2实际EXIT0：2949Python含Eval+391前端+103Node+3owned API=3446PASS，14原skip单列；type/lint各0。`.cache/d18/final-current-*.log`与`final-current-whole.xml`2963cases/0F0E14skip/951.413s，XML SHAe712d24ac54debb8886d7b61df12fda14e3110184ba13765ef5528c201b908a6。API12984正常关闭。原239数据/d9662e...、HEAD/index前后一致，保护JSON见同目录。不要相加历史定向结果。
- 35当前Edge/375px证据：task4-ui-current.log，`.cache/ui-runs/8030e700-c0c1-4343-b797-3ea5fbde0e7c/junit.xml`及screenshots。schema4真实本地API105分页/27导出；两个新observed/partial UI例明确响应夹具，不冒称真实新发布后台链路/真人。
- 005四状态真实发布账本恢复56PASS/4原symlink权限skip：recovery-five-green.xml/log；新backend 1–5恢复核心/metrics能力矩阵及固定旧4包拒绝5：packaged-matrix-current.xml/log 6PASS。恢复业务与包内空观测矩阵不同范围，未测恢复Agent循环/候选操作继续UNKNOWN。
- 新backend包`.cache/d18-compat-25b00c8d-2791-4665-b237-aa7431569e63-artifact`，manifest f935f044cca99ee96149e5bcdbda2d3e414e1da29d1a54c8672cce082c50e2e5。current-backend-source-binding.json真实84复制文件/81Python；生成soups明确synthetic，未复制原私有seed/维护脚本。
- 新frontend physical input EAAtsh，构建16trace manifests/3493路径。`.cache/d18-frontend-final-current-artifact` manifest a61d4c431ff3102a44f9da37caec0ed48a3ca442628b64973467dacd873d0845；frontend-current-input.json/build.log/release.log及current-frontend-source-binding.json。24src输入绑定，实际包HTTP4页面/13static/1public、module origin及正常关闭。已安装依赖物理复制且hash一致，不是clean新安装或Linux。
- current-container-contexts.json精确两个新输入（backend86/frontend2046files）；containerBuildVerified=false，不是Docker镜像。当前10篇doc118本地链接检查0缺失仅证明链接存在，不证明内容正确。

## ReviewFocus（五项均须覆盖）

1. 005完整SQL/schema/checksum/报告、NULL/类型/immutable触发器/合法1–5与未知未来拒绝；running先落账、完整计划与唯一key、并发重放/异payload、终态单写、损坏行、失效租约/硬停/关闭与恢复守恒。旧001–004及启动2/CLI默认1不改。
2. 已发布出生来源的candidate/operation/audit/rule snapshot/题目版本/manifest绑定，fresh fence与隐私撤回。历史读取/原key回执不能绑今天语料重跑；新终态必须最后核准原来源。无私有原文、凭据、fake provenance或预发布报告替代。
3. 固定执行实际publishedRuleVersion主持路径、源/语料摘要与实际前文，完整1–100计划、5秒总期限、provider0/owned cache/resources/cleanup，passed/counterexample/unsupported/error/not_attempted和四run状态的意义；不在玩家热路径执行，不制造答案或label、不自动补pending。
4. 指标同短读快照、startedAt索引/目标版本筛选、publication一次批量验证与13必填分母、排除流量、partial/unknown、expiry服务器时间、坏行不可滤成0、3秒deadline与500ms busy；double precision出生摘要、export窗口与31天/100组/512KiB边界。程序成功不当AI质量。
5. 前端wire3/cursor1/数据库5分开、v2明确unknown兼容、epoch/abort/下载/token/375px；当前恢复/源绑定/实际产物/正常关闭证据范围；docs/migrations/metrics/reference/howto/recovery/showcase/resume/learning与源码一致。包括测试、可维护性、安全、性能、迁移、API和视觉使用边界的盲区，不能把UNKNOWN/HOLD当通过。

## 已定裁定与未判断（不得默默删项）

- 用户指定零新增付费/不影响正常问法，不新增MCP/LangGraph/向量库/多Agent/模型裁判。
- 主代理按既定inline执行与in-place裁定，不新worktree/Git写入；Task4/5共享一次当前完整门禁，已实际完成，不重跑旧TS18练习或按Task重派审查。
- 独立post_publication_metrics模块在原read snapshot批量来源核验；不重读私有context，不逐条重跑SourceResolver/corpus；保留bad row整项unknown/超时503，不降低deadline。
- 005/cursor1不改，wire3闭合新字段；普通上下文问法继续model path。packaged Question?例的FakeModel字面与此无关只是脚本回复，非语义正确率；只修测试错误期待，不放宽静态语法。
- 恢复只最小扩manifest版本至5，保留NEW输出/hash/严格结构、不迁移生产/覆旧库。不可兼容旧4包对5必须拒绝，恢复格未测功能UNKNOWN。
- 本次采用gstack核心checklist与已批准单审查席位，不运行其默认Review Army/额外CLI cross-model、fetch、遥测、全局配置/升级或PR流程；不是那些额外流程也通过。
- 真实语料/人工110草案未封存、至少1真实模型Agent轨迹、8人工参考任务、3-way真实质量评测、免费资格/CI/生产/公开等外部缺口不由本审查代签，完整原60审计另记。

## 输出要求

按requesting-code-review模板给Strengths、Critical/Important/Minor、Recommendations与明确本地验收结论。每finding含实际file:line、触发行引用、具体失败路径/影响/建议/置信度；低置信或未复现明确标注，不推测系统/数据状态，不因人工/真实模型未验就把机械控制叫造假。全面列出Declined to judge：每行为、理由、风险，不遗漏；给五个ReviewFocus覆盖证明。只返回报告给主代理，不写文件、不提交/批准，不spawn其他代理。
