# TS16 独立审查：逐项裁定与一次修复恢复点

原报告：[完整原文](ts16-review-report.md)，从原审查者权威completed文本逐字保存。
唯一Chandrasekhar01a12c0f-c7bb-7ca3-801d-4ab9cbf3d0da完成后实际close返回
previous_status=completed；没有重审/另派/跨模型审查。冻结350source/189evidence
及原报告均为修复前历史，不能冒称审查者检查过修复后的代码。

## 分级与根因核对

- I1保持Important：实际SQL min/max忽略NULL，且提交审计turn_id没有与反馈权威关联核对。
  单条有效来源不能掩盖另一条缺字段/冲突来源。原生缺省/null/关联冲突反例先RED，
  同SQL批量收敛完整必要来源，再计唯一反馈；有效重复、未关联反馈不得误伤。
- I2保持Important：实际只用table存在作为公开名单；active基线验证不覆盖unused坏快照。
  要验证真实历史快照/内容摘要/身份关系，过滤和投影同一名单；不可只改filter或抹掉
  合法历史。成本：有界验证必须含在3秒预算，不把私密原文传Python逐行统计。
  Ruling: 选择同快照全catalog验证后才把注册表当公开名单；任何损坏catalog固定503不可用，
  不返回私人canary也不默默丢合法历史。沿用baselines的摘要/严格JSON/身份/规则绑定校验，
  Python只在必要catalog完整性验证中处理已有快照，不读取玩家/反馈/run/candidate全文或
  逐行统计；这与已有active验证同类，不新增统计服务/缓存/写入。成本：历史catalog越大
  验证工作越多，全部SQL和后续aggregate仍共用3秒预算；无规模/SLA承诺，必须新测量。
- I3保持Important：actualfetch/json无计时器；abort后current=false会跳过busy释放。
  拥有者计时器覆盖获取+解码，显式释放并递增epoch拒绝迟到结果；先用fake timers
  复现honor/ignore abort与迟到下载，不影响玩家路径/正常3秒SQL请求。
- I4保持Important：String(array)枚举校验、cast保留数组，页面兜底会显示完整覆盖。
  实际contract3数组反例RED：3FAIL28controlsPASS1.33s，review-i4-red.log。
  最小强制string验证，组件也要拒绝而非肯定覆盖。
- I5保持Important：json_valid不拒绝duplicate object keys，真实SQLite提取可能把
  real/test歧义选成real。原生rawJSON两顺序/审计+run反例，SQL结构检查每个对象，
  保持aggregate-only Python、当前deadline和有效metadata控制。
- M1保持Minor/deferred至TS17：baseline包装SQLITE_INTERRUPT/BUSY改变固定503代码，
  仍安全拒绝/清理，不导致账错或泄漏。不能称已修；nativebaselineSELECT中断测试
  与窄异常链映射另行收尾，避免本次顺手修改旧baselines公共行为。
- M2重新分级Important：书面spec明确五分类和固定/覆盖后时钟，测量夹具缺unknown
  且窗口早于覆盖；这是明确验收缺项，不仅文案优化。纳入同一C-I修复，原测量保留，
  新测量独立命名；200/1000/5000不改变，预期分母从实际独立SQL计算。
- M3重新分级Important：书面spec要求完整reader含序列化，原profile仅dump summary。
  纳入同一C-I修复，原数字不称伪造但明确范围较窄；新profile计完整JSON序列化与
  闭合回读核对，不把未来数字预填成提升。

以上是裁定/待实施，不是已修证明。单次修复通道按项native RED→GREEN，全部项后
才运行当前完整/页面/测量/文档与最终新snapshot，不重复派审查者。

## 每项Declined裁定

