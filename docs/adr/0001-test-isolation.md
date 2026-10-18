# ADR 0001：为什么把运行状态放到应用实例中

状态：TS-01 已实现，远程 CI 与跨平台矩阵尚待验证。

## 问题

原来导入后端模块就可能加载个人配置、运行题库、初始化真实数据库并创建共享 HTTP transport。一次测试也可能修改玩家数据、使用真实模型，或因旧 `.venv` 的失效解释器完全跑不起来。全局题库、口令、缓存和限流器还会让两个应用实例互相影响。

## 方案

把配置加载和存储初始化移到应用生命周期；请求通过 ContextVar 找到所属 Runtime。保留现有 API 和业务函数，不在第一步同时重写游戏判定和数据库 schema。

```text
create_app(Settings, injected model/catalog)
    └─ startup → Runtime → isolated DATA_DIR + catalog + limiter + transports
          ├─ request A → copied context → sync handler → Runtime A
          └─ request B → copied context → sync handler → Runtime B
    └─ shutdown → close owned HTTP clients → clear owned caches
```

pytest 在收集模块前安装文件/网络防误用保护，普通 fixture 使用每个测试自己的 tmp_path。合成模型不读取标答：这样“测试全绿”只证明程序契约，不会冒充模型准确率。

## Windows 退出流程

本机 venv 的 python.exe 会启动实际解释器，杀掉 launcher 不一定让服务退出；最初的测试服务因此残留。现在 runner 保持到 Python 的 stdin 管道，测试成功、失败或父进程退出时的 EOF 都通知实际服务正常 shutdown。测试入口等待服务退出后才返回，端口占用时拒绝启动而不是接管别人的服务。

## 取舍

- ContextVar + 兼容 config.NAME/db.SOUPS 让现有代码改动较小，但依赖更隐式；后续模块可逐步采用显式注入。
- 旧 CLI 不再靠 import 建库，首次显式 CRUD 惰性初始化，以保留嵌入调用兼容性；显式读取动态配置/题库仍可能触发 I/O，不能把这些操作当成纯 import。
- 内存缓存与限流器是单应用/单进程状态，不能因此宣称多 worker 共享一致或解决并发计数问题。
- Python monkeypatch 比系统沙箱轻量、免费、易于跨平台测试，但防不了任意恶意 native/subprocess。用有限的可信测试代码和默认无凭据配置补足边界。
- 安装依赖仍需网络或完整缓存；“测试离线”不等于“从未联网下载依赖”。

独立临时进程而不拆 Runtime 仍会保留导入时副作用；单靠 monkeypatch 路径也无法处理第二个应用的口令、缓存和题库。因此同时采用工厂、实例状态和测试护栏。

接口细节见 [参考](../test-runtime.md)，实际复现见 [How to](../testing.md)，尚未完成的验收见 [状态](../ts01-status.md)。
