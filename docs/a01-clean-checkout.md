# A01 本地干净检出与安装证据

2026-10-16 更新：此前“3040只收集、完整后端未执行”的缺口已补测。独立 checkout/54 个原锁定包实际全跑 3025通过/15跳过；额外的历史发布包缺失 skip 经固定 manifest/78 文件核验复制后，原用例补验1通过，合计3026通过/14跳过。原完整 XML 不改写，546条SQLite ResourceWarning保留；304后端/守卫输入与主库一致，收尾独立Git干净。详见[最新本地验收](local-acceptance-2026-10-16.md)。下方为先前阶段记录；这仍不代表当前整仓 Git clone、CI/跨平台或全部验收已经完成。

2026-10-15。本次A01本机限定验证单元已完成并获独立审查支持；原完整验收不扩签。本页验证的是当前许可源码生成的本地验证快照，不是原仓库已经提交、远程可克隆或公开样例已放行。

## 实际检出

- [二版检出回执](../.cache/a01/v2-checkout-receipt.json)：独立本地验证提交61e69de612a6124e9daeab3cb7fe7b9e049971e1，421文件逐字节一致、初始Git状态干净。
- [输入清单](../.cache/a01/v2-snapshot-inputs.json)：400个现有许可源码文件，加16个构建/说明/静态资源输入与5个backend/testing支撑模块。输入摘要7f3e05f437ab292c23c2182fc61bc2c618bfd000188d2e650910a7a8697540ce。
- 目标为.cache/a01/checkout-v2-LZkw8i/checkout。起始无node_modules、venv、私有dotenv、backend/data或根data，不拷贝主Git目录；拒绝源链接、私有holdout及路径越界。
- 独立seed/clone禁全局Git配置、换行转换、钩子、签名和HTTP远程克隆；没有改写主仓库HEAD、索引或用户修改。

## 安装与运行

| 项目 | 实际证据 | 状态 |
| --- | --- | --- |
| 基础工具 | Git2.53.0.windows.2 / Node22.17.0 / npm10.9.2 / uv0.12.3 / 基础Python3.13.13 | 本机实际读取 |
| Python锁定安装 | [v2离线安装](../.cache/a01/v2-install-offline-python-receipt.json)，uv sync --locked --group dev --offline，独立新venv | exit0 |
| Python包与来源 | [54包清单及模块来源](../.cache/a01/v2-python-environment.json)、[全部包对锁核验](../.cache/a01/v2-python-lock-provenance.json) | 54个实际包名称/版本全部匹配uv.lock，分发根目录均为新venv，无全局site-packages |
| 默认后端收集 | [验证回执](../.cache/a01/v2-clean-python-verification.json)及[v2收集日志](../.cache/a01/v2-clean-python-collection.log) | 3040项收集成功，非3040项执行 |
| 配置隔离冒烟 | [v2日志](../.cache/a01/v2-clean-python-settings.log)，checkout/.cache/a01-settings.xml | 50通过/2平台能力跳过 |
| Node离线安装 | [v2真实失败](../.cache/a01/v2-install-offline-node-receipt.json) | ENOTCACHED，Next16.2.12缓存未齐 |
| Node联网安装终态 | [真实失败回执](../.cache/a01/v2-install-node-registry-receipt.json) | 12:32:15Z退出1/ECONNRESET，非仍在运行 |
| 两项缺缓存补齐 | [独立缓存恢复](../.cache/a01/v2-cache-recovery-receipt.json) | 官方原锁tarball串行各一次，两个原完整性值均可读；无checkout改动 |
| Node锁定离线安装 | [独立终态](../.cache/a01/v2-install-node-offline-recovery-receipt.json)、[日志](../.cache/a01/v2-install-node-offline-recovery.log) | npm ci --offline退出0，19秒安装446包，禁安装脚本/审计上传 |
| Node全部实际包来源 | [446包实际清单与对锁核验](../.cache/a01/v2-node-package-provenance.json) | 实际package.json版本及本地锁来源/完整性匹配原锁，目录全部位于新checkout |
| 新Node环境运行 | [四步终态](../.cache/a01/v2-node-verification.json) | 前端399通过，类型退出0，进程测试103通过，合成API3通过并正常关闭；421输入零漂移 |

只使用基础解释器建立新环境，没有复制或链接主仓库node_modules/venv。Python安装使用公共包缓存；这不是复用旧安装环境。模型密钥/追踪环境不传入验证进程，未调用真实模型。

## 已发现并保留的问题

首版416文件快照虽能完成uv安装和实际Git检出，但测试启动时缺testing模块；[首版验证](../.cache/a01/clean-python-verification.json)记录两个exit4，不能写成测试通过。实际包位于backend/testing，400文件旧身份未覆盖这5个支撑文件。只修快照工具许可清单，另建二版重新检出，不在原已安装目录补文件后冒称起始完整。

首版Node离线缺zod-validation-error4.0.2，随后一次官方锁定安装在十分钟总时限结束：[原终态](../.cache/a01/install-node-registry-receipt.json)为ETIMEDOUT/SIGTERM，非成功。诊断日志证明大量官方tarball已真实下载，两种官方HEAD检查均200，不归因为权限拒绝或全面网络阻断。二版联网安装实际18分钟后ECONNRESET，保留清理EPERM警告，未放宽权限。14:16Z只读缓存核验发现当前平台445包条目已缓存、仅Next16.2.12与原生SWC16.2.12两项原锁完整性值缺失；随后单独官方缓存请求各32秒/28秒成功，再进行一次完全离线npm ci。串行请求成功不等于已证明前次断连的网络根因。

所有锁文件保持原字节；检查全部resolved来源为官方npm HTTPS且存在完整性值。npm lifecycle安装脚本及审计上传禁用；Python本地editable构建后端确实执行，不能把原回执installScriptsAllowed=false解释为Python构建也被禁用，见[原记录绑定澄清](../.cache/a01/v2-install-script-scope-clarification.json)。无付费服务、生产或模型访问，仅下载公开锁定依赖，没有上传项目内容。

## 继续与限制

安装与四步运行已全部终态，不重复安装/测试。配置冒烟50与前端399/进程103/API3属于本次新环境实跑；3040仅为收集数量，不能把它写成全部后端通过，也不把重复环境验证加到旧全套总数。[独立只读限定审查与处置](superpowers/plans/2026-10-15-a01-review-resolution.md)：Kuhn实际报告Critical0/Important0/Minor1，支持LOCAL限定结论；字段改名作为minor保留，事实范围已澄清，不重写历史收据，不重复A46审查。

新环境完整统一入口、其它Python/OS矩阵、远程CI、真实模型、人审、生产/公开均未由本页证明。原完整范围继续见[全范围审计](upgrade-completion-audit.md)；计划/恢复点见[本地计划](superpowers/plans/2026-10-15-a01-clean-checkout.md)和[ledger](superpowers/plans/2026-10-15-a01-progress.md)。