| 项 | 主任务裁定、成本与依赖 |
| --- | --- |
| D1 | 真实语义质量HOLD；独立人审题集/provider未验收，工程计数不能代替 |
| D2 | 真人人审质量HOLD；synthetic确认字段只是契约夹具 |
| D3 | 当前免费资格/供应商额度HOLD；不付费、不以源码注释确认永久免费 |
| D4 | 真实运营数据HOLD；不访问真实玩家库或把合成行当用户 |
| D5 | 无身份基础，明确不宣称去重人数；会话数保留本义 |
| D6 | 生产004/真实完整性需单独授权；本地迁移通过不增加生产权限 |
| D7 | TS17本地最新库恢复/全写入者演练必须继续；真实cron/备份仍外部HOLD |
| D8 | TS17本地release/TLS代理模板继续；实际TLS/SSH/远程CI部署HOLD |
| D9 | TS17剩余D25合成资源/100入场继续；RSS/生产QPS/SLA/provider延迟未知 |
| D10 | 10既有skip保留，不算通过，不改ACL或伪称跨平台验证 |
| D11 | TS17/18范围/密钥安全核查继续；66链接/有限pattern不是全面安全证明 |
| D12 | 375页面证据有限；TS17真实页面QA继续，不宣称真人/全面无障碍结论 |
| D13 | TS15 M1保留TS17实际畸形组合测试，不能被本次统计解码修复冒充解决 |
| D14 | TS15 M2保留TS17前后台观察恢复，人工刷新不代替 |
| D15 | 缺corpus真实浏览器分支仍欠TS17，native不能顶替 |
| D16 | 不扩展跨HTTP长快照/无限导出；保留完整拒绝与新快照语义，成本是实时页可能变化 |
| D17 | 不公开/上传统计或凭据；本地管理员导出不授予公开许可 |
| D18 | 原计划确实要求后续回归失败统计，不删除、不拿候选预发布失败偷换。现没有权威post-publication失败流；先单独登记为未实现统计项，TS17/18继续确认来源与可零成本实现路径，不能宣布原完整A57/所有统计交付均通过。无来源时明确unknown/HOLD，不造0或增加越权评测 |
| D19 | 统计读不授予历史任务新权限，不重放模型/实时corpus授权来统计；保留历史来源核对 |
| D20 | 原239字节由主任务实际哈希门禁证明，peer只查证据；不混淆独立重哈希 |
| D21 | 仅TS16评审，TS17–18与18阶段目标/hourly保持ACTIVE，不縮为局部完成 |

## 当前修复证据

