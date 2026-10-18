# 口令读取失败：本地修复与验证

2026-10-15。本次修复的是：页面已显示口令框，浏览器随后拒绝读取存储时，点击进入会抛未处理异常、没有可见错误。不是后端鉴权失效或模型问题。

DEBUG REPORT：DONE_WITH_CONCERNS（本地最小修复、回归和新产物已完成；原生浏览器整套、C26额外反例及原完整目标签收仍有明确边界）。

## 根因与最小修复

SiteGate的unlock先在try外读取previousToken；该读取抛SecurityError时绕过现有catch/finally。只把这次读取移入已有try首行，复用原错误提示和复位逻辑。正常catalog验证、当前控制器与token比较、成功后才写token/解锁的条件均未放宽。生产只有[SiteGate](../src/components/SiteGate.tsx)一处改动，其余用户修改保留。

原组件SHA1b3f5c6f…，修复后8106f073…；[新回归](../src/components/SiteGate.storage.test.tsx)SHAfdd454a5…。初始口令检查正常后才注入真实getItem错误；断言仍锁定、有错误、按钮可重试、仅config请求、无已保存token，随后恢复存储，同输入成功验证。

## 真实RED/GREEN与完整回归

- 原生RED实际1 FAIL加1未处理SecurityError，堆栈api14→unlock54；[完整原日志](../.cache/c27/storage-red.log)和[XML](../.cache/c27/storage-red-captured.xml)保留。原捕获收据的expected=false是ANSI分隔行号造成的检测问题，[独立澄清](../.cache/c27/storage-red-validated.json)绑定日志/XML SHA，不改原记录。
- 首次名为green的运行因新测试误用未安装的jest-dom matcher失败，未计GREEN。改用原生DOM断言后，同一测试在原组件副本[baseline-red](../.cache/c27/storage-baseline-red-receipt.json)实际exit1；在当前组件[fixed-green](../.cache/c27/storage-fixed-green-receipt.json)实际exit0，无未处理异常。没有回退主文件或更改依赖。
- [完整运行](../.cache/c27/storage-verification.json)实际27文件/417前端通过，XML独立解析0failure/0error/0skip；类型与生产文件+新测试lint均exit0、空日志。[417 XML](../.cache/c27/storage-full-frontend.xml) SHA47a072a4…。只称此范围，不重算后端或伪造新统一入口全套结果。
- [403显式身份](../.cache/c27/storage-identity.json)52d0d3559ee499df8cfceb4c3f1eb5944d0d4c867f955cca88b7a3313ad67545，原402仅SiteGate变更，另加新测试。不是仓库全部支撑输入清单。
- 当前覆盖分支1726/2032=84.94%、语句1738/1964=88.49%、函数402/465=86.45%、行1296/1409=91.98%。拆const新增一行，不能声称全部分母/branch map不变；这次修复价值由真实错误回归证明，不冒称提升模型质量或达到100%。

## 独立审查

唯一Confucius席位01a14039-6da1-7a81-9c42-3d10ca475c39实际C0/I0/M0，逐项复算403和同测试RED/GREEN；[完整原报告](../.cache/c27/independent-review-report.json)、[范围裁决](superpowers/plans/2026-10-15-sitegate-storage-review-resolution.md)保留。没有二次审查、额外模型或真人标签。其结论不含主执行者后续新构建。

## 新前端产物，不复用旧包

[新构建回执](../.cache/c27/artifact-refresh.json)实际04ca57原会话91945退出0：物理输入.cache/ts07-frontend-T8o9xK，复制现有24124依赖文件/517179618字节，无安装/下载；35构建输入含24源文件，输入摘要34b8c963…，与当前403绑定。配置按已有审查策略转换，原字节保存在next.config.source.ts并有[独立来源核验](../.cache/c27/config-origin-verification.json)。

Next16.2.12实际新standalone构建成功，16个trace manifest/3493路径边界已核。新包.cache/c27-frontend-artifact-dc77cfb8-0132-469d-a8e0-72a83dee66b7共2045文件，manifest SHA47e6363662c84e335e2dc1807ce92ebcda0099aa8860e72f686a378984e25402；rebuilt=true/reused=false，不用旧包同数量冒充新构建。

实际自有HTTP冒烟检查4网页、13个JS/CSS资源和1个public资源的签名/字节，产物模块来源与外联边界检查通过，进程正常EOF收尾并释放端口。它证明网页和资源可取，不等于浏览器点击/后端游戏整链已重跑。[最终来源/产物回执](../.cache/c27/final-source-artifact-verification.json)核403零漂移，旧前端产物只保留为历史。

## 保护与剩余范围

[原239/HEAD/index保护](../.cache/d18/c27-storage-after-protection.json)仍相同，主执行者核验，不冒充审查者背书。没有生产、公开、真实模型或人工数据操作。最新403未重新执行owned Edge整套，旧35页面结果属于旧身份；需要后续完整交付门禁时再实际刷新，不沿用为本次新结果。

C26额外clearTimeout反例仍因两次正常审批超时未执行，独立绑定5个未改SUT模块与原快照，不因本UI修复失去来源，也不拿本正常回归代替或绕过其审批。[本阶段ledger](superpowers/plans/2026-10-15-sitegate-storage-recovery-progress.md)和[全范围审计](upgrade-completion-audit.md)继续保留这些待办；整体任务未完成。
