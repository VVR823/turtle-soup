# TS17 本机资源测量参考

这些是2026-10-12本机合成测试，不是真实用户、模型准确率、公网耗时或生产容量。完整当前阶段门禁和唯一审查尚未完成；这里记录已实际执行的测量单元。

## 接口与复现

从仓库根目录，使用已安装的隔离解释器和依赖，不下载模型或依赖：

```powershell
$env:UV_PROJECT_ENVIRONMENT = 'D:\CODE\turtle-soup\backend\.venv-ts01'
$env:UV_CACHE_DIR = 'D:\CODE\turtle-soup\.cache\uv'
uv run --project backend --offline --no-sync python -m app.scripts.benchmark_admission
uv run --project backend --offline --no-sync python -m app.scripts.benchmark_game_paths
```

两个CLI不接受任何参数或外部数据库路径，输出一个JSON，只有完整测量且清理通过才退出0。导入不运行测量。`measure_admission()`固定100申请；`measure_game_paths(*,warmups=3,samples=20)`允许warmups整数0–10、samples整数1–100，拒绝bool。失败使用固定代码，保留已尝试原始记录，不输出成功分位数或原始异常文字。

P50/P95是完整原始样本排序后的nearest-rank位置；不挑最好一次、不忽略失败。缺少升级前同范围报告、真实provider延迟与RSS（整个进程驻留内存）时返回unknown/null，不填0。

## 实际100入场结果

当前独立报告：[admission-measured-current.json](../.cache/ts17/admission-measured-current.json)，SHA256 `D08D2C46BE48876CF6881FB074659BB78177F4372B938A743A60CF3D109A65D0`。

| 观察 | 实际值 |
| --- | --- |
| 同时申请模型名额 | 100个临时测试驱动线程 |
| 人工保持执行时的执行/排队/拒绝 | 2 / 32 / 66 |
| 释放后的完成/拒绝/异常 | 34 / 66 / 0 |
| 实际transport开始/关闭 | 34 / 34 |
| 完成请求P50/P95 | 14.2707 / 21.3701 ms |
| 被限流拒绝请求P50/P95 | 3.0776 / 3.4743 ms |
| CPU / Python分配峰值 | 46.875 ms / 773973 bytes |

100条原始终态记录全部保留，峰值执行2、排队32。实际join模型/测试驱动线程，gateway关闭且active/waiting为0。时间包含人为Event保持和tracemalloc开销；这里只证明当前名额策略的容量与回收，**不证明网站支持100人同时游戏，也不是CPU吞吐上限**。早期[报告](../.cache/ts17/admission-measured.json)保留为另一轮运行，不与当前样本拼接。

## 实际正常游戏路径结果

报告：[game-path-measured.json](../.cache/ts17/game-path-measured.json)，SHA256 `6B7AF4F38079AD9E506B0F3CEEB2A6D992FB8E407B1C4ECE4A2D4AE1591DC845`。

每条路径预热3次、测20次；每次新建一局。计时只包含进程内TestClient的POST提问及实际turn保存、审计和trace写入，不含创建会话或公网传输。规则命中使用预热后的当前缓存；模型兜底每次仍实际调用注入的FakeModel，绝不缓存模型答案。

| 路径 | 实际来源 / 每样本模型调用 | P50 / P95 |
| --- | --- | --- |
| 合成规则命中 | deterministic / 0 | 29.7799 / 32.3943 ms |
| 普通上下文问题兜底 | llm / 1（FakeModel） | 32.3877 / 37.0283 ms |

40个计时样本和6个预热样本均保存。真实业务方法产生46局/46turn/92消息/46次计数，独立SQL核对184审计（46创建、46turn提交、92HTTP尝试），46trace文件/46行、23次Fake调用。trace与typed audit的来源/答案类型/是否扣次/版本实际一致，未把提醒或异常当正常答案。

本轮DB增加389120 bytes、trace29348 bytes、审计JSON167977 bytes；审计JSON在DB内，不能再与DB增量相加当总磁盘。结束时DB512000 bytes/WAL0；CPU2171.875 ms/Python分配峰值4252127 bytes。Runtime实际关闭、model active0、audit残留/未保存0且无永久缺口，临时目录实际移除。Python分配峰值不是RSS，Fake延迟不是免费供应商延迟。

## 验证与边界

[selected native日志](../.cache/ts17/d25-selected-green.log)与[XML](../.cache/ts17/d25-selected-green.xml)实际80通过/11.52秒，覆盖两类测量、原gateway/admission、HTTPaudit和typedtrace。接口缺失4与12个真实RED，以及失败记录2个真实RED分别保留，不拿写完之后才加的控制伪称RED。

升级前后同机同范围比较仍未知，不宣称“提速多少”；真实provider/正式免费资格/真实用户/RSS/生产QPS与SLA尚未核验。TS16已有200会话/1000turn/5000审计规模测量是独立历史报告，不重做或重复计成这里的证据。

相关：[本地发布操作](howto-local-release.md)、[阶段权威记录](superpowers/plans/2026-10-12-ts17-progress.md)、[统计口径](metrics-explanation.md)。缓存证据未公开上传；清理或克隆仓库后需重新运行对应测量，不能把缺失文件当当前证明。
