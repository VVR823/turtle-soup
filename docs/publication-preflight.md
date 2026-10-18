# 公开前盘点：目前不能自动上传

以下是2026-10-12T16:41:40.863Z的TS18历史本机只读预检查，保存原356/c34aaff…及TS17旧包身份，不是最新D18代码/制品的盘点。结果是**当时产物完整性已核验，公开许可未成立**，`uploadAllowed=false`。它不是全库安全扫描，不是GitHub发布记录，也没有读取原玩家记录来“证明”它们可以公开；最新版本不能沿用这份旧报告宣称公开门禁通过，见[原范围审计](upgrade-completion-audit.md)。

## 检查对象和身份

[实际机器回执](../.cache/ts18/publication-preflight.json)记录时间、检查边界、类别及不含原文的opaqueIdentity（不显示匹配内容的摘要编号）。

| 对象 | 本次实查 | 不能推出的结论 |
| --- | --- | --- |
| backend合成包 | [VEVQiL](../.cache/ts17-backend-VEVQiL-artifact)，78个清单文件，manifest `ab61062c21dc29eaeca16234ed459415815eff10b1bb298922aaf73c2220fa85` | 不等于来源认证、许可核验或新机器安装 |
| frontend独立包 | [review-fixed产物](../.cache/ts17-standalone-review-fixed-66a0b318-7369-48d6-aaf8-55b0313b88e2)，2045个清单文件，manifest `6348f0eb732f8e41a0a4f19643d5b9f9d6612abadac32bef28fa3e2df5fdd88e` | 不等于所有JS/HTML均已内容扫描或Docker验证 |
| 当时源码（非最新D18） | [冻结356文件身份](../.cache/ts17/review-fixed-final-verified-20261013/review-fixed-code-identity.json)，c34aaff...；[恢复矩阵](release-recovery.md)注明完整身份 | 不包含docs、JSON语料、Git历史、运行数据或全部依赖 |
| Git元数据 | HEAD `c5765b68cb251a7c566e76e2887d335d6ed6b285`，1个可达提交、150个跟踪文件、175条可达对象元数据 | 不等于内容无密钥；本次未检查每个历史blob的内容 |
| Git保护 | 检查前后HEAD与index摘要相同，index `45c635efdd2844f5a8dac3cf3b6b7fbb4caa6a54a2f247f3f8cc902c4ca275f5` | 未改写、清理或重建历史，也没有提交新代码 |

清单文件数不包含release-manifest自身；因此容器输入的79/2046个复制文件不是另一份产物数量。旧frontend 7ebe...不作为当前版本。

现有精确校验器为[backend policy](../scripts/backend-release-policy.mjs)与[standalone policy](../scripts/standalone-release-policy.mjs)。本次实际调用了两者，拒绝清单/字节/目录集合或重定向不一致；不是只检查manifest文件存在。

backend固定复制allowlist，包内生成单条`demo-synthetic`，不复制原`app/soups.py`、玩家库、dotenv、私有标注或评测案例目录。合成seed不保证其它业务源码没有嵌入原题事实，全部代码正文及来源仍须另查。frontend只带独立server、已追踪依赖、构建页面与静态/public资源；这仍不能检测允许文件中藏着的敏感内容。现有[backend反例](../scripts/tests/backend-release-policy.test.mjs)和[frontend反例](../scripts/tests/standalone-release-policy.test.mjs)有真实canary、篡改、缺文件与junction拒绝；最近103项harness的通过见[TS17最终记录](ts17-review-resolution.md)，不是本次新增扫描器测试。

## Git盘点到底检查了什么

只读命令使用`git rev-parse HEAD`、`git rev-parse --git-path index`、`git ls-files -z`、`git rev-list --all --count`和`git rev-list --objects --all`。Node以参数数组调用Git，不拼接文件名执行shell；stdout限制4MiB。对象路径只在内存分类，不打印原始路径/值。分类规则：

- 非`.example`的`.env`路径：潜在密钥路径。本次匹配0，**不能解释为密钥0个**。
- data/datasets/backup/backups路径或sessions.db/feedback.jsonl/verified_qa_pairs.jsonl：潜在运行或私有材料路径。本次68条元数据匹配，**不是68个已确认泄漏**。
- 原题库模块路径：1条需核验题目来源和发布范围的元数据匹配。
- 其他路径未因未匹配就获准公开；Git历史内容未扫描，已删密钥、普通代码中嵌入的凭据仍可能漏掉。

本次跟踪许可文件匹配0，只说明`git ls-files`中没有匹配LICENSE/COPYING文件名，不能证明工作树或依赖不存在许可文件，更不能替代来源授权。没有读取blob正文、私有题库正文、真实dotenv或玩家消息；`historyContentsInspected=false`。可复核数量而不显示内容：

```powershell
git rev-list --all --count
@(git ls-files).Count
@(git rev-list --objects --all).Count
```

本次结果分别为1、150、175；以后提交变化应产生新报告，不能照抄旧数字。盘点只覆盖本地可达refs，不证明远程、reflog或其它副本没有私有对象。

## 每项公开门禁单独保留

| 门禁 | 当前状态 | 后续需要的证据 |
| --- | --- | --- |
| 指定两个本地产物完整性 | 已验证，仅完整性 | 文件或来源变化后重新验证 |
| 指定产物当前源绑定及本机运行 | 已验证，合成/Fake证据 | 见[本地发布指南](howto-local-release.md)；不扩大成生产 |
| 工作树全部文件与Git全历史内容检查 | HOLD，未完整检查 | 有明确边界、不会泄露匹配值的内容检查记录；失败不上传 |
| 原题库/视频问答/真实反馈/玩家数据公开权限 | HOLD，未核验 | 可证明来源与许可范围的材料；不能把匿名化想象成授权 |
| 自有样例、源码与第三方依赖发布范围 | HOLD，未最终核验 | 合成seed可识别且不带原题库，但全部代码/资产/依赖范围须另外核验 |
| 公共仓库上传授权 | HOLD，本次任务未授权 | 用户后续明确指定公开范围；当前不自动请求或上传 |
| 干净公共clone可复现 | HOLD，没有公共仓库 | 获授权后在新隔离目录验证，不能把本机复用依赖当干净clone |
| 真实模型七段演示与补充失败片段 | HOLD，没有录制/资格证据 | [演示清单](showcase.md)所述版本、权限、模型和录制证据；Fake截图不替代 |
| 本人技术掌握 | 待本人练习验证 | [学习路线](learning/project-learning-map.md)，不能由AI替本人签收 |

当前README、日志、缓存、原Git仓库及本报告均为私有工作材料；别直接整目录压缩上传。`.gitignore`只影响部分未跟踪文件，不清除已提交历史，也不决定构建文件内容。SHA摘要像“包裹封条”，能检查有没有变化，不能证明里面东西的来源或公开权限。

## 为什么没有新增扫描工具

现有只读Git命令、两个严格产物校验器及元数据回执足以复现这份**有限盘点**。没有新增通用secret scanner或额外应用代码，因此不伪造新的RED→GREEN，也不重复整个已通过离线门禁。真正完整内容/许可/公开授权门禁继续保留，不以简短分类器缩小原A60要求。

本文件的写作和链接检查只是材料验收；原TS18/A60仍不完整。许可/权限不明时继续整理不受影响的本地求职与学习材料，保持不上传。
