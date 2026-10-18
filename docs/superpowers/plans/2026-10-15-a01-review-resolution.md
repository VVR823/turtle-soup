# A01 本地验证单元：独立审查处置

审查者Kuhn：01a13ff3-bd08-7b90-832f-d928d2a2b4d9。实际终态报告经wait_agent读回：Critical 0 / Important 0 / Minor 1。本席只读，未修改文件/Git/权限，未下载、重跑套件或再派审查者；不是此前A46审查。

## 证据与结论

审查完整读取本阶段9个缓存验证脚本、原A01及计划/Rulings，复算主目录、seed、checkout共421项输入SHA及摘要；核54个Python分发、446个Node实际包及原锁。日志/XML支持前端399、harness103、合成API3和Python设置50通过/2跳过；类型退出0依据进程回执而非空日志，3040明确仅收集。未见主依赖/真实配置逃逸证据。该结论支持本地验证快照经真实Git检出后的锁定安装和所列运行，不是完整目标签收。

## Minor 1：保留原始记录，限定解释

Python安装收据的installScriptsAllowed=false范围过宽。主执行者已核uv日志确实Building/Built本地turtle-soup-backend，uv参数没有禁止Python构建；npm实际使用--ignore-scripts。

Final: minor (deferred): 缓存安装工具的字段将来可拆为npmLifecycleScriptsDisabled/pythonBuildBackendsDisabled；本次不改写已发生的回执，不修改工具或重装环境。代价是旧字段必须连同[澄清证据](../../../.cache/a01/v2-install-script-scope-clarification.json)阅读。澄清记录绑定原Python收据SHA237ea33b…和日志SHA931b2d4b…，明确Python本地构建实际执行、仅npm lifecycle脚本禁用。主证据页同步准确说明，不将此项称为产品缺陷或虚构RED→GREEN。

## 对审查未裁定部分的逐项裁决

- Final: Ruling: 全后端、新环境生产构建、浏览器UI、远程/公开检出、跨OS、生产及模型质量不由本单元证明；保留相应全范围门禁。理由是本次仅执行具名安装/运行；若误外推会把未执行环境或真实证据冒充已通过。
- Final: Ruling: 不声称空缓存下全程离线安装；已有公共缓存加两次官方原锁tarball下载后才成功npm ci --offline。若漏写此限制，离线新机可能无法安装。
- Final: Ruling: 不为历史起始状态重复制造一次检出；保留生成脚本和当时断言/回执，审查独立复算当前三处源字节。审查者未重跑Git status/fsck，不替其补造。若原回执有误，当前独立核对不能单独证明当时目录为空。
- Final: Ruling: 原239文件及主index保护由主执行者实际核验，不转述为审查者背书。[安装后保护](../../../.cache/d18/a01-post-verification-protection.json)记录原239摘要、HEAD/index均未变；审查者未扫描真实数据。若误合并两席证据，会夸大独立验证范围。

## 本单元验收边界

计划任务1所列本机快照/安装/适量运行/审查和保护检查完成，无Critical/Important待修，不再派复审。保留缓存工具/回执以便恢复；不按通用收尾流程删除证据、不写主Git/公开PR。新环境完整后端/统一入口及其它OS/Python矩阵未重跑，原完整升级目标继续。
