# A21 本地调用所有权与等待上限：断言已映射

2026-10-15，当前398源身份55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32，应用与永久测试未改。以下现有测试均已从当前完整XML核对通过、与冻结源逐字节绑定；不是重跑或新增成绩。

| 现有模块 | 当前XML通过数 | 已读行为 |
| --- | ---: | --- |
| test_model_gateway | 14 | 两个超时仍运行owner占两槽，第三次busy不派发；迟到丢弃；两次各清理一次；失败清理保留槽 |
| test_model_admission | 26 | 两owner/32等待/第33拒绝；等待取10秒与原deadline最小；FIFO、取消、关闭；在线票据优先；Agent仅1且共享第2槽；待办10及并发50到达 |
| test_agent_admission | 3 | 在线抢先准入；清理未知不启动下一SQLite任务预算/截止；原截止过期不重启 |
| test_launch_policy | 8 | 非法worker配置拒绝，Agent要求声明1 worker；支持的启动器拒绝2且不信任代理头；check不启动服务器/泄密 |
| test_request_disconnect | 2 | 取消仍占槽；实际ASGI断开保存失败、玩家0扣数、迟到不改审计/重放 |
| test_agent_loop_races | 12 | 心跳/撤销/接管/取消/关闭期间真实迟到模型/工具结果不能越权提交，未知清理不能触发后续模型 |
| test_agent_heartbeat | 12 | 30/60秒封闭lease政策；续约不刷新180秒原截止；接管保留checkpoint并拒绝旧owner |
| test_agent_shutdown | 12 | 阻塞中关闭/接管/原截止/取消仍承认未清理；实际Runtime关闭和启动失败安全收尾 |

共89项已包含于当前3515离线回归，不相加。现有Agent HTTP39项还直接覆盖持久队列恰好10、11次429且无新增步骤/模型预留；不把本地PendingAgentQueue误称SQLite持久调度器。

## 补齐真实饱和到游戏HTTP的链路

仅凭gateway返回busy及通用system_error零扣数不足以冒充这一具体HTTP场景，因此新增了独立本地验收探针（不改永久测试或应用）：

1. 当前真实Runtime共享ModelGateway由两个明确持有的合成Fake transport占满。
2. 第三个普通游戏问题在真实ASGI路径等待约10.041秒，返回503/model_busy，未创建第三次模型派发；此前两槽仍active。
3. 游戏questionsAsked保持0，回合为failed，真实HTTP审计charged=false/modelCalls空。
4. 释放并关闭两owner后再次检查：玩家仍0扣数、失败回合不被迟到答案改写；owned资源正常关闭，合成目录正常清理，当前398源零漂移。

实际native65842 / 419913退出0。[回执](../.cache/a46/original-a21-busy-http.json) SHA256 ce0a3346b478839d11f205fa10fac003a44671cbf661f517df79657c9766d6e5；
[探针](../.cache/a46/original-a21-busy-http.py)使用固定现有venv-ts01解释器、-I -B、单条显式合成汤与两条自有测试线程。是额外验收场景，不添加进3515，也不是真实玩家、真实模型或吞吐数据。

## 关键区分与限制

玩家“问答次数”与Agent“任务预算预留”不是同一件事。在线与后台抢占发生竞争时，后台可能已经保留一次任务预算但实际provider未派发；既有agent_admission断言明确保留这次预留、不退款以免无限重试，不能把它当实际provider调用。上面的游戏HTTP场景直接验证玩家0扣数。

本地取消、lease过期与网页返回都不能证明transport已经退出。只有owner实际完成清理后释放槽；清理失败明确降级/保留占位，不虚称远端推理已停止。在线32是模型准入等待票据上限，不是整个Web服务器所有线程的上限。

只验证当前进程/支持启动配置；不证明跨进程、跨机器或远程模型服务的总并发上限。真实服务器多worker是否按支持配置运行仍属生产核验，不能拿本页认证生产部署。

[保护回执](../.cache/d18/a21-busy-http-after-protection.json)：原239文件/d9662e98…、HEAD/index与既有原值相同。未改生产数据、未调用付费/真实模型、未再次派审查者。
