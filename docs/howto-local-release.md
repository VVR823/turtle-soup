# How to 验证本地隔离发布与最新数据恢复

2026-10-14最新检查点：D18唯一整项审查处置后，当前380/6053fa…完成3456离线通过/14明确跳过、35Edge、当前新包构建/HTTP/源码绑定与新容器输入复验；原239运行数据和Git摘要未变。见[当前本地证据](d18-local-verification.md)。本页下方早于此检查点的冻结数字/“仍待”说明为历史，不当最新状态；真实模型、人审、生产、公开与原完整任务签收仍未通过。

只做本机、合成数据演练：验证“交付代码包”不携带玩家数据或密钥，验证最新合成数据恢复后不丢不重。不是上线命令，也不授权操作生产库。

## 前提

- 当前仓库在 `D:\CODE\turtle-soup`；示例使用本机PowerShell7，Node版本符合package.json的22.17–22.x，已安装npm锁定依赖及backend/.venv-ts01。离线测试使用uv --offline --no-sync，不自动安装。
- 新目录必须由本次任务独占，路径绝对且不经过符号链接/NTFS junction；不要复用已存在产物、旧数据目录或真实用户路径。
- 最新实施以[D18 ledger](superpowers/plans/2026-10-13-d18-progress.md)为准；[TS17唯一审查](ts17-review-resolution.md)的3231离线/33Edge只属于旧冻结。D18审查前完整冻结验证和唯一整单元审查已完成，当前仍待修复后完整验证、产物重绑定及最终签收；生产A58–A59仍欠，不能把本地门禁当上线通过。

## 1. 创建并验证backend合成demo

在仓库根目录执行：

```powershell
node scripts/test-backend-release.mjs
if ($LASTEXITCODE -ne 0) { throw 'Backend demo未通过，停止' }
```

命令生成新的 `.cache/ts17-backend-*-artifact` 和独立合成data目录，并输出精确实际receipt。成功必须同时有health/publicSeed/chatReplay/moduleOriginsVerified/fixedSuiteSourcesVerified/ownedResourcesClosed与networkAttempts0。

包仅复制固定代码allowlist和锁文件；原 `backend/app/soups.py` 不读取/复制，包内生成只有一条自行编写的synthetic seed。原dotenv、玩家库、私有题库、评测标注、测试、venv、旧deploy、备份均不带入。manifest精确检查内容与额外文件；manifest不是代码来源签名、整库密钥扫描或公开许可证明。

冒烟启动新的 `-I -B`解释器，实际app/eval导入只在产物，实际创建/提问/幂等重放及资源关闭。它复用本机已安装依赖，**不是新机器安装、Linux/wheel/容器验证**。CLI输入处理尚不是面向任意调用方的生产发布工具。

## 2. 从物理隔离输入构建frontend并验证独立包

仍在仓库根目录：

```powershell
$buildInput = (node --input-type=module -e 'import { prepareStandaloneFrontend } from "./scripts/standalone-input-policy.mjs"; console.log(prepareStandaloneFrontend(process.cwd()).directory);').Trim()
if ($LASTEXITCODE -ne 0) { throw '物理隔离输入未通过，停止' }
node scripts/test-standalone-build.mjs $buildInput
if ($LASTEXITCODE -ne 0) { throw '独立构建未通过，停止' }
$releaseArtifact = Join-Path (Resolve-Path -LiteralPath '.cache').Path ('ts17-frontend-' + [guid]::NewGuid().ToString('N'))
node scripts/test-standalone-release.mjs $buildInput $releaseArtifact
if ($LASTEXITCODE -ne 0) { throw '产物或HTTP冒烟未通过，停止' }
```

输入准备真实复制已安装node_modules为物理目录，并核对原树与副本每个文件hash；需要约517MB副本空间，本机先前余量只代表检查时刻，运行前请再次确认。不下载新依赖，不修改原node_modules。不得通过扩大tracingRoot到真实workspace来绕过Next trace错误。

