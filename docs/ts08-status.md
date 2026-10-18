# TS08 页面恢复状态

状态：LOCAL_VERIFIED_WITH_CONCERNS。唯一独立审查与一次修复/完整本地门禁完成，不是线上升级或18阶段总目标完成。见[审查处置](ts08-review-resolution.md)。

## 实现

严格公开 DTO、版本1 浏览器操作记录、路由控制器与 React 订阅接入了真实游戏页。初始化完成前不能提问；同一时刻重复点击只发送一次。断网、刷新、503/429、揭晓回复丢失按原操作恢复，不凭网页报错承诺未扣次数。另开与未知操作放弃均为显式操作，保留服务器历史。站点检查失败不放行，目录错误不冒充空结果，反馈选择使用公开的已解锁目录。

移动底栏与桌面侧栏为浮动反馈保留空间，真实 bbox/输入框 hit-test 和桌面按钮边界均通过。全 lint 排除后端、运行数据和生成缓存，不隐藏 src/scripts/tests 的问题；原后台凭证初始化和列表分页的 lint 问题均通过实际响应回调/状态归属修复。

## 已读证据

| 检查 | 实测 | 证据 |
| --- | --- | --- |
| 后端 | 760 passed /9 skipped | .cache/ts08/post-review-full-gate.xml：769 /0 fail /0 error /9 skip |
| 前端单元/组件 | 182 passed | .cache/ts08/fix-final-frontend.xml：182 /0 /0 |
| Node 隔离/收尾政策 | 25 passed | verify-test-isolation session65012 exit0 stdout |
| API 冒烟 | 3 passed | 同一 gate，实际 PID/正常退出见最后 stdout |
| 合计离线 | 970 passed /9 skipped | session65012 退出0，239 原数据文件 SHA 前后一致 |
| UI | 25 passed | post-review-ui.xml；iVfOuV build0、noncea5226506-053d-4657-96d4-0340bd838096、后端103068和前端正常关闭 |
| 桌面遮挡修复 | RED1/21controls → GREEN22 | ui-desktop-red.xml → pre-review-ui-final.xml；真实按钮 bbox 不相交 |

原数据 SHA：d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a。主执行者已查看移动修复、桌面修复、丢回复恢复、冻结揭晓、零次数、通关、旧口径和反馈弹窗八类真实截图。移动遮挡两轮复现，难度切换旧标题/按钮一项永久测试先失败再修复；首次 UI 定位错误与新增“陈述句会得到免费提醒”的测试夹具问题不计作业务缺陷。[观察记录](ts08-browser-observation.md)保留失败分类。

## 对应验收与限制

A28 最终评分刷新、A30 初始化保护、A31 刷新恢复、A32 目录/站点错误、A33 lint、C13–15 对应上述组件与真实浏览器路径；最终独立审查已闭环，2个Minor（返回旧页的草稿、锁屏提交前storage失效）安排TS17回归，未冒称修复。UI 与原3项 API 套件分开，生产构建仅使用无 dotenv/data 的自有副本，standalone 包装在该副本关闭，不是 TS17 发布包签收。

FakeModel、故障注入与合成旧结果明确标注；未执行真实模型、生产部署/迁移、真实用户资料读取、Safari/iOS 真机、跨 OS、全面可访问性/性能评测。免费账户资格、真实语义质量、跨设备恢复和全局多标签锁不在已通过证据中。

操作指南见 [testing](testing.md)，接口见 [test-runtime](test-runtime.md)，原理见 [恢复解释](game-recovery.md)。
