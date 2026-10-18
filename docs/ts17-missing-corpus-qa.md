# TS17 D8：缺可信评测集的真实浏览器验收

状态：**DONE_WITH_CONCERNS，仅本项本地观察**。不是TS17整阶段、镜像、生产部署、真实模型质量或真人标注验收。按QA-only观察；夹具开发另按inline TDD，未修改游戏或候选批准产品逻辑。

## 范围与环境

- 2026-10-12；Next.js/FastAPI；实际已安装Edge，固定自有127.0.0.1:18080/18081，无复用用户服务/浏览器下载/外连/供应商调用。
- 独立合成Runtime/schema4/corpus/Fake Agent，通过浏览器提交反馈、隐私许可、启动真实worker/tools，生成真实七case报告与pending候选。不是预置候选、预置成功报告或stub响应。
- 实际51836 EXIT0；当前完整UI33PASS/0FAIL/0ERROR/0SKIP，JUnit86.513314s；本用例14.945s。隔离构建实际EXIT0/编译9.4s；API5384真实startup→shutdown complete→finished，前端CLOSED0，both owned fixtures closed。
- 源nonce 4d130cb9-80f3-4f85-b083-2a7c1f9eeaae；输出不可变归档 `.cache/ts17/ui-corpus-verified-20261012`，首次运行前旧证据另复制到 `.cache/ts17/ui-corpus-before-06496ae5-3d92-4f6a-9013-262ffeff1a8c`，未丢弃或覆盖历史。

## 实际交互与结果

1. 原可信corpus可用时，pending/ready候选有完整事实、原对话及独立报告；勾选两项确认后批准按钮可用。
2. 只有显式fake TESTING+UI入口上的owned-nonce控制可撤回其原corp；调用不接受外部路径/标签/corpus。正常应用和非UI夹具无该路由。
3. 保留浏览器已加载的旧材料，撤回corpus后真正点击批准，实际POST409拒绝。请求仍包含原proofDigest/reviewVersion0和两项true确认，不是因缺必填字段拒绝，也不是伪造响应。
4. 刷新真正GET后，候选状态仍pending/审核版本0/review-null/未发布/规则指针不变；availability=unavailable/material-null/proof-null，blocker=candidate_corpus_missing。候选完整材料移除，批准与发布按钮不存在；独立反馈编辑区仍按原管理权限显示，并非整页清空所有反馈数据。
5. 原游戏的全部读取结果逐字段相同，未新增提问/扣次/重建会话。finally真正恢复原corp，GET重新ready且原proofDigest不变；不是重签标签或替换source。
6. 375×812实际viewport检查：clientWidth375、scrollWidth≤376；截图已主任务实看，表单纵向排列、版本长串换行，无横向溢出。桌面与手机候选不可用状态清楚；不从截图推断真实iPhone设备验证。

## 截图证据

主任务实看以下4张原始截图（观察时工具缩放长图，不修改文件）：

- [原材料加载与待批准](../.cache/ts17/ui-corpus-verified-20261012/ui-results/admin-agent-review-missing-621cf-y-minimal-unavailable-state/trusted-corpus-loaded-pending.png)
- [实际批准拒绝](../.cache/ts17/ui-corpus-verified-20261012/ui-results/admin-agent-review-missing-621cf-y-minimal-unavailable-state/missing-corpus-approval-refused.png)
- [桌面最小不可用材料](../.cache/ts17/ui-corpus-verified-20261012/ui-results/admin-agent-review-missing-621cf-y-minimal-unavailable-state/missing-corpus-minimal-desktop.png)
- [375px最小不可用材料](../.cache/ts17/ui-corpus-verified-20261012/ui-results/admin-agent-review-missing-621cf-y-minimal-unavailable-state/missing-corpus-minimal-mobile.png)

## Console与问题

本用例实际断言uncaught=[]、outsideOrigins=[]通过；console error仅允许预期409请求拒绝。首轮inline JSON attachment未被现有list/简版JUnit reporter落盘，因此raw console条数与精确scrollWidth不从XML猜测；可证明上述边界断言，不声称整站console绝对0。后续最终UI门禁需改为owned文件保存观测后再取证。

本范围未观察到需要修复的网页bug，Critical/High/Medium/Low均0；拒绝409是预期保护，不计作缺陷。不编造Top3问题或全站100/100。功能保护/本页布局有上述证据；全站链接、性能、可访问性和生产TLS的量化健康分数未测，**总体health score=unknown**。

## 相关原生证据与未完成项

新增测试控制原生RED：9case中7FAIL/2PASS/0ERROR/23.886s，失败为缺路由404；最小fixture实现后selected38PASS/0SKIP/64.540s，覆盖非UI路由缺失、nonce拒绝、严格body、实际withdrawal/approval409、原业务保持、恢复后同原请求成功。已有产品拒绝本来正确，未冒充修复新生产bug。

整项目3199离线PASS/14SKIP是本夹具改动之前的checkpoint；最后当前全套/type/lint/独立新发布包、D18来源/unknown契约与ONE整阶段审查仍欠。Docker/Linux、真实provider、人审与生产事项仍HOLD；不会因本报告通过宣布原A58/A59全部达成。