构建使用副本自己的Next CLI、封闭config和trace根。包装只从新输入复制standalone/public/.next/static，精确manifest拒绝额外文件/空目录/redirect/私有运行文件。冒烟真的启动包内生成的server.js，检查4个HTML路由、从HTML发现的JS/CSS字节和publicasset；模块实际只从包内加载，无外连；实际正常关闭并重绑定端口。Next16.2.12协作SIGTERM正常退出143，并需同时满足nonce/EOF/来源/无强杀证明，不能仅靠143数字签收。

不同源码修改后必须新目录构建和封存，不覆盖旧包。这里证明的HTTP页面不是浏览器交互、手机设备、真实模型、Linux或线上证书验证。生产NEXT_PUBLIC_API_BASE需与已核验TLS/代理保持一致；它是构建时公开配置，不能填供应商密钥。

## 3. 演练最新合成数据恢复与回退

运行已有原生演练，自动使用本次新合成临时库，不把生产DATA_DIR传给它：

```powershell
node scripts/test-backend.mjs backend/tests/test_release_recovery.py backend/tests/test_recovery_quiescence.py backend/tests/test_release_recovery_business.py backend/tests/test_post_publication_recovery.py backend/tests/test_packaged_backend_compatibility.py -o cache_dir=.cache/d18/recovery-repro-cache
if ($LASTEXITCODE -ne 0) { throw '恢复演练未通过，停止' }
```

这会验证实际业务API/候选/发布之后的最新4局/4turn/8消息、反馈、任务、候选、版本和幂等；合法但过时备份会被独立最新状态核验拒绝。规则指针回退保留游戏/反馈/任务/不可变规则版本，**不等于拿旧库覆盖新库**。schema1启动明确拒绝，schema2/3/4原生读写/重放与版本保留有单元证据；这不自动批准任意代码×feature×schema兼容组合。

备份原语接口是 `backup(source:str,target:str,report:str)` / `restore(source:str,target:str,report:str)`，CLI `python -m app.scripts.snapshot_recovery backup|restore --source ABS --target NEW_ABS --report NEW_ABS`。三路径须按原语规则隔离，输出不得存在；所有输入由演练自己生成。backup先复制数据库+WAL到自有scratch再SQLite backup验证001–005；restore先完整核对manifest，只恢复到NEW目录；**不负责生产全局停写，也不负责迁移**。005计划/终态/running及出生证据不丢，不自动重跑；真实模型质量未验证。不要把代码签出的目录或玩家目录当实验输入。

`require_local_quiescence(runtime, external_writers)`只观察实际已关闭的TESTING Runtime：model/Agent/audit/HTTP及pending；external_writers必须恰好声明api/cron/timer/legacy_merge/legacy_cleanup/manual_scripts/direct_database为stopped或disabled。声明不是发现或停止全生产写入者的证明，因此quiescenceVerified仍false。本机4个symbolic-link创建权限分支保留SKIP/HOLD，NTFS junction拒绝有实际证据，不偷偷改系统权限。

按[恢复兼容矩阵](release-recovery.md)逐格判断：D18当前backend包schema1拒绝/2–5核心重放、metrics边界与旧4包拒绝5；未测Agent/候选能力仍UNKNOWN。TS17历史完整身份只用于历史源，D18完整源码/新frontend身份和最终验收以ledger为准。UNKNOWN不允许据此恢复生产写入；原始旧HEAD和未测编译包不是可自动回退版本。私有统计wire3、cursor1与数据库005不能混为一个版本号。

## 验证与故障处理

### 容器输入目录（不是已构建镜像）

