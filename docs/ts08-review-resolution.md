# TS08 独立审查处置

2026-10-08，唯一新上下文审查者Socrates（01a11a60-d766-7871-b17f-85ffef24bd2b）终态完成并关闭，无复审。原报告`.cache/ts08/reviewer-probes/terminal-review.md`。修复前主执行核对46冻结文件、HEAD/分支/index全部一致；保留原manifest，修复后不声称hash仍相同。

## 唯一修复回合

0 Critical /3 Important /2 Minor，主执行逐项核对源码与复现，接受等级。

| 发现 | 处置与永久证据 |
| --- | --- |
| I1 A→B→A后pending被last_session挡住 | 修复。路由原操作可读；只有规范GET核验session/soup、generation/journal及初始化捕获指针未变，才接回原指针。保留过期/外来写入栅栏，不换UUID。51项中5真实RED→51通过，另2新保护controls；UI验证原UUID、原指针、一轮问答、一次扣数。 |
| I2 turn404丢掉终态 | 修复。规范GET已结束则展示保存结果，不POST问题、不以404声称未扣数；solved-null走原幂等揭晓。given_up/solved/solved-null三项真实RED→全前端182通过；UI验证未送达问题与其他客户端揭晓并存。 |
| I3 缺必填次数变无限 | 修复。仅显式null表示无限，undefined拒绝。5项decoder+1项真实GamePage先RED→33通过，保留journal、禁止操作；UI删除真实创建响应字段，再按原UUID找回同一局。 |
| M1 返回旧页复活过期页码草稿 | 确认Minor，安排TS17最终页面回归：页1输入3→next→previous应显示1。此轮只修Critical/Important，未修此项。 |
| M2 锁屏提交前storage失效逃出try | 确认Minor，安排TS17站点故障回归：提交时首次读凭证进入错误处理，显示重试、不放行。未修，未证明凭证泄露/开锁漏洞。 |

新增16项永久前端测试，14真实RED、2保护controls。I1首次新夹具错误：LastSession误作GameTarget、turn故障时规范GET也回turn体；初次51/6失败与首次green文件51/2失败保留，不当最终证据。修正夹具并仅暂退本回合实现后51/5真实RED→同一修复51/0；不是第二轮审查、不改既有断言。I3 33/6 RED→33/0；I2 54/3 RED→全前端182/0。

## 证据与边界

审查者自己执行：166既有前端、13指定Node、2合成后端通过；额外12 authored tests中8失败期待/4控制通过，另M2 unhandled SecurityError。类型/lint/diff通过。未运行父完整后端/UI，读XML不等于自己执行；初始sandbox失败与合成error testcase不累加缺陷。

主执行修复后：760后端/9跳过+182前端+25Node+3API=970离线通过，另25UI通过。`post-review-full-gate.xml`769/0/0/9、`fix-final-frontend.xml`182/0/0、`post-review-ui.xml`25/0/0（均.cache/ts08）。全gate65012退出0/API80272正常关闭；UI64291退出0、iVfOuV隔离build0、nonce a5226506-053d-4657-96d4-0340bd838096、后端103068/前端CLOSED0/双fixture cleanup0。typecheck0、root lint73369退出0、diffcheck0。239原文件SHA保持d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a；pytest既有缓存拒写warning未改ACL/删除缓存。

新增3UI为修复后整合验证，不声称它们先RED；主执行实看新增导航/缺turn终态截图。API/UI同用18080，后续服务器串行；本次实际API退出后UI才绑定，不把偶然无冲突当并发保证。

## 完整 Declined to judge 主执行裁定

| 未判断行为 | 裁定 |
| --- | --- |
| 真实provider语义/提示/通关覆盖准确率、免费资格、取消、token成本 | 外部证据保留；TS11–12准备独立评测、TS09记录未知usage。无真实调用/账户读取，不宣称通过。 |
| 生产迁移/部署/保存/备份回滚/TLS/代理/多worker/发布包 | TS17本地演练及后续明确生产授权，隔离页面build不是发布包证明。 |
| Safari/iOS/Android/其他OS/真键盘/隐私storage | 外部设备矩阵保留，Edge390视口/jsdom注入仅对应本地证据。 |
| 审查者视觉签收/全视口/可访问性/焦点陷阱/原生网络隔离 | 主执行8原截图+2新增/几何验证，不称审查者视觉签收；全面可访问性/OS网络沙箱未验证。 |
| 线上负载/10倍流量/延迟/内存耐久 | TS16–17合成演练准备，不虚构线上指标；本阶段仅有限轮询。 |
| 原子多tab锁/跨设备/清storage后恢复 | 设计非目标，继续标明；普通A→B→A不能免责，I1已修。 |
| TS01–07重审/TS07 M1 free-win防御 | 不重做已验收阶段，原Minor单独保留，本次未改评分。 |
| TS09 attempt日志/TS10反馈与规则发布/TS15管理员写并发 | 继续后续实施，目录与凭证初始化不能冒充这些机制完成。 |
| 私密dotenv/玩家内容/每条生产记录完整性 | 禁止读取；主执行只核239文件hash，未读内容或声称逐记录验证。 |
| 审查者未跑全760后端/3API/另12Node/25UI | 主执行实跑完整门禁，审查者独立计数仍166/13/2，两者不归并。 |
| 远程CI/Greptile/外部审批/真实用户验收/发布PR | 授权外保留，无公开上传/推送/PR/生产发布。 |

结论LOCAL_VERIFIED_WITH_CONCERNS：3 Important已一次修复/完整本地门禁，M1/M2及外部门禁如实保留。进入TS09，不是18阶段总目标完成。
