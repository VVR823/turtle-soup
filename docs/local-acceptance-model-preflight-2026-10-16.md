# 2026-10-16 模型网关离线边界补验

用户明确授权继续本地验收。本轮执行结束；自动续跑永久禁止，未启动 Loop、heartbeat、调度或跨任务接续。记录按 context-save 的状态、决策、剩余任务结构保存于项目内，不执行全局同步、遥测或自动提交。

## 已完成与证据

新增 [test_model_gateway_preflight.py](../backend/tests/test_model_gateway_preflight.py)，33 项测试覆盖：容量/重试次数参数拒绝、调用前超时与取消、持久化尝试门限拒绝、工厂失败后的容量释放与错误脱敏、两种取消来源、负关闭等待值，以及真实模型关闭/缺少模型或密钥/远程非 HTTPS 时的提前拒绝。

只调用公开接口，使用脚本传输和合成配置。凭据/策略拒绝测试禁止创建 HTTP 客户端，没有真实模型请求；合成免费资格字段不代表任何服务已获免费资格。

首次新增33项通过，有一条 pytest 缓存目录权限警告，原始[日志](../.cache/manual7-acceptance-20261016/preflight.log)和[XML](../.cache/manual7-acceptance-20261016/preflight.xml)保留。随后关闭缓存插件，对新增文件及既有网关、准入、适配器、适配器边界共5文件执行关联复验，ResourceWarning/PytestUnraisableExceptionWarning 均作为错误：**95 PASS、0 FAIL、0 ERROR，无告警**，北京时间12:27:03–12:27:19，退出0。[日志](../.cache/manual7-acceptance-20261016/backend-affected.log)、[XML](../.cache/manual7-acceptance-20261016/backend-affected.xml)、[退出回执](../.cache/manual7-acceptance-20261016/backend-exit.json)。

与上轮完整后端XML逐个 classname/name 匹配：95项中62项重复复验、33项为新增；当前证据集合 **3063 PASS/14 SKIP**，共3077项。它是历史完整3044项加本次33项、重复项使用最新结果的集合，**不是本轮单次完整后端运行**。14项仍为7真实模型、6 symlink、1 Unix socket 跳过，未转为通过。[逐键校验及汇总](../.cache/manual7-acceptance-20261016/accepted-results.json)。

## 覆盖测量与输入保护

用 coverage.py 合并上轮完整运行的原始数据与本次关联测试原始数据；输入文件哈希前后不变。严格投影至原110个生产文件，不排除未测代码：

| 指标 | 历史完整基线 | 历史完整＋本次补验并集 |
| --- | ---: | ---: |
| 分支 | 3118/4032 = 77.33% | **3129/4032 = 77.60%** |
| 语句 | 11316/12672 = 89.30% | **11325/12672 = 89.37%** |
| 未命中分支结果 | 914 | **903** |

新增11个分支均在 model_gateway.py，准确起止行为44→45、114→115、122→123、124→125、158→159、246→252、264→265、289→290、310→311、330→334、334→335；无旧命中丢失。[110文件原始条目与准确未命中](../.cache/manual7-acceptance-20261016/backend-production-coverage.json)、[完整并集报告](../.cache/manual7-acceptance-20261016/backend-union-coverage.json)、[可复核汇总脚本](../.cache/manual7-acceptance-20261016/summarize.py)。不能把903个未命中称为903个缺陷，或等同原“新关键路径”的分母。

前端未改、未重跑；沿用上轮43文件717 PASS、类型/lint通过、分支2005/2032=98.67%、剩27的历史结果。[上轮前端报告](local-acceptance-game-boundaries-2026-10-16.md)。本轮未重跑完整后端、构建、浏览器、框架或API冒烟。

既有421项源码/测试输入逐文件哈希零漂移，仅新增一个测试文件形成[422项输入身份](../.cache/manual7-acceptance-20261016/final-source-identity.json)。业务代码未变。分支仍为 `codex/ts02-storage-foundation`，HEAD仍为 `c5765b68cb251a7c566e76e2887d335d6ed6b285`；原239运行文件、HEAD、Git索引由[开始保护](../.cache/d18/manual7-before.json)和[结束保护](../.cache/d18/manual7-after.json)核对。没有提交、切分支、覆盖旧修改或生产操作。

## 尚未完成与建议顺序

1. **本地覆盖**：后端原110文件尚有903个未命中分支结果；先按关键业务路径选择有效场景。前端27项保留，未豁免。静态核对发现多项为按钮禁用后的重复守卫、严格数据契约下的回退，不能通过注入私有状态凑命中；仍需逐项可达性证据与原验收目标映射。
2. **可复现版本与平台**：仓库仍只有原始提交，没有可克隆的完整升级提交；A01/A03等不能仅据本地测试签收。CI和其他平台的运行证据仍缺。
3. **真实模型与人审**：已确认免费的 provider/model/endpoint、正式语料、人工参考答案或审核记录尚未提供；真实三系统/Agent轨迹/8参考任务等仍待验，不以离线假模型代替。
4. **生产与公开**：生产停写恢复、上线及公开发布属于独立边界，未执行、未签收。

正式60项状态不变：限定本地工程通过47，未通过1（A42），进行中但停止2（A46/A60），未开始3（A50/A53/A59），待核实7（A01/A03/A04/A10/A54/A56/A58）。原100%新关键路径及整体最终验收尚未完成。

本轮保存后停止，等待新的明确指令。后续读取本报告、旧计划或额度恢复均不构成续跑授权。[收尾状态](../.cache/manual7-acceptance-20261016/final-verification.json)。
