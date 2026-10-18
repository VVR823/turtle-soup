# 原C/IR/补充约束统一对照：非整体签收

2026-10-16最终本地复核：当前版本完整后端/离线评测3094PASS/14SKIP、前端722PASS、框架103PASS、API3PASS、受控Edge35PASS，全部0失败错误；类型和lint退出0。下表C01–C24的本地可执行映射由本轮全量结果重新绑定，真实模型、人审、CI平台、生产和公开边界仍HOLD。详见[最终本地报告](local-acceptance-final-2026-10-16.md)。

2026-10-15。cb93c0实际读回原24组测试矩阵、24项整改、OV1–3/SG1，并核四份原文件SHA与[原范围清单](../.cache/d18/original-completion-scope-current.json)完全相同。该JSON的pending等状态是历史，不能当当前事实。本页关联已逐断言审计的A页，不把“有测试文件”当完成证明，不修改原验收清单。

当前本地证据基准为398/55462476…、[实际完整门禁](a46-local-verification.md)3515离线PASS/14明确skip与35 owned Edge；同一成绩不重复累加。A页内有具体模块、断言、XML/身份和额外探针的范围。本页是范围交叉核对，不是另一轮独立审查或新测试执行。原计划文件名有request_contracts/host_result/turn_transactions/e2e等示意名，当前实现拆分为request_contract/host_contract/game_transactions及tests目录；以行为与具名证据对应，不要求制造同名空测试。

## C01–C24

“本地映射”只表示A页已核对应的本地断言；系统能力skip、真实质量、覆盖率和外部门禁均不因此通过。

