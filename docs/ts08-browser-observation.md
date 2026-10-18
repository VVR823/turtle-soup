# TS08 浏览器观察与复现（本地、合成数据）

2026-10-08，主执行者进行了只观察、不改业务源码的 QA pass。使用已安装 Edge + Playwright 适配器；gstack browse 可执行程序缺失，未安装软件或启动其 daemon。全部网页/HTTP 请求只允许自有 127.0.0.1:18080/18081，禁止 service worker，测试后两个服务均正常退出。不是生产、Safari、真实用户或模型质量验收。

第一轮 18 项：7 通过、11 失败；其中 10 项是测试自身定位问题（Next 路由播报器也有 alert、目录是分页 link 而非 button），不是 10 个业务缺陷。修正测试定位但不改业务源码后，第二轮 17 通过、1 失败。原始 XML 分别保留 ui-first-observation.xml / ui-corrected-red.xml。

| 级别 | 已复现问题 | 复现步骤 / 证据 | 后续处理 |
| --- | --- | --- | --- |
| 中等 | 手机提问框被反馈按钮覆盖 | 390×844 打开 xin/xuermu，等待输入可用，失焦；反馈 opacity=1 时 bbox 相交，左侧 hit-test 失败。两轮独立 fresh build/context 均复现；主执行者查看了 mobile-before.png | 本观察 pass 已结束；转入独立的 TDD 实施，为移动底栏预留反馈位置及 safe-area，再复跑同一几何/真实点击门禁 |

第二轮构建 zY3mR1、后端 PID108432，nonce 791bdeac-1c95-41ce-b2df-fc0a7508d6c0；构建退出0、前端 EOF wrapper退出0、后端正常关闭、pair cleanup0。纯路由错误与上述业务缺陷分开计数。综合 QA 分数、Core Web Vitals、WCAG 对比度、Safari/iOS 真机、OS 矩阵未测，不赋予虚构分数。

剩余验证：零次数自动揭晓、真实确定性 win、429 恢复、最终移动截图与正式全套门禁、唯一独立代码审查。当前观察不是 TS08 最终签收。