- I4：合同3数组 + 实际页面1反例 genuine4FAIL/45PASS RED，最小 typeof string 检查后49PASS/1.85s GREEN；证据 review-i4-component-red.log / review-i4-green.log。不是只测类型声明。
- I1：完整必要字段缺省/null与实际关联turn冲突 genuine6FAIL/2controlsPASS RED（review-i1-complete-red.log/xml，1.46s）；SQL count(*)要求每条字段完整，turn一致性区分全NULL与混合/异值，并与feedback_items.turn_id权威FK匹配。当前 selected query/HTTP/query-plan/feedback storage 109PASS/13.83s GREEN（review-i1-green.log/xml，EXIT0）；有效重复、未关联和既有来源控制保留。
- I5：raw JSON审计两种键顺序、run根/嵌套对象四反例 genuine6FAIL/1.40s RED（review-i5-red）。SQLite json_tree按parent/key只核对对象键，数组索引不作重复对象键；歧义映射为未知而不漏掉源计数。第一次实现 selected136PASS/1FAIL，真实5000审计索引测试触发3秒拒绝；保留失败。systematic-debugging原生诊断1FAIL/4.02s：两个aggregate共548个json_tree计划节点、audit_window未materialize。根因为CTE内联反复展开校验，不是3秒预算太短。窗口边界AS MATERIALIZED只解析一次，预算未放宽；当前137PASS/13.20s GREEN（review-i5-materialized-green.log/xml，EXIT0），含原时间索引、分页和来源控制。完整仪器化性能仍待新测量，不能以selected绿冒充全门禁。
- I2：第一夹具4失败/1通过为immutable baseline触发器拒绝UPDATE的测试错误，不作产品RED；保留触发器、仅在隔离库初次INSERT畸形未激活记录后，4 genuine DID NOT RAISE /1合法历史控制PASS，1.15s（review-i2-native-red）。必要catalog摘要/身份/规则绑定验证后当前195PASS/14.76s GREEN（review-i2-green.log/xml），含合法未激活历史筛选/完整导出与既有规则发布。无私人行级统计/新增缓存、默认迁移不改。
- I3：查询/分页/导出 × 获取/body × 遵守/忽略abort，共12 actual超时反例FAIL、18控制PASS（review-i3-complete-red，2.91s）；同拥有者10秒计时器覆盖获取和解码，超时显式释放busy并提升epoch拒绝迟到响应/下载；筛选/unmount/token清除计时器，不影响玩家路径。61 selectedPASS/2.31s（review-i3-green）；当前全前端350PASS/22文件、typecheck/lint EXIT0（review-front-current/typecheck/lint），不是全后端/真实浏览器最终门禁。
- M2/M3：unknown缺类和timed reader未序列化各 genuine FAIL（review-m2-m3-red，2FAIL/5.88s）；实际reader覆盖前窗口单独 genuine FAIL（review-m2-clock-red，1FAIL/3.35s）。保留200/1000/5000、审计五类各1000（unknown以typed null流量表达）；源独立SQL核对real50/150/1000与unknown0/0/1000，窗口从实际迁移覆盖后开始，不虚称进程覆盖complete。计时包括完整MetricsPage JSON及闭合roundtrip；当前6 benchmarkPASS/40.52s（review-m2-m3-green），不是预填性能数字。
- 新 standalone实际CLI EXIT0产物 benchmark-post-review-measured.json，SHA256 BF9E4F1E7F89D23B52B4B42CDF62AC6823CD0089839ED463F1E7CA6C98B48DA9。3预热/20样本：reader P50=478.65830012597144ms/P95=486.46740010008216ms，完整JSON每样本13602bytes；CPU30921.875ms/Python分配峰值10295788bytes/DB5320704bytes/WAL0/cleanupConfirmed=true。包括tracemalloc/catalog/歧义JSON守卫/序列化及回读，明显比旧窄范围90.63/92.49更慢；不同范围/五分类输入不能直接叫同比退化或优化提升，必须保留两个原始报告，不能宣传速度提升/生产SLA/RSS/模型质量。
- 当前整离线第一轮3178实际EXIT0/2981PASS10existingSKIP；但之后实际Edge96356 EXIT1/31PASS1FAIL，统计503/35秒test等待body，正常API88280/双关闭。原截图/trace/JUnit保存ui-post-review-first-artifacts，不冒称真实页面通过。
- 同一I2修复通道继续systematic-debugging：trace实际GET503/3004.395ms、截图已提示不可用并释放按钮，不是10秒页面timeout挡正常请求。真实ownedUI题库比四题测量大；每题调用session_baseline重复解析/摘要全release。原生SQLitetrace4题6次整release读 vs要求≤2，genuine1FAIL/0.87s（review-i2-catalog-cost-red），不是猜测放宽预算。改为每个puzzle验证一次、每个release验证一次，再复用本请求已验证catalog进行相同身份/规则字段绑定比较；无跨请求缓存、没有缩小合法历史集合或修改公共baselines/3秒限制。当前99PASS/15.61s GREEN（review-i2-catalog-cost-green），完整/实际Edge需对这次最终代码重新验收；旧2981门禁仅作此次优化前历史。
- 全部C-I仍在同一修复通道，最终真实Edge/当前全离线/测量/文档与新snapshot尚待验收；不另派审查者、不称TS16整体已完成。

最终代码当前真实Edge49414 EXIT0/32PASS（1.2m），统计全流程3.6s；build0/API119512正常双关闭。主任务实看375viewport，DOM375/375/outside[]；uncaught[]、console仅预期105组409。完整筛选导出27组/27session/13416bytes/coveragepartial，仍为declared synthetic而非用户。所有证据归档ui-post-review-final-artifacts，首轮失败没有覆盖。新最终CLI测量benchmark-final-measured.json实际EXIT0，SHA25682B7DFC9CF3F416EEC4719A38CE99050541D98454DB074C721E5642B3466EDC7，3预热20样本/full JSON；reader P50/P95473.27989991754293/490.58590014465153ms、CPU30703.125ms/Pythonpeak10294961bytes/DB5320704/WAL0/cleanuptrue。最终全离线与snapshot仍待执行，不以页面绿/原整套门禁代替。

最后实际96815完整门禁 EXIT0：2614 XMLcases、0failure/0error、2604PASS/10existingSKIP，含412Eval；另350frontend/25Node/3API，共2982离线PASS，XML567.758s。API102292正常关闭，原239运行文件canonicalSHA d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a未变，HEAD/index未动。至此当前工程C-I修复与全门禁闭合，不另派重审。D18原统计来源欠项并未由这些通过数解决，仍明确接续；M1 Minor/真实人审/provider/prod边界不变。进入不依赖D18的TS17本地工作，不向用户索要阶段继续指令，不结束整18目标或hourly。
原full2944PASS10skip为修复前，加入新失败测试后不声称当前全绿。
