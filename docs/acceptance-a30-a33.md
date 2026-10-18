# A30–A33 前端恢复与默认隔离验收

2026-10-15。本次是原验收逐断言映射，不是重跑已验收门禁或新增独立审查。实际核对当前398文件身份55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32，0字节漂移；下述25份实现/测试/配置均在该冻结清单内并逐文件匹配。原18阶段/A01–A60等范围不变，真实模型质量、人审、生产与公开仍不据此通过。

## 实际证据与计数边界

- [完整前端退出回执](../.cache/a46/review-final-frontend-exit.json)实际exitCode=0、signal/error=null，同398身份；[原输出](../.cache/a46/review-final-frontend.log)为23文件/395通过。这里完整读取9份相关前端测试，不从aggregate日志捏造每文件独立成绩，也不把映射数加到3515离线总数。
- [当前owned Edge XML](../.cache/ui-runs/3f5e7a43-cf84-4641-834d-ada2839b2071/junit.xml)实际35通过/0skip，SHA256=4f8c29dc93a449d783dc230c48d03ba4095cbb2280922c2116688c9815888dbc。本次逐条核其game-initialization 6、game-recovery 9、site-gate-and-privacy 10，合计25项已经在35内，不是新运行的25项。
- [harness退出回执](../.cache/a46/review-final-harness-exit.json)与[实际输出](../.cache/a46/review-final-harness.log)为103通过，其中末尾7项明确测试固定origin、nonce/Fake身份、占用端口、覆盖参数拒绝、不下载浏览器、双子进程正常关闭。
- [类型回执](../.cache/a46/review-final-typecheck-exit.json)、[lint回执](../.cache/a46/review-final-lint-exit.json)均实际0。[交付回执](../.cache/a46/review-final-delivery-artifacts.json)明确reusedArtifacts=true/rebuilt=false：前端24源/86关联输入匹配、2045产物/2046上下文，并有新4路由/13静态/1公开资源隔离smoke及正常关闭。构建入口的既有成功证据见[当前验证](a46-local-verification.md)；此轮没有再构建，不声称验证Docker/Linux/生产。

## A30：先存身份，后发送；迟到结果不接管新局

实现：[controller](../src/lib/game-controller.ts)、[journal](../src/lib/game-journal.ts)、[route hook](../src/lib/use-game-controller.ts)、[游戏页](../src/app/game/[id]/page.tsx)。journal按JSON序列化的[soupId,level]分开，保留原question和UUID；未知版本/损坏/存储失败不当作空记录。create/ask都先writePending后POST，存储失败零发送；创建成功还要校验返回requestId、原pointer与journal仍属本操作，然后存session指针再清journal。

[controller测试](../src/lib/game-controller.test.ts)完整覆盖未初始化零ask、create/ask发送前durable identity、丢create后503重用ID、StrictMode同ID、旧create/ask/reveal/restore迟到和dispose防写、另一tab改pointer拒绝覆盖；[journal测试](../src/lib/game-journal.test.ts)含同ID换问题拒绝、旧完成不能清新操作、损坏原样保留、安全UUID无不安全回退。[DTO测试](../src/lib/game-contract.test.ts)拒绝错request/session/soup、缺count和非法状态，不把缺值当unlimited。

[页面组件测试](../src/app/game/[id]/game-recovery.test.tsx)实际断言初始化双控disabled、StrictMode同ID、切汤旧标题不出现、新session不被覆盖、丢响应刷新后仅原POST一次。owned浏览器的初始化6项和恢复9项另证明真实本地HTTP：pending UUID先于被延迟POST可见，刷新不新开；快速换难度旧响应不能覆盖新pointer；A→B→A按原UUID找回已提交结果。故障后仍使用原业务身份，不以网络重试编号当新业务编号。

默认测试隔离：[Vitest配置](../vitest.config.mts)envDir=false，只收src测试；[setup](../tests/frontend/setup.ts)每例独立清理合成localStorage、固定18080，未stub fetch直接抛错。Vitest单元替换fetch，不要求真模型或生产服务。[UI配置](../playwright.ui.config.ts)、[fixture](../tests/ui/fixtures.ts)、[启动器](../scripts/ui-e2e-server.mjs)、[固定策略](../scripts/ui-server-policy.mjs)要求随机nonce/testing=true/provider=fake，自建临时data与无真实env前端；固定127.0.0.1:18080/18081、禁止外部网络/参数覆写/复用现有端口。对应[策略测试](../scripts/tests/ui-server-policy.test.mjs)有真实占端口且connections=0；默认入口不是“先试连已有服务器”。