| C | 原核心要求与当前证据 | 结论/剩余依赖 |
| --- | --- | --- |
| C01 | [A01–12](acceptance-a01-a12.md)：隔离/导入/锁定环境/标记/严格匹配 | 本地映射；当前干净commit checkout、远程CI/OS矩阵未验收 |
| C02 | [A01–12](acceptance-a01-a12.md)、[A34–35](acceptance-a34-a35.md)、[A47–49](acceptance-a47-a49.md)：001/002/003各阶段版本/故障回滚 | 本地映射；生产迁移未授权 |
| C03 | [A01–12](acceptance-a01-a12.md)：旧ID/时间/计数/消息、坏行、未配置与损坏 | 本地映射；不查询真实玩家库 |
| C04 | [A01–12](acceptance-a01-a12.md)：scene/UUID/null/未知字段/500与501/32KiB/2000与2001 | 本地映射，额外4实际HTTP探针单列 |
| C05 | [A01–12](acceptance-a01-a12.md)、[A22–29](acceptance-a22-a29.md)：严格HostResult/解析错误/语义错误分开 | 本地映射，不代表语义真值 |
| C06 | [A18–20](acceptance-a18-a20.md)、[A21](acceptance-a21-admission.md)、[A01–12](acceptance-a01-a12.md)：窗口/代理/期限/占位/队列 | 本地映射；实际免费资格HOLD |
| C07 | [A01–12](acceptance-a01-a12.md)、[A30–33](acceptance-a30-a33.md)：并发开局/丢响应/原ID/浏览器初始化 | 本地及owned页面映射 |
| C08 | [A13–17](acceptance-a13-a17.md)：最后名额/整轮事务/写入故障/无模型长事务 | 本地映射，不扩称多机锁 |
| C09 | [A13–17](acceptance-a13-a17.md)、[A30–33](acceptance-a30-a33.md)：预留/迟到/丢响应/未知状态恢复 | 本地映射，取消不等于远端停止 |
| C10 | [A13–17](acceptance-a13-a17.md)、[A22–29](acceptance-a22-a29.md)、[A30–33](acceptance-a30-a33.md)：揭晓互斥/solved/持久结果 | 本地与owned页面映射 |
| C11 | [A22–29](acceptance-a22-a29.md)：exact最小对立/版本/上下文/有锁TTL-LRU/返值隔离 | 本地映射，检索不是事实判决 |
| C12 | [A22–29](acceptance-a22-a29.md)：严格覆盖/还原null/难度/彩蛋与质量分离 | 本地映射，特殊故事不从评测分母删掉 |
| C13 | [A30–33](acceptance-a30-a33.md)：初始化/切汤/generation/原ID | 本地与owned页面映射 |
| C14 | [A30–33](acceptance-a30-a33.md)：错误类别/刷新/同ID重试/终态 | 本地与owned页面映射 |
| C15 | [A20管理员矩阵](acceptance-a20-admin-matrix.md)、[A30–33](acceptance-a30-a33.md)、[A36–38](acceptance-a36-a38.md)：公私DTO/站点门禁/合法揭晓 | 本地映射，不宣称实名用户隔离 |
| C16 | [A34–35](acceptance-a34-a35.md)、[A36–38](acceptance-a36-a38.md)：HTTP与业务审计/fallback/缺口/隐私 | 本地映射，unknown保留null |
| C17 | [A36–38](acceptance-a36-a38.md)、[A39–40](acceptance-a39-a40.md)：反馈CAS/导入/冻结许可/旧Trace | 本地映射；未把合成资料当真人反馈 |
| C18 | [A39–40](acceptance-a39-a40.md)、[A54–56](acceptance-a54-a56.md)：人工声明门禁/绑定/CAS/回滚/停版 | 程序与owned页面映射；真正语义人审HOLD |
| C19 | [A41–43](acceptance-a41-a43.md)：规模/来源家族/去重/hash/holdout隔离 | 工程映射；110 pending，真人标签/正式封存HOLD |
| C20 | [A44–45](acceptance-a44-a45.md)、[A46](a46-local-verification.md)：全失败分母/相同预算/实际旧驱动 | 工程映射；合成九报告不是三系统真实质量实验 |
| C21 | [A47–49](acceptance-a47-a49.md)：五白名单工具/候选报告/固定回归/归属 | 本地映射；真fact配错答案只待人审，不是自动语义判真 |
| C22 | [A51–52](acceptance-a51-a52.md)、[A54–56](acceptance-a54-a56.md)：动态分支/有限停止/候选不可越权 | 合成工程映射；真实模型安全候选及8个真人参考任务HOLD |
| C23 | [A51–52](acceptance-a51-a52.md)、[A21](acceptance-a21-admission.md)：预算/三断点/独立心跳/旧owner | 本地映射，含3独立进程探针；非断电或远端exactly-once |
| C24 | [A57](acceptance-a57.md)、[A58–60](acceptance-a58-a60.md)：统计/20样本/最新库恢复/兼容/代码产物 | 本地映射；真实维护/TLS/SSH/镜像/公开与本人掌握HOLD |

## IR01–IR24

采用原IR编号/决策，不把JSON历史“未实施”沿用为今天结论。下面C列回指上表与具体A页，并保留每项不可由测试代替的含义。

