# How to 查询统计、检查004并复现合成测量

不需供应商密钥，不连生产、不升级真实玩家库。先按[离线安装指南](testing.md)准备锁定依赖；定义见[参考](metrics-reference.md)。

## 1. 查看与完整导出

在已经配置独立管理员口令、已显式004的**本地实例**打开 `/admin/feedback`，填写管理口令，点击内部统计的“查询统计”。不点击不会发统计请求。默认7天，日期明确按UTC，不是北京时间。

“下一页统计”保留窗口；换日期、来源或令牌会清空旧结果并取消正在进行的请求。“下载完整统计”另读一次新快照，不是当前50行。超过100组/512KiB拒绝，需缩时间或指定题目；文件核对complete=true、summary和组计数总和。

统计获取或解码超过10秒会提示超时并释放按钮，可重试；迟到响应不会恢复旧结果/触发下载。后端仍共用3秒读预算，玩家游戏请求没有增加这个计时器。

以下仅是HTTP格式模板，**不是访问真实线上实例的记录**。口令留本机，不放URL、截图或Git；只向已确认归自己所有的本地实例发送：

```http
GET /api/metrics/admin?start=0&end=86400&limit=50
X-Admin-Token: <独立管理员口令>

GET /api/metrics/admin/export?start=0&end=86400
X-Admin-Token: <独立管理员口令>
```

本地真实Edge用例实际验证50/50/5分页、105组拒绝、筛选后27组完整文件和375像素页面；这些是合成数据，不是105用户。005新观测展示的observed/partial浏览器例是响应夹具，真实发布出生链另由后台合成业务验证，不能合并成真人效果。最新协议3及13项完整分母见[参考](metrics-reference.md)，0次real不是0错误。原004正常查询时新观测unknown/schema_5_required；需观察功能时另行显式演练005，不自动迁移真实库。

## 2. 检查显式004

应用空库启动仍只要求002，CLI默认001，Agent默认关闭。003增加Agent结构，004仅五个统计时间索引、不回填旧审计。旧库503先按[隔离迁移指南](migrations.md)取得完整停止写入的独立副本，不直接使用生产路径。

以下是须替换明确隔离路径的**操作模板，不是生产执行记录**。在backend的已安装环境运行；target/report尚不存在且互不重叠：

```powershell
python -m app.scripts.migrate_data --dry-run --target-version 4 `
  --source 'D:\isolated\old-copy' `
  --target 'D:\isolated\new-output' `
  --report 'D:\isolated\metrics004-report.json'
```

dry-run真的在内存迁移、写新报告、不创建target。检查版本4、phase004.noHistoricalBackfill=true、源摘要未变、完整性/旧行保留；productionReady仍false。正式隔离演练须另一个新target/report，不覆盖旧输出，不提供安装到生产的步骤。

本轮原生测试已执行显式4/默认1、旧001/002/003兼容和004失败回滚。复验从根目录：

```powershell
node scripts/test-backend.mjs backend/tests/test_metrics_migrations.py backend/tests/test_migration_cli.py -q
```

## 3. 复现200/1000/5000测量

依赖已安装后，在backend运行本轮实际执行过的命令：

```powershell
uv run --project . --offline --no-sync python -m app.scripts.benchmark_metrics
```

仅输出JSON，只用自己新建临时目录。没有用户路径/模型参数，不安装、不读真实dotenv/私人题库、不调用供应商。核对status=complete、evidenceKind=declared_synthetic_benchmark、三种profile各20个samplesMs、cleanupConfirmed=true；当前real统计50新建/150成功计次/1000HTTP，test/synthetic/legacy同规模排除，unknown另有1000HTTP但没有业务会话/轮次。窗口从实际迁移覆盖后开始，进程覆盖未知仍显示unknown。

P50/P95是排序后向上取位：20条样本的95%取第19条。当前reader包括快照/catalog校验、聚合、完整JSON序列化及闭合回读，并保留20个serializedBytes；sqlBatchBeforeIndexes/AfterIndexes仅实际同一SQL批次，不是旧reader。原较窄测量另行保留，不能用旧数字替代当前范围。所有样本保留，没测并发吞吐，不能推出真实质量。

## 4. 本地发布后固定复查（不是生产或真实模型质量评测）

只在独占合成本地实例练习：先显式演练005，按[候选操作](candidate-review-reference.md)完成真正的批准和单独发布，再取得该实例实际candidateId及publishedRuleVersion；不能用pending候选或预览报告代替。Runtime必须已加载来源/题目身份可核验的冻结dev/regression语料（最多100例），不接受客户端传题集、结果或模型参数；缺语料时拒绝而不是算0错误。正文格式仅 `{"operationKey":"<本次UUID>","candidateId":"<本地已发布候选UUID>","publishedRuleVersion":"r1:<实际64位摘要>"}`，向本地 `POST /api/feedback/admin/post-publication-regressions` 发送，带独立X-Admin-Token及Content-Type: application/json。尖括号是模板，不能原样发送，不把口令放URL/截图/日志。

查看回执plan/result/state，核对实际发布版本、startedAt/deadlineAt和完整计划分母；passed/failed/incomplete/running分别是全部通过、发现反例、检查不完整、尚无终态，不等于玩家胜率。固定复查不调用模型，需要模型的例记unsupported，不会拿标准答案假装模型答对。同operationKey与原内容只取原回执，不重跑；冲突409。running超过期限也不自动补测或改成通过，显式新key才是新尝试。

随后手动查询协议3统计，用startedAt落入的UTC窗口和实际发布ruleVersion筛选；real主数与test/synthetic/unknown排除计数分开，早于coverage的窗口partial。测试实例不能变出真人，缺005或坏出生来源显示unknown，不能写成0失败。可在根目录单跑已有 `node scripts/test-backend.mjs backend/tests/test_post_publication_http.py backend/tests/test_post_publication_metrics.py -q` 复现程序边界；这个学习入口不是本次另一次执行记录。当前实际证据/最终欠项见[D18 ledger](superpowers/plans/2026-10-13-d18-progress.md)。

## 排错与停止条件

- 401：核对独立管理口令，站点口令不够。
- 422：核对UTC秒/31天/来源/重复参数；导出不可带limit/cursor。
- 429：等Retry-After，不加频率或绕过身份。
- 409：缩范围，不拼多页伪称完整。
- 503：区分锁/预算与结构问题；核验隔离副本，不自动升库或重建为空库。
- 测量failed：没有成功分位数，保留输出；cleanupConfirmed=false不能宣称清理完成或宽泛删除目录。
- 迁移needs_review、源变化、未知结构/漂移：保留源与报告，拒绝上线。生产、人审、免费资格待定项单独搁置，不用合成证据替代。

[实测状态](ts16-status.md) · [大白话](metrics-explanation.md)
