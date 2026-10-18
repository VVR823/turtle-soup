# TS09 唯一独立审查处置

审查者 Raman（01a11b81-a4d9-7461-9998-b1a423a29d0d）已终态完成并关闭。原报告 `.cache/ts09/reviewer-probes/terminal-review.md`，独立探针23个不同案例：13个控制通过、10个失败断言，对应6 Important（8个失败案例）和2 Minor。没有第二次审查、模型调用、付费步骤或生产操作。

主执行者修复前核验48个冻结文件、HEAD、分支和index SHA全部相同。原 `.cache/ts09/source-freeze.json` 保留为审查前证据；修复后不再声称源码hash仍相同。独立报告没有运行父完整/UI门禁，下面父证据与其分开计数。

## 一次 Important 修复回合

源码和复现核对后保留0 Critical /6 Important /2 Minor等级。永久回归 `backend/tests/test_ts09_review_regressions.py` 首次16个真实失败、0 collection error；不是放宽原断言。以下六项修复的相关组合120通过；自查追加损坏标记2真实失败，随后18个永久回归与30个原fallback用例共48通过。完整/UI最终门禁仍需另外签收。

| 发现 | 一次修复与边界 |
| --- | --- |
| I1 晚到写入失败无归属、关闭恢复泄漏原异常 | 普通保存、显式恢复和关闭恢复共用实际任务所有者；等待超时后仍由原worker保存有界RAM/永久缺口并尝试持久化安全标记，回调消费异常，不打印原异常。rollback/close失败不能阻止fallback/sidecar；确认commit成功不重复写。前后等待两类回归确认未双记丢失；8实际名额、500ms等待、250msSQLite、2s关闭不变。 |
| I2 sidecar错误形状当无缺口 | SQL和文件使用同一严格、有界、单调合并器：确切两个字段、bool、非负signed64、拒绝重复键。非零dropped即表示缺口，损坏/超限/歧义保守不完整。不尝试自动清除缺口。 |
| I3 超限旧文件卡住合法RAM恢复 | 旧文件仍原样保留并保持永久缺口；独立RAM快照可恢复到健康SQL。remaining包括旧文件哨兵和RAM；一个不可用sink后停止本轮，避免每项重复busy等待。8个真任务加第9个缓冲，最终9行及文件不变已测。不把内存称作持久化。 |
| I4 默认窗口随时间移动漏分页 | 新规范cursor同时绑定createdAt/eventId及实际start/end/eventType；后续省略条件继承首屏，显式不同条件拒绝422。继续≤512字符、≤31天和独立管理员鉴权。审计接口本阶段尚未生产发布，因此未放行不含窗口的旧裸cursor；开始新查询即可。 |
| I5 CHECK字面量被lower忽略 | 只规范化引号外SQL语法，字符串字面量大小写/空白保留；实际SQLite拒绝注册值的漂移定义被核验拒绝。001/002 SQL和checksum均不改。 |
| I6 201字符兼容旧ID恢复500 | 可选关联拒绝时原子省略ID、metadataTruncated=true，不截成另一个身份；后续metadata不能覆盖已发现缺口。合法GET恢复200、原ID/历史不变、日志ID null。没有放宽Chat/Evaluate请求合同。首次I6选测为2通过/1失败：响应已200，但后续默认metadata覆盖标记；查明后修正，最终5个相关用例通过，保留中间XML。 |

证据目录 `.cache/ts09`：`review-fix-red.xml`=16/16失败，`review-i2-green.xml`=11通过，`review-i5-green.xml`=7通过，`review-i4-green.xml`=21通过，`review-i6-verified.xml`=5通过，`review-fix-selected-green.xml`=120通过，`review-marker-edge-red.xml`=2失败，`review-fix-final-selected.xml`=48通过。各选测有重叠，不相加成总数。`review-i1-green.xml`为26通过/1尚未实施I3的失败，不误标整体GREEN。

## Minor 保留

M1：恢复报告的recovered/duplicates仅计文件，不计实际已恢复RAM；实际行不丢，但报告低估。M2：供应商content非法时已返回的合法usage可能仍记null；不会把非法答案放行或假造0。确认Minor，安排TS17最终故障演练前修复；本轮未修，不用更多探针/复审扩展本阶段。真实provider/token账单/人工质量仍没有证据。

## 全部 Declined to judge 主执行裁定

| 独立审查未判断项 | 裁定与后续 |
| --- | --- |
| 1 断电、控制器耐久、DB+磁盘+进程同时失效 | 外部门禁保留；RAM/缺口无法永久保存的边界不隐藏，TS17仅做有授权本地合成故障。 |
| 2 多进程共享fallback/分布式审计 | 本阶段明确单实例；不宣称跨进程锁或可靠队列。真实部署拓扑另行核验。 |
| 3 大DB/WAL冷启动复制/慢磁盘/生产P95 | TS16合成性能及后续真实授权；小文件保全不是延迟证明，不读生产数据压测。 |
| 4 源writer修改后恢复文件/实时备份竞态 | CLI前提停写，本地校验不当作在线原子备份；生产迁移/备份未授权。 |
| 5 residual native IO之后整个进程退出时长 | 2秒是调用等待上限，不是强杀线程或进程退出承诺；保留实际任务计数。 |
| 6 未启动503和仍在执行HTTP覆盖 | 无Store不能保证持久化；status是快照。已准入最终失败不得漏记由I1修复。 |
| 7 002前历史尝试/回填质量/用户统计 | 不倒推、不伪造；旧unknown/null不是质量或用户增长证据。 |
| 8 真实免费账户/provider/远程取消/token账单/人工标签 | 外部证据保留；TS11–12准备独立评测工具，不自费或读取账户秘密。 |
| 9 生产迁移/备份/降级/滚动发布/上线 | 本地隔离演练范围；没有生产签收和发布授权。 |
| 10 父完整门禁、239原文件hash、生产EXPLAIN | 独立只核48冻结文件和自有数据；父门禁单独记证据，生产查询延迟不宣称。 |
| 11 旧反馈JSONL/发布改造/反馈正确性 | 继续TS10，002表存在不等于反馈流程已实现；I5当前核验责任不能推迟。 |
| 12 default-off私密诊断Trace文本保存/轮转 | 旧诊断不是必需审计，不作公开安全承诺；后续隐私/部署文档和授权保留。 |
| 13 standalone/嵌入式db.create_session全部外部调用 | 管理HTTP已走create_game_once，未覆盖所有任意外部Python调用；不扩大生产保证。 |
| 14 TS08两Minor和TS07 free-win Minor | 原台账保留TS17，不重审已签收阶段。 |
| 15 全repo视觉/PR/Greptile/发布队列/全局学习 | 当前本地后端范围，不运行远程PR/全局写入/模型fanout；不冒称发布完成。 |

最终父证据：完整70468退出0，992后端/9skip+182Vitest+25Node+3API=1202离线通过，API114932正常退出。post-review-full-gate.xml实际1001/0/0/9，post-review-frontend.xml182/0/0已读。UI20209退出0，post-review-ui.xml25/0/0已读；mLCusk隔离build成功、nonce1750e1ea-5688-472c-97d8-fcc21b9ca1d9、API109840正常关闭、frontendCLOSED0/bothcleanup0。lint/typecheck64195退出0、diff0；UI后原WindowsPowerShell5格式239文件SHA=d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a未变。未把父证据算成独立审查执行数。

结论LOCAL_VERIFIED_WITH_CONCERNS：六项Important一次修复并最终本地签收，2 Minor和外部限制如实保留；直接继续TS10。18阶段整体未完成，不结束目标或心跳。