`scripts/container-context-policy.mjs`提供 `buildContainerContext(kind, artifact, target)` / `verifyContainerContext(kind, artifact, target)`；kind仅backend/frontend，artifact须先通过现有release verifier，target必须是项目.cache的新独立直接子目录。仅复制已验证产物的文件和release-manifest到release/，保存独立context-manifest；拒绝额外文件/空目录、junction、源改变、重签清单、重叠和已有输出。verify仍需要原可信产物，不凭新清单自证来源。

该工具没有运行Docker，也没有生成默认Dockerfile；`containerBuildVerified=false`始终保留。不要把旧Dockerfiles套到项目根、backend或这个输入目录。实际Linux锁依赖构建、审核过的基础镜像digest、Dockerfile/非root运行、数据与私密env挂载、容器端口和TLS/代理仍待额外环境及相应验证。本机103项harness包含14项输入边界验证，不是103项镜像验收。

单元成功后仍需当前 `npm run test:offline`、typecheck、lint、隔离build、真实Edge、原运行文件hash与HEAD/index保护、唯一阶段审查与一次必要修正。旧截图/旧XML/旧产物不能代替当前源码的门禁。

- 任何复制、manifest、来源或HTTP失败：保留失败目录/log，不覆盖它、不改私有路径限制；创建新owned输入后定位原错误。
- 同时有live gate/server/reviewer：只接续同一handle，不并发修改或重启另一套；终态结果必须实际读取。
- 异常模型输出与语义答错是不同问题。前者不得冒充合法答案或扣次；普通问法继续正常游戏。绿色合成回归只说明程序边界，不证明AI语义永远正确。
- 配额耗尽保存ledger、等待正常小时续跑；恢复后自动接续，不要求阶段确认、不买额度/换卡/绕审批。

## 生产发布阻断清单（未执行）

这些是将来取得额外授权后须满足的门禁，不是当前上线记录：

1. 核实实际服务器/CPU/RSS/磁盘/依赖漏洞与Linux/容器构建。现有Dockerfiles仍历史配置，当前本机无docker命令，不签容器成功。
2. 核验SSH host key与密钥身份，不自动接受未知指纹、不要关闭host-key验证；权限最小化、不从聊天或仓库传生产密码。
3. 核验TLS证书链/主机名/有效期、nginx语法与实际peer/CIDR。只对已确认直连可信代理配置TRUSTED_PROXY_CIDRS；不能信任客户随意的转发头。
4. 分开不可变release、`/var/lib/...`运行数据和`/etc/...`私有env；非root单worker、Agent默认关闭、独立管理与站点口令、私密目录权限。模板路径必须与实际产物布局核对，当前demo不含scripts/run-backend.py，不能直接套用旧service模板启动。
5. 实际维护入口先拒绝新写入，再核对所有API/cron/timer/旧merge-cleanup/人工脚本/directDB写入者真正停止、清理回执/在途为0；未知项保留维护，不能推测。
6. 备份维护时刻的LATEST数据，独立验证hash、恢复到新目录、最新业务ID/次数/消息/版本核对通过；记录兼容矩阵后才人工显式迁移。001–004原checksum、启动所需2、默认migrate1不改；004/005只显式授权迁移，不在启动自动补。
7. 新release健康/功能/权限/幂等/Agent可用性检查与依赖/版本核验都通过后才切换并解除维护。失败保持维护；兼容旧代码则只退代码/规则指针，保留最新数据；不兼容则保持维护到在NEW目录恢复最新数据验证通过，禁止旧备份覆盖新游戏。
8. 真实用户/真实模型/人审标签/后续发布回归统计来源及完整分母必须单独取证，缺证据写unknown。全本地绿色也不等于这些已验收，不公开上传或部署。

旧deploy整目录覆盖脚本和HTTP/root密码教程已标为历史退役，**不得运行**。相关：[资源测量参考](ts17-resource-measurements.md)、[迁移参考](migrations.md)、[既有代理模板](../deploy/templates/turtle-soup-api.conf)、[阶段ledger](superpowers/plans/2026-10-12-ts17-progress.md)。
