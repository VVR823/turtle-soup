# A20 当前本地管理边界：拒绝矩阵已验证

2026-10-15。针对原A20的“无/错管理员凭据、站点凭据不能替代管理员、缺配置关闭管理”做补齐验收。只说明当前本地应用，不认证生产反向代理、服务器文件权限或所有业务内容安全。

## 实际结果

固定声明清单20个管理操作，与当前生成OpenAPI操作清单精确相等，再逐条调用真实ASGI：

- 已配独立管理凭据：20操作×无凭据/普通站点凭据/错管理凭据，60项全部401/admin_token_required。
- 未配管理凭据：20操作×无凭据/普通站点凭据，40项全部503/admin_not_configured。
- 每次均检查合成业务表行数保持不变、FakeModel调用0，拒绝内容不回显测试管理凭据；两个自有临时合成库正常关闭/清理后才生成成功回执。

包含反馈列表/approve/reject/privacy及禁用的旧merge入口、审计list/status/recover、统计page/export、Agent list/start/status/cancel、候选detail/approve/reject/publish/rollback、发布后观察操作。端点清单新增/缺失会失败，不能静默缩减。

成功命令：固定现有venv-ts01解释器 `-I -B .cache/a46/original-a20-http-matrix.py`，实际native d355d6退出0。100项是本次独立验收检查，不是新增100条永久pytest，也不与3515项完整回归相加。

[回执](../.cache/a46/original-a20-http-matrix.json) SHA256 1984fe99d5c6d44fdeedd21cdad3e70bc96138bbc5aff697bad4391828f076ec；
[探针](../.cache/a46/original-a20-http-matrix.py) SHA256 cab4fbacca9393c70a17cd822a263ee503a3c07e86cc0a02d9a7c5dfc557251a。

## 断言的准确边界

POST使用空JSON，验证鉴权在业务/请求实体执行之前拒绝；不把它宣传成所有有效业务请求、发布质量或管理员正常操作已覆盖。已有候选HTTP37项中的18个实际有效业务拒绝组合另验证业务值不变，真实approve/publish/rollback及幂等也另有既有测试；见[逐模块映射](acceptance-a18-a20.md)。

“行数不变”不是“逐字段完全不变”的替代词。新矩阵只声明前者；后者依赖相应现有状态测试。未配置时管理关闭包含本次全部20操作，不再只靠共用guard或抽样GET推断。

当前生成HTTP清单没有命名为Trace的端点；源码搜索未见应用StaticFiles/目录mount或Trace读取路由。trace_logger仅在运行时私有DATA_DIR/traces下写入，开关关闭时直接返回。本轮只读源码，不读任何真实Trace文件。这证明当前应用没有声明/挂载原始Trace的HTTP读取面，不证明生产Web服务器、文件系统或未来隐藏路由安全。

## 问题总结与自我修正

探针首次直接uv脚本因固定backend导入路径缺失而未执行；之后改用与完整测试相同的venv-ts01隔离解释器。当前FastAPI app.routes为惰性IncludedRouter，不能误筛APIRoute；改用公开生成清单并以实际ASGI验证。应用正确拒绝空汤目录，故改为明确单条合成种子，未放松迁移约束。探针自身只读SQLite的with事务并不关闭连接，Windows清理失败；改用contextlib.closing，不忽略清理异常。这些启动/探针失败都不是已通过矩阵或应用权限漏洞。

失败时没有生成成功回执；没有把框架兼容错误冒充产品RED或另改已验收应用代码。留存的残余自有合成缓存不当作真实数据或成功证据，不扩大删除范围。

## 保护与签收范围

当前398源身份55462476961a9a33cca6fba244bc89b8d44a5c357ab0c1e04e7ddb046f16fc32，逐文件零漂移；未修改应用源码/永久测试，不需重跑同字节完整门禁或再派审查者。
[原239/Git保护回执](../.cache/d18/a20-admin-matrix-after-protection.json)与原运行摘要d9662e98…、HEAD/index完全一致，没有生产迁移、部署、公开、付费或真实模型调用。

本地A20三个拒绝/配置断言现有直接行为证据。原验收清单未擅自追改勾选，其他A01-A60/18阶段/C24/IR24/OV+SG不自动通过；下一项接续A21实际本地调用/在线等待/后台上限及生命周期断言映射。
