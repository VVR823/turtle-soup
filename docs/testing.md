# How to 运行 Turtle Soup 的离线测试

在不使用个人模型密钥、运行数据或线上站点的情况下，复现工程测试。这里的“离线”指**测试执行**不需要真实网络；首次下载依赖需要网络，缓存完整后可以离线安装。

## 前置条件

准备 Node 22.17.0、npm 10.9.2、Python >=3.11,<3.14、uv 0.12.3。下面全部在仓库根目录运行，无需复制 `.env.example`，无需 Ollama，也无需下载 Playwright 浏览器。

## 1. 安装锁定依赖

PowerShell：

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path (Get-Location) 'backend/.venv-ts01'
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.cache/uv'
uv sync --project backend --locked --group dev --python python --no-managed-python
npm ci --ignore-scripts
```

Linux/macOS：

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/backend/.venv-ts01"
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --project backend --locked --group dev --python python --no-managed-python
npm ci --ignore-scripts
```

`--locked` 拒绝隐式更新 Python 锁文件；`npm ci` 校验 npm 清单与锁文件匹配。`--ignore-scripts` 不运行依赖安装脚本；本轮测试已验证可用，但并未因此验证 Next.js 生产构建。不要用 `--force` 或 `--legacy-peer-deps` 掩盖版本冲突。

## 2. 验证默认入口

```bash
npm run test:offline
npm run typecheck
```

顺序为后端 → 前端 → 子进程收尾单元测试 → API 冒烟；前一项失败就不继续下一项。后端结果中真实模型套件应显示 skipped，当前实测数量见 [状态记录](ts01-status.md)，不要把跳过理解为通过。

API 冒烟在 **127.0.0.1:18080** 创建自己的临时服务，每次生成不可复用的实例 ID；端口已占用时直接失败，不复用已有服务。运行结束后必须看到后端正常 shutdown。测试数据只放在 `.cache/e2e-*`，保留用于调试，不会清理真实玩家数据。

## 3. 跑单项或验证数据不变

```bash
npm run test:backend
npm run test:frontend
npm run test:e2e
```

指定 pytest 参数时可直接用 Node 入口，避免某些 Windows npm 包装器吞掉参数：

```bash
node scripts/test-backend.mjs backend/tests/test_settings_isolation.py -q
```