## A31：临时故障保留原局；永久/鉴权/终态分开

[API测试](../src/lib/api.test.ts)与controller完整测试覆盖404/410/409/429/503、401类型、断网和坏JSON：原session指针保留，没有自动POST开新局；429保留Retry-After，包括HTTP日期与非JSON代理错误，原turn恢复最多3次GET、间隔1秒，429立即停且截止前手动sync也不再请求。

API分别提供401“需要访问口令”、404“保存的对局或请求不存在”、410“这局旧游戏暂时无法恢复，历史仍保留”、409状态冲突、429等待、503暂不可用；controller分类auth/missing/incompatible/conflict/rate/service/network，页内401另有重新验证入口。用户显式另开不等于临时故障自动覆盖；未知pending只有显式放弃才另开，原服务端历史不删除。

solved/given_up恢复其冻结评估、保持原pointer；solved尚无评估或真实次数耗尽才走同一互斥揭晓路径。owned恢复用例实际确认restore503零新create、丢响应GET找回、旧终态fixture保持历史分数、不反转playing。API晚401仅清发送时旧token，不能误清新验证token。

## A32：互斥与扣次话术

同一controller同步设置inFlight，ask/reveal/双击不能并行发第二次业务POST；未验证session、pending或停版都阻断。丢ask响应先GET原session/turn/requestId：有完成记录只取真实session历史；404还须核原session，只有仍playing才可重POST完全相同payload/UUID，已结束不补提问。[暂停测试](../src/lib/game-suspension.test.ts)另覆盖pending UUID保留、停版不自动ask/reveal、解除后原意图同步。

失败/expired的严格DTO和真实session核验才允许显示“没有扣次数”；未知网络失败、reserved、未知turn但已结束均不作此承诺。揭晓不另造requestId，以同session幂等；丢响应先GET持久结果，只有确实尚未完整保存时才重试同session。owned浏览器直接断开已提交响应、刷新、检查questionsAsked和POST次数；不是靠固定前端文案推测后端未扣次。

这里“手动同步/确认放弃”是游戏玩家保护入口，不是让本项目用户逐阶段批准Codex续跑；自动任务仍无需阶段确认，不移除玩家的数据保护确认框。

## A33：服务错误不是成功/空列表

[SiteGate测试](../src/components/SiteGate.test.tsx)涵盖503、坏JSON、非布尔siteLocked、待验证口令错误响应和卸载后迟到，均不打开children、不保存未核验token；正常严格目录验证才解锁。503保留尚未验证失效的旧token，而不是清除后假解锁。

[catalog测试](../src/lib/catalog.test.ts)只把成功的合法空数组当“没汤”，401/404/410/409/429/503、坏结构、断网、坏JSON都抛错；公开目录解码去掉bottom。[列表/反馈组件测试](../src/app/catalog-errors.test.tsx)覆盖Home和难度页错误重试、旧搜索/旧汤迟到、反馈加载失败不能提交，以及带已解锁ID查询后可选隐藏汤。

owned页面10项另实测config四种失败闭锁、unlock三种拒绝不存token、目录503不是空/缺汤、真实合成隐藏汤公开选项可反馈且不含私有truth、CORS仅owned前端。lint使用[忽略配置](../eslint.config.mjs)排除backend/**、.cache/**、.pytest_cache/**等；当前实际lint/type和已有干净构建证据如上，不把文件存在当入口已成功。

结论：A30–A33本地实现/默认隔离及具体行为已有当前同源证据映射。本次不修改应用/永久测试，不新派审查、不重复全门禁；不把合成故障注入或本地Edge提升为真实模型质量/生产运行保证。后续[A34–A35](acceptance-a34-a35.md)及[A29剧情评分/完整分母交叉核对](acceptance-a22-a29.md)也已保存，下一步A36–A40。
