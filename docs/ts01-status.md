# TS-01 实施状态与验证证据

记录日期：2026-10-07（Asia/Shanghai）；本地验证截止约 10:22 UTC。状态：**DONE_WITH_CONCERNS：本地实现/验证完成，M0 未全部签收**。

## 实际完成的内容

1. 配置显式加载；应用工厂导入时不读取 dotenv、不初始化数据库、不创建 HTTP transport。
2. DATA_DIR、题库、口令、模型/答案缓存、HTTP transport、限流器按应用实例隔离，启动失败和关闭异常也执行资源收尾。
3. 默认 pytest 使用每次测试独立临时目录/FakeModel；收集前保护真实配置/数据和网络。特殊临时目录、SQLite URI、符号链接目标及 Windows 扩展路径均增加保护。
4. 保留旧开发 API/首次显式 CLI CRUD，保留空 CORS 默认来源及 dotenv 插值优先级；未同时重写游戏规则或数据库 schema。
5. Python uv.lock、npm lock、固定 Node 版本、Vitest、API-only Playwright 和离线 CI 配置已加入。
6. 修复 Windows fixture 子进程收尾：正常 EOF 关闭、有限强制兜底、已 exit 的 PID 禁止再次终止；测试失败不允许冒充正常完成。
7. README/操作指南/参考/ADR 同步；旧简历草稿明确标为待证据核验，旧准确率不再作为新版独立评测成绩宣传。

## 本机与干净副本验证

环境：Windows，Python 3.13.13、Node 22.17.0、npm 10.9.2、uv 0.12.3。Python 环境安装 54 个包，清单保存于本机 `.cache/ts01/environment.json`。

| 检查 | 当前工作区 | 干净源码副本 |
| --- | --- | --- |
| pytest | 114 passed / 9 skipped | 114 passed / 9 skipped |
| Vitest | 7 passed | 7 passed |
| 子进程收尾单测 | 6 passed | 6 passed |
| Playwright API 冒烟 | 3 passed | 3 passed |
| TypeScript | 通过 | 通过 |
| `npm run test:offline` | exit 0 | exit 0 |

合计 **130 项通过、9 项跳过**，不是 139 项全部通过。跳过的 7 项为真实模型 QA，另外 2 项为本机不支持的 Unix socket/符号链接权限测试；Linux 与有权限的 Windows 环境仍需补验。扩展 Windows 路径的两项本机负例已通过。

干净副本通过 Git 的 tracked + nonignored untracked 文件清单复制**当前工作树**，初始无 node_modules、无 Python venv、无私密 dotenv/运行数据；保留 tracked QA 源文件但默认测试禁止读取它们。不是新 commit 的 checkout，也不是远程 clone。Python 用锁文件和缓存建立新环境，npm 从锁文件在新目录安装，未运行安装脚本；最终测试源码与工作区一致。源码摘要清单不包含根 README、docs 和 backend/data，以避免报告自引用与数据混入。

已验证负例：非专用 basetemp 被启动前拒绝；占用 18080 时在 HTTP/fixture 启动前失败；Playwright CLI 故意报错时服务正常 shutdown、入口非零；收尾单测覆盖强制退出、有限失败、signal-only exit 和先 exit 后 close，不执行真实 PID 终止来伪造集成证据。

## 运行数据完整性

测试外只读 SHA256 校验：`backend/data` 与根 `data` 共 **239 个文件**，测试前后数量相同，汇总 hash 均为：

```text
d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a
```

命令为 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-test-isolation.ps1`，结果 `RuntimeDataUnchanged=true`、`TestExitCode=0`。没有查询真实数据库行或显示玩家原文，没有读取私密 dotenv。此证据仅证明这次本地测试未改文件，不证明未来任意恶意程序都不能改文件，也不是生产备份/恢复演练。

## 验收映射

| 条目 | 状态 | 未完成部分 |
| --- | --- | --- |
| A01 | 本地干净环境通过；部分验收 | 未提交代码，未做该 commit 的真实 checkout/clone；其余 Python/OS 矩阵未实跑 |
| A02 | 本地通过，范围如上 | native/恶意 subprocess 不在完整沙箱保护内；两个系统能力用例跳过 |
| A03 | 本地入口、标记和严格五类答案匹配通过；部分验收 | CI 只有配置和 YAML 检查，没有 GitHub Actions 运行证据 |

M0 不能标为全部通过。TS-02–TS-18 未在本轮实现：尤其没有受控 Agent 工具循环、版本化规则发布、holdout 成绩或升级后的线上统计。后续可在隔离环境准备 TS-02；生产和公开发布仍需单独授权。

为维持 0 付费，CI jobs 限定公开仓库的标准 hosted runner，私有仓库直接跳过；没有云缓存/产物上传或 larger runner。跳过不是通过，不允许为了触发 CI 擅自公开仓库。[GitHub 计费说明](https://docs.github.com/en/billing/concepts/product-billing/github-actions) 明确区分公开标准 runner 与私有超额用量。

## 发布阻断项

2026-10-07 npm 只读审计：**10 个受影响包，9 high、1 critical**。原 HEAD 锁文件审计为 12 个（11 high、1 critical），当前集合没有新引入的受影响包；数量减少不等于上线安全。

当前 Next.js 16.2.12 位于相关公告的受影响版本范围；具体运行方式与功能决定可利用性。例如 [ImageResponse SVG 公告](https://github.com/advisories/GHSA-vcvr-r3jv-pc5j) 和 [Windows 路由权限公告](https://github.com/advisories/GHSA-p293-qw3h-jr36) 有不同前提。本机源码搜索未发现 next/og / ImageResponse / next/image 导入，配置禁用图片优化，但这不是所有漏洞的豁免证明；线上实际版本/拓扑未核验，不能断言已被攻击或完全安全。

本轮没有自动 `npm audit fix --force`、没有降级 Next/eslint-config-next、没有升级生产依赖或部署。应先在本地选定修复版本，做兼容性、lint、生产 build 和回归验证，再纳入发布门禁；在这些问题消除或正式评估前不放行新版生产发布。

## 复核与限制

pytest XML：工作区 `.cache/ts01/pytest.xml`；npm 审计 `.cache/ts01/npm-audit.json`；环境/源码摘要 `.cache/ts01/environment.json`、`source-manifest.json`。完整本机实施记录保存在工作区相邻的 `turtle-soup-audit`，不包含玩家原文或密钥。

审查采用 gstack checklist 的本地适配 + 3 个独立专业审查 + 1 个 fresh-context red-team；发现的路径/退出/配置兼容问题已修补并加负例。未运行另一种模型/官方 CLI 交叉审查，不伪称正式 PR/发布门禁通过。没有新 Git remote、commit、PR、远程 CI、浏览器 UI QA、真实模型调用、线上请求、部署或公开上传。

复现见 [How to](testing.md)，接口见 [参考](test-runtime.md)，设计原因见 [ADR](adr/0001-test-isolation.md)。
