# TS17 唯一审查与一次修复记录

状态：DONE_WITH_CONCERNS，仅 TS17 本地工程子集。唯一审查后的两项 Important 已在一次修复中验证；原D18、完整生产A58–A59及真实质量门禁仍未满足，不是上线记录。

## 审查身份与范围

唯一独立审查者 Peirce：`01a1306c-a269-7c81-8078-0b1056f4e239`。实际最终报告为 **0 Critical / 2 Important / 1 Minor、With fixes**；报告收到并封存后关闭该审查者。额度恢复接续的是同一审查者，没有重派或第二轮复审。[完整原报告](../.cache/ts17/final-review-report.md)和[全部16项未判断裁定](../.cache/ts17/final-rulings.md)保留，不将未判断项默认为通过。

## I1：手机统计来源分组表难读

实际27组、375px页面反例先失败：版本列30.65625px、日期列40.171875px、单行420px。不是仅检查源码 class，也不是在 jsdom 假测布局。[真实 RED](../.cache/ts17/review-metrics-readable-red-verified/review-metrics-readable-red.xml)保留32通过/1失败。

修复仅改变统计分组表的局部横向滚动、日期/版本/计数列宽，以及管理页面在 flex 布局中的宽度约束；完整版本摘要不截断，区域可键盘聚焦后横向滚动。普通玩家问答、模型、计次和存储没有改动。

第一版修复虽然改善单元格，但实际容器右侧735px，仍失败，未冒称绿色。[失败证据](../.cache/ts17/review-metrics-readable-first-fix/review-metrics-readable-green.xml)保留。之后核对真实 body/main 布局，最小补充主区域 `w-full min-w-0`，没有放宽375px边界断言。

最终固定 Edge 全套实际 **33通过 / 0跳过，XML85.77112秒**；原服务正常关闭。版本列304px、日期93.796875px、最大行高48px，容器33..342px、client307/scroll1592px，document375/outside[]。完整版本文本及真实 ArrowRight 滚动断言通过；桌面和手机截图已实际查看。[最终XML](../.cache/ts17/review-metrics-readable-fixed-verified/review-metrics-readable-fixed-green.xml)、[几何证据](../.cache/ts17/review-metrics-readable-fixed-verified/ui-results/admin-metrics-owned-real-b-29288-download-and-test-exclusion/metrics-mobile-readability.json)、[手机截图](../.cache/ts17/review-metrics-readable-fixed-verified/ui-results/admin-metrics-owned-real-b-29288-download-and-test-exclusion/metrics-complete-mobile.png)均另存，不覆盖旧审查证据。横向长表仍需主动滚动，不代表所有设备/辅助技术已验收。

## I2：没有冻结身份的恢复兼容矩阵

新增[恢复兼容矩阵](release-recovery.md)，由[本机操作指南](howto-local-release.md)链接。逐格区分快照原语、当前核心、候选/发布回滚数据、动态Agent和metrics；001拒绝/002–004已测核心、未测组合UNKNOWN分别记录。旧HEAD和未测包不得据此自动恢复生产写入。

当前356个代码/测试/锁配置文件只读复核0差异，摘要 `c34aaff77ab4f1b31a347efa447799e56dea8e7a79daa625c5126c557f4d0e9c`；HEAD不是这些未提交源码的替代身份。77个backend复制文件与当前源码逐一绑定，生成的合成seed单独注明，不读原seed。矩阵源测试及已有XML已核对。修改后frontend新产物6348f0eb...已经真正启动、资源核验并正常关闭，22个生产src文件绑定当前代码；详情见矩阵。两个容器输入79/2046文件验证通过，仍不是镜像。新全项目回归首次因3个合成worker等待超时失败，原断言定向15项通过后完整串行复验也通过；均保留实际证据，不将旧报告/旧包叫作修改后全套验收。

## 修改后的最终门禁

实际完整串行47548 **EXIT0**：Python XML2774cases/0failure/0error/14skip，2760通过（含Eval）、XML595.677秒；前端365、Node103、API3均实际通过，合计 **3231离线通过**。API21144正常关闭。前述布局修复后Edge33通过/0skip、typecheck/lint/隔离standalone构建/真正包HTTP冒烟也通过；没有源码变化后偷用旧门禁。

[本次完整证据归档](../.cache/ts17/review-fixed-final-verified-20261013)保存最初全量失败、原断言定向15通过及最终串行全量，失败没有覆盖或删除。最终[离线XML](../.cache/ts17/review-fixed-final-verified-20261013/review-fixed-whole-sequential.xml) SHA256 `ae1982ad9f371de27a8d123a696520ddb5a6aacaec17ceb9a35dcba04371c229`，修复后Edge XML SHA256 `ca1ff5e44dd43ce977c8d9d769087036c448bfadfb48ffdd4ec222cf2eb06564`。

[最后源码检查](../.cache/ts17/review-fixed-final-verified-20261013/review-fixed-final-code-check.json)重新枚举356文件并核对完整集合/内容，摘要仍c34aaff...；[保护检查](../.cache/ts17/review-fixed-final-verified-20261013/review-fixed-final-protection.json)再次确认原239规范WinPS5.1摘要d9662e...、HEAD/index不变。不是第三方认证，也未查询原玩家记录。

全量首次三个夹具超时、定向无修改通过、去除并行构建/复制负载后的完整通过，只说明当前串行门禁已通过。不能证明特定磁盘、杀毒程序或CSS是根因，更不能据此声称修复了新的生产Agent死锁；10秒夹具在繁忙机器上的时间敏感性保留为测试运行限制。后续完整门禁串行，不在同时执行大规模依赖复制/构建时给它背书。pytest根缓存权限与Node颜色环境warning、6链接权限/1Unix/7真实模型opt-in跳过均如实保留，不改ACL/系统权限。

## Deferred minors

M1：后端内部解码遗漏新来源对象/字段时会补保守unknown/null，前端要求完整字段。这与子计划“缺字段拒绝”不完全一致，作为防御性契约欠项保留，未夹带到本次 C/I 修复。当前正常HTTP输出完整，没有制造0次失败或质量结论；没有新增让调用方提交统计对象的入口。

## Rulings I made

全部16条及错误代价逐条列在[裁定文件](../.cache/ts17/final-rulings.md)。生产写入者、真实数据迁移/恢复、未知旧release、Docker/Linux、TLS/代理/SSH、真实模型/免费资格、人审标签、原D18发布后collector、未测性能/容量、14跳过分支、来源认证/许可/供应链、敌对文件系统、其它设备/a11y、独立原239认证、TS18公开A60及远程CI均不被本次LOCAL证据吞掉。

尚未满足原D18可信采集；未知来源字段不是其完成证明。TS18仍是下一本地阶段，公开上传/生产/真人学习掌握不由本报告批准。