PowerShell 中对 `backend/data` 和根 `data` 做测试前后 SHA256 校验：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-test-isolation.ps1
```

输出包括文件数、汇总 hash、`RuntimeDataUnchanged` 和测试退出码。哈希脚本只计算文件摘要，不输出玩家原文/数据库行，不读取 dotenv。该操作是**测试进程之外的只读完整性检查**，不代表允许 pytest 读取这些数据。若有另一个服务同时写数据，摘要可能变化；不要为获得一致结果擅自停止线上服务。

## 真实模型和线上检查不是默认测试

CI 仅在公开仓库的标准 GitHub-hosted runner 上运行；私有仓库跳过，不表示测试通过。流水线不使用远程缓存/产物上传或付费 larger runner。公开前仍须单独授权，不能为了 CI 擅自公开代码。此限制遵循 [GitHub 的计费说明](https://docs.github.com/en/billing/concepts/product-billing/github-actions)，将私有分钟超额计费排除出默认流程。

真实模型 QA 带 `real_model` 标记，默认跳过。需要运行时必须另外确认免费资格、供应商、脱敏范围和调用预算，并通过进程环境提供配置；测试不会自动读取个人 dotenv。

只有在获得真实调用授权后，设置 `TURTLE_SOUP_REAL_MODEL_CONFIRMED_FREE=1` 并显式传 `--real-model` 才能启用相关套件。这个变量只是人工声明，不会替你核实供应商计费；本轮未设置或执行。

`online` 标记需要 `--online`。现有 `backend/tests/online` 含历史线上脚本，默认不收集；本轮也不作为已授权、安全的线上检查入口。不要通过 `--real-model`/`--online` 给整个默认套件开放网络来运行非必要测试。

## 故障排查

- 旧 `.venv` 解释器指向不存在路径：使用新的 `.venv-ts01`，不删除或覆盖旧环境。用显式可用的 Python 路径替换安装命令的 `--python python`。
- `uv` 找不到依赖或 pytest：先运行锁定同步。测试入口使用 `--offline --no-sync`，不会测试时悄悄联网补装。
- `18080` 被占用：先只读确认占用来源。不要开启服务复用，也不要杀未知进程；本次测试拥有的服务应随入口正常退出。
- pytest 报 `TestAccessBlocked`：真实配置/数据访问或不属于测试的网络请求被拒绝。修正 fixture 和数据路径，不要关闭保护换取通过。
- pytest 的 Windows 临时目录 ACL 错误：默认使用仓库 `.cache/pytest/run-*`，无需接管个人临时目录权限。
- 自定义 `--basetemp` 被拒绝：只能选择 `.cache/pytest` 下新的或空的专用子目录；禁止运行数据、工作区根、已有非空目录及 cache symlink/junction。pytest 会删除 basetemp 内容，不能随意指向已有文件夹。
- pytest 真实模型被拒绝：未获免费确认或未显式 opt-in。默认跳过是设计行为。

更多接口/配置说明见 [参考](test-runtime.md)，设计原因见 [隔离 ADR](adr/0001-test-isolation.md)。

## How to 运行真正的页面恢复门禁

在上述依赖已安装的仓库根目录运行 `npm run test:ui`。Windows 需已安装系统 Edge；其他平台需已经存在的 Playwright Chromium。缺浏览器时不会自动下载，报告 UI 未验证；原 `test:offline` API-only 门禁不依赖浏览器。

```bash
npm run test:ui
```

入口自动建立无私密配置的前端副本、做本地生产页面构建、启动自有18080/18081服务，然后运行 tests/ui。它会实际验证重复点击、刷新后原 UUID/计数、结果冻结、零次数/通关自动揭晓、站点/目录故障与手机/桌面遮挡。结束必须看到 `TS08_FRONTEND_CLOSED:0`、后端正常 shutdown 和 `TS08_UI_CLEANUP:0`，以及退出码0；不能只看绿色用例就忽略收尾失败。JUnit 在 .cache/ts08/ui-junit.xml；截图/失败 trace 在 .cache/ts08/ui-results。每次都是新合成数据/浏览器上下文，不是生产玩家。

端口占用：只读核对来源，不杀未知进程、不配置 reuseExistingServer。缺解释器/依赖：按前置步骤修复安装，不指向真实服务。Windows 沙箱 junction EPERM 是测试运行权限问题，不是允许更改 ACL 或删除缓存的理由。故障测试明确注入在这两条 owned origin 上，不代表免费云模型质量/真实断网网络已通过。不要传生产 base URL 或 CLI config 覆盖；入口会拒绝它们。

## How to 保留前端 JUnit 证据

部分 Windows npm 包装器吞掉 `npm run ... --` 参数。需要命名报告时直接使用现有 CLI：

```bash
node node_modules/vitest/vitest.mjs run --reporter=junit --outputFile=.cache/ts08/frontend-current.xml
```

先检查文件实际存在，再读取 tests/failures/errors。命令提出一个文件名不等于报告已经写入，名字含 green 也不等于通过。若需保留 UI 红/绿结果，在下一次运行前复制这一次的 XML/截图；不要覆盖唯一失败证据。最新阶段数字见 [TS08状态](ts08-status.md)。

## TS-09 审计回归与证据

全项目仍使用 `npm run test:offline` 与上面的独立 `npm run test:ui`；先等 API 服务正常关闭，再启动 UI，避免共用18080端口。审计定向入口可运行 `node scripts/test-backend.mjs backend/tests/test_audit_fallback.py backend/tests/test_audit_http.py backend/tests/test_audit_transactions.py backend/tests/test_audit_admin.py backend/tests/test_audit_query_plan.py -q --junitxml=.cache/ts09/audit-current.xml`，不加真实模型/线上标记。

Windows 根 pytest 缓存权限警告时，可只给本测试进程追加 `-o cache_dir=.cache/ts09/pytest-cache`，不更改 ACL/删除缓存或绕开数据守卫。完整门禁报告默认写 .cache/ts01/pytest.xml，UI默认 .cache/ts08/ui-junit.xml；下一次运行前复制到对应阶段新名字并实读计数。原数据 manifest 必须用同一 Windows PowerShell/verify-test-isolation.ps1 格式比较，不混用路径规范化/JSON序列化造成假差异。

状态见 [TS09](ts09-status.md)，接口/未知用量/缺口解释见 [请求审计](request-audit.md)。这些数字仅是本地合成/FakeModel证据，不是历史真实请求完整率、真实模型准确率或生产延迟。

## TS10 反馈与停版门禁

TS10最终本地审查修复结果以状态页为准，不等于生产验收。

仍运行完整`test:offline`、串行`test:ui`与原数据字节hash守卫，不改真实模型开关。UI新增真实表单→SQLite反馈→后台服务器版本审核、另一审核者409及原对局停版/解除恢复；审批不自动授模型权限或发布答案。测试停版setup仅在独立UI fixture注册并校验本次实例nonce，普通create_app/生产/API-only模式不存在这个路由。

定向报告、测试失败原因和当前未完成门禁见[TS10状态](ts10-status.md)，精确字段/隐私边界见[反馈规则](feedback-rules.md)。每轮UI生成的`.cache/ts08/ui-junit.xml`需在下一轮前复制到TS10目录保留，不把修正测试URL的失败说成产品回归。可选空理由是真实合法输入，应在真实后台页面中接受；无效响应后刷新必须可恢复，不能以禁用重试隐藏异常。

## TS11 数据与封存门禁

默认pytest testpaths包括backend/tests和backend/eval/tests，根网络/运行数据守卫保持有效。专项：`node scripts/test-backend.mjs backend/eval/tests -q --tb=short -o cache_dir=.cache/ts11/pytest-cache --junitxml=.cache/ts11/dataset-current.xml`；再完整离线、串行UI、lint/typecheck/原239字节hash。下一轮前保留XML新名字并实读，不复用旧数字。

CLI与人工步骤见[数据指南](evaluation-data.md)，待定门禁见[TS11](ts11-status.md)。合成人工声明是测试夹具；pending110仅证明草案规模，不证明模型准确率、真人确认或独立holdout。不要执行旧accuracy入口补证据。

## TS12 完整分母 / 同预算比较

专项入口：`node scripts/test-backend.mjs backend/eval/tests -q --tb=short -o cache_dir=.cache/ts12/pytest-cache --junitxml=.cache/ts12/eval-current.xml`。默认整套后端已包括所有Eval用例，阶段整套可从JUnit中精确统计classname以`backend.eval.tests.`开头的用例，不再另外重复同一整套；不要用`*eval*`误包含backend/tests/test_evaluation_*。

完整离线、原239字节hash与真实UI仍串行，API正常关闭后才开启18080/18081页面门禁。旧入口现在安全转向`eval.run_cli`，无参数/旧筛题参数拒绝；既有数据/报告不删不覆盖。真实模型开关、生产数据与根守卫没有放宽。

手算8条混合结果、相同代词/错误历史、非法JSON/429/timeout/预留计数、未收尾停止下一题/下一repeat、全重复缺失/参数漂移、报告自重算篡改、未知用量与CLI冷导入有永久测试。三系统夹具是合成工程证据，实际CLI缺旧基线时退出2/质量null。操作与当前阶段门禁见[运行器](evaluation-runner.md)/[TS12](ts12-status.md)。
