# 私有统计：缺失发布后回归来源的本地验证

状态：DONE_WITH_CONCERNS（仅显式未知契约与实际页面/下载；原D18可信采集仍HOLD）。不是生产发布、完整TS17验收、真实模型质量或真实用户统计报告。

审查后接续：下文99060/57659及旧包为本单元历史 checkpoint，不能作为后续布局修改的全套证据。手机分组表已按真实375px反例修复，最终33项Edge通过，完整摘要可横向滚动；见[唯一审查及一次修复](ts17-review-resolution.md)。新全offline曾出现3项合成worker等待超时，原断言下定向15项通过、最终串行47548也实际3231离线通过/14跳过后，本地工程子集已验证。后端补默认unknown的Minor差异及全部未判断项同样保留，不声明所有缺字段都被后端拒绝，也不把此契约签为原D18完整采集。

## 结果

私有Page/Export的闭合响应升级为schemaVersion2，summary含严格固定对象：

```json
{"state":"unknown","failedRuns":null,"observedRuns":null,"reason":"source_not_integrated"}
```

网站后台明确显示“发布后回归失败：未知、可信来源未接入”。`complete:true`只保证导出分组完整，不表示所有质量指标已接入。审计覆盖说明只适用于已经接入的事件；不能用候选发布前测试/失败任务数替代发布后观测，更不能把缺证据写为0。游戏协议、cursor1和数据库001–004未改变。旧私有统计JS需与后端同步更新，不能混合上线；此处没有部署授权。

## 实际证据

- 原生初始RED3FAIL6PASS，前端初始RED3FAIL67PASS，保留在`.cache/ts17/metrics-source-red*`与`metrics-source-frontend-red.log`。
- 首次实现实际12FAIL142PASS：旧继承校验器仍只接受1，默认v2构造却在导出重校验时拒绝。补充真正JSON解码/导出重校验RED2FAIL12PASS后，将校验限定为模型声明的精确整数版本；不接受布尔、浮点、字符串或旧版本。另一次补充测试误用Python元组解码已如实纠正，失败记录保留。
- 首次组件尝试1FAIL69PASS来自未注册的DOM matcher；只改为实际textContent断言，不安装额外依赖。最终selected203后端PASS/0SKIP/57.76s、70前端PASS/2.38s。
- 当前全offline99060实际EXIT0：Python XML2774cases/0failure0error/14既有SKIP/619.676s，2760PASS（含Eval）+365前端+103Node+3API=3231PASS。API30112启动与关闭完成；typecheck/lint各EXIT0。
- 真Edge57659实际EXIT0：33PASS/0SKIP/88.514996s；新隔离Next编译8.7s，实例275b7ebb-25b5-4bc5-bb28-33ac0d57b1df，合成目录ts08-ui-vd1FXl。统计流程4.7s，实际页/两次分页/下载都是v2+同一unknown/null对象，27组完整导出；105组超限仍409拒绝。API9816、前端和双夹具正常关闭。
- D8新增wx观测文件在本轮实际存在：拒绝409/unavailable/pending/reviewVersion0、uncaught[]、outside[]、viewport375/width375，仅预期409控制台信息；不是旧33PASS替新代码背书。
- 统计实际观测：uncaught[]、仅预期105组409控制台信息；DOM viewport/document均375、已检查控件outside[]。主任务实看新desktop/fullmobile/mobileviewport和D8缺corpus mobile截图。统计fullmobile原图389×14712，缩略图不能用来证明所有文字可读；可见未知断言由真实浏览器执行，超长表格与截图宽度差异仍须谨慎评价，不凭DOM无溢出声明全面视觉完美。
- 指定WinPS5.1再次核对原239运行文件digest为d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a；HEAD/index仍原值。

证据独立封存于[本轮归档](../.cache/ts17/metrics-source-verified-20261012)，历史D8归档未覆盖：

- [UI XML](../.cache/ts17/metrics-source-verified-20261012/metrics-source-browser.xml)，SHA256 EA75C499A39309594B6A590193AAEA154A044E2E759F9FAF9BAC9640D6AEC9CA。
- [全offline XML](../.cache/ts17/metrics-source-verified-20261012/metrics-source-whole-offline.xml)，SHA256 74A0A3DA726BF1769A9C139D984937E0079CC0126FE22CD6FCF5824042CD475E。
- [真实下载](../.cache/ts17/metrics-source-verified-20261012/ui-results/admin-metrics-owned-real-b-29288-download-and-test-exclusion/metrics-complete.json)、[统计观测](../.cache/ts17/metrics-source-verified-20261012/ui-results/admin-metrics-owned-real-b-29288-download-and-test-exclusion/metrics-console.json)、[375布局](../.cache/ts17/metrics-source-verified-20261012/ui-results/admin-metrics-owned-real-b-29288-download-and-test-exclusion/metrics-mobile-layout.json)。
- [统计desktop](../.cache/ts17/metrics-source-verified-20261012/ui-results/admin-metrics-owned-real-b-29288-download-and-test-exclusion/metrics-complete-desktop.png)、[统计mobile](../.cache/ts17/metrics-source-verified-20261012/ui-results/admin-metrics-owned-real-b-29288-download-and-test-exclusion/metrics-complete-mobile.png)、[mobile viewport](../.cache/ts17/metrics-source-verified-20261012/ui-results/admin-metrics-owned-real-b-29288-download-and-test-exclusion/metrics-mobile-viewport.png)。
- [D8新wx观测](../.cache/ts17/metrics-source-verified-20261012/ui-results/admin-agent-review-missing-621cf-y-minimal-unavailable-state/missing-corpus-observation.json)、[D8新mobile](../.cache/ts17/metrics-source-verified-20261012/ui-results/admin-agent-review-missing-621cf-y-minimal-unavailable-state/missing-corpus-minimal-mobile.png)。

## 未完成与边界

可信发布后执行/报告/发布绑定、真实供应商与人审标签仍未接入，原A57/D18缺项保留。当前完整工程证据不能证明真实语义质量。既有14SKIP保留（Windows符号链接权限、真实QA来源、Unix socket等），pytest根缓存WinError5权限warning和Node颜色环境warning未隐藏、不改ACL。

下一项：当前源码的新独立backend/standalone包与真正HTTP冒烟，ONE整阶段审查及必要一次C/I修复，再TS18材料；Docker/Linux/生产迁移部署/公开仍HOLD。唯一小时续跑仍ACTIVE，不要求逐阶段继续，也不保证额度重置瞬间唤醒。
