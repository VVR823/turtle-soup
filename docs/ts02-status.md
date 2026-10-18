# TS-02 实施状态

日期：2026-10-07（Asia/Shanghai）。状态：**LOCAL_VERIFIED_WITH_CONCERNS：独立审查修正与本地门禁完成，生产/跨平台门禁未签收**。

## 已验证

- 001 迁移/快照：30 项先失败后通过；包括 20 个 SQL/快照/账本故障位置、重跑、schema/checksum 拒绝、消息索引与快照防修改/损坏检测。
- 旧局兼容/应用启动：17 项先失败后通过；3 个回填故障位置、原历史保留、真实本地 API + FakeModel 继续旧局、410 异常提示与拒绝启动旧库。
- 隔离 CLI/旧写入口：12 项通过；先观察到缺失能力失败，其中无管理员认证的期望状态码由错误的 403 改为既有正确值 401，未改认证行为。
- 最终本地综合验证：后端 173 passed / 9 skipped，Vitest 7 passed、子进程清理 6 passed、API-only Playwright 3 passed，共 189 passed / 9 skipped；TypeScript typecheck 和 git diff --check 退出 0。239 个运行文件 hash 保持 d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a。
- 首次独立审查因额度不足退出，没有结论；恢复后一次新上下文审查复现 5 类问题。新增 9 个失败测试后全部修正，TS-02 定向共 68 passed；详见 [独立审查与修正](ts02-review.md)。
- 修正后组合 TS-01–TS-03 的最新完整门禁：后端 324 passed / 9 skipped，加前端 7、清理 harness 6、API-only Playwright 3，共 340 passed，运行目录 hash 仍不变；这不是 340 项 TS-02 专属用例。

## 本轮边界

只使用合成旧 SQLite/JSON，不读取玩家原文、私密 dotenv 或真实模型；没有生产迁移、服务器请求、cron 变更、部署、公开上传、commit 或 PR。

Superpowers 从 obra/superpowers 固定提交 8ca22dba9a94f28898bbce59f2537ff4d87c747d 安装 15 个技能文件；本轮实际使用分步执行、失败测试和完成前验证。未安装插件钩子或修改全局权限/遥测。

## 问题与限制

本轮基线在 Windows 沙箱内挂起。最小 asyncio 空循环的 faulthandler 指向 socket._fallback_socketpair/accept；同命令在沙箱外退出 0。已批准的离线测试在沙箱外运行，项目级网络/真实配置数据保护仍开启。首个完整复跑 130 passed / 9 skipped，239 运行文件 hash 保持 d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a。

pytest 有既存 cache 权限警告，未调整用户文件 ACL。7 项真实模型与 2 项本机系统能力测试仍跳过；没有跨平台或远程 CI 实跑。TS-01 的依赖发布阻断仍有效，不能用新测试通过代替依赖修复。

## 验收映射（待最终复核）

| 验收 | 本地证据 | 仍待完成 |
| --- | --- | --- |
| A04 | 合成旧 SQLite/JSON/WAL 备份、原字段/源文件保留；旧 cron/cleanup/HTTP merge 停写 | 实际生产备份副本演练、真实服务器所有写入者盘点 |
| A05 | 001 重跑、checksum、事务故障回滚、索引/FK/完整性 | 002/003 在对应后续阶段实现及故障门禁；OS 矩阵 |
| A06 | 完整冻结基线；正常合成旧局可继续；异常明确 410 | 实际旧格式/题库/规则备份覆盖与维护恢复演练 |

M1 未整体完成，TS-03–TS-18 不在本轮签收。使用方法见 [migrations.md](migrations.md)。