| IR / 决策 | 对应组 | 核对结果/边界 |
| --- | --- | --- |
| IR01 / D2 | C23 | 持久预算9/7后仅余各1、原deadline/意图先记；不承诺未知远程调用不重复 |
| IR02 / D3 | C18/21 | 审核显示事实与短理由，显式确认后才可发布；没有自动识别所有“真fact错答案”的语义oracle |
| IR03 / D4 | C06/09/23 | 实际双残留owner占位及第三次HTTP忙碌；业务lease与模型清理不混同 |
| IR04 / D5 | C24 | 最新NEW副本、完整业务辅助表/收据、实际新旧包拒绝矩阵及runbook；生产全写入者未证实 |
| IR05 / D6 | C17/21/23 | 脱敏TaskContext/row_version/许可冻结与撤回，缺Trace不捏造；不谎称已发云输入可追回 |
| IR06 / D7 | C18 | 旧局pin、显式停版阻止旧在途写入、回滚保留历史 |
| IR07 / D8 | C23 | 阻塞仍独立心跳、失租/接管拒绝旧owner、有限关闭 |
| IR08 / D9 | C11/21 | exact-key版本/最小对立、模糊仅证据；不可由穿越自动推出魔法 |
| IR09 / D10 | C05/12/21 | 严格结果/DraftRecord及不同digest域、报告/候选归属 |
| IR10 / D11 | C08/16/18 | 同事务审计、fallback/缺口/重放；已提交游戏不因日志再执行 |
| IR11 / D12 | C01/02/03 | 导入纯净/显式初始化；缺配置与已配置损坏严格区分 |
| IR12 / D13 | C04/07/13/14 | 旧payload相符兼容，原ID耐久、pending/迟到UI不覆盖 |
| IR13 / D14 | C15/16/21/24 | 公私DTO、公开搜索不取私有事实、合法揭晓保留；不是实名多租户 |
| IR14 / D15 | 全C | 24组行为均已关联A页；真实/平台及分支覆盖率缺口仍保留，不能全项签收 |
| IR15 / D16 | C01/06/13 | 离线前置保护/markers/实例隔离可核；远程CI仅配置未执行 |
| IR16 / D17 | C08/09/23 | 原生屏障/控时钟/逐SQL故障与新进程恢复；不冒充OS强杀/断电 |
| IR17 / D18 | C13/14/15/18 | 实际Vitest与owned Playwright全链路；合成页面响应明确标记 |
| IR18 / D19 | C19/20/22 | manifest/失败不滤/真实opt-in/holdout不入工具；真人封存及真实任务仍缺 |
| IR19 / D20 | C10/15/16 | playing禁止汤底与授权ended允许的成对测试，不把合法揭晓封死 |
| IR20 / D21 | C06/11/20 | 完整Turn窗口/输入字符预算/关键指令/超限失败，既有A22–29及runner证据；不宣称字符=token |
| IR21 / D22 | C11/16 | 有锁LRU/TTL/容量/克隆返回/版本及上下文排除 |
| IR22 / D23 | C06/22/23 | 2owner/32等待/单Agent/持久队列10；不把应用限额冒充全Web服务器线程总限额 |
| IR23 / D24 | C02/16/24 | 时间窗/游标/批量/EXPLAIN/上限；不是生产全库容量结论 |
| IR24 / D25 | C20/24 | 实际200会话/1000轮/5000审计、20样本及资源明确；另005规模副本不叫200真实执行 |

## OV/SG与五项原约束

- OV1：A04/A58的本地全部写入者演练、旧merge/cleanup禁止恢复已映射；productionReady/quiescenceVerified仍false，不能声称实际生产已停写。
- OV2：A24/A48/A54的上下文独立声明与同一次审核事实展示/绑定已映射；指代不明转人工。声明true不是人类确已正确判断。
- OV3：A48/A49/A54–56的唯一replace目标摘要/同key/临时release回归/CAS已映射；已批准内容被替换或证明陈旧则拒绝。
- SG1：001业务凭证、002同事务审计与内部CAS、003后TS15候选API按阶段映射；普通启动不自动升级/启用管理能力。
- 0付费：本次无采购、真实provider或新增付费；仅本地既有环境。历史一次免费旧卡授权不转给其它卡；实际卡0，代理未兑换。
- 免费模型不自动付费回退：策略负例通过不代表某供应商今天免费；有日期真实资格仍HOLD，不联网编造。
- 人类批准后发布：只有待审核候选；程序可校验声明/理由/证明/CAS，不能自己充当语义批准者。合成人审夹具不当真人批准。
- 保留历史与新数据：原239摘要/HEAD/index保护、NEW恢复及回滚保留新记录；不触碰真实生产迁移。
- 原“仅本地评审/文档”是2026-10-06历史授权，已由用户后续明确本地实施授权扩展；不扩为生产/公开/采购/全局系统策略变更。

## 仍需接续的本地审计

原测试计划除行为矩阵还要求关键分支/故障覆盖与关键路径注释。已有case数及全绿不能直接证明分支覆盖率；本页没有coverage百分比。下一步核现有coverage文件/配置是否可复用、按风险选择最小离线测量，并核事务reserve/commit/expire、网关期限/清理、worker claim/heartbeat、人工发布CAS和owned网络防护的注释。尚未逐条验证这些附加要求，整体目标保持未完成；先做不依赖真人/生产/公开权限的部分。
