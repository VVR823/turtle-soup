# TS-04 实施状态

更新：2026-10-08（Asia/Shanghai）。状态：LOCAL_VERIFIED_WITH_CONCERNS，本地实施、独立审查与修复回归通过，外部门禁保留。

## 已实现的玩家保护

同一开局 requestId + 相同内容只建一局；改变内容返回 409。同一局的同一个问题请求只处理一次：进行中 202，结束后取回原安全响应及原剩余次数，失败也不会偷偷再调模型。同一文本使用新 ID 才表示玩家主动再次提问；旧客户端缺省 ID 仍兼容，但不声称旧客户端可自动重试幂等。

模型工作在数据库事务外；一局只有一轮预留。90 秒租约、随机 token、版本和终态共同检查迟到写入。答复、两条消息、扣次数、通关状态和可恢复响应一次提交；任何中途写入或提交故障全部回滚。提醒/模型失败不扣次数；通关记录 solved，揭晓不能覆盖成 given_up。

请求拥有独立取消信号。ASGI 观察到断开后停止后续模型尝试，保存 failed 响应；仍阻塞的实际模型任务继续占名额，直到真正清理。事务提交决策之后发生断网可能只是响应丢失，不能倒扣已提交次数，应按原 ID 恢复。不宣称供应商远端推理已经终止。

## 恢复接口

- POST /api/chat 保持旧 camelCase 字段，追加 requestId/turnId/kind/state。
- GET /api/session/{sessionId}/turns/{requestId} 查询本会话内请求，返回已保存状态/响应；不存在或其他会话的请求为 404。UUID 不是账户身份系统，不公开 session/request ID。
- POST /api/evaluate 拒绝与在途问答竞争；只保存一个结果和依据 hash，重复揭晓取回同一快照。
- GET /api/session/{id} 已结束也返回 200、status 与保存的 evaluation；旧的完整历史继续保留。已通关但尚未点击揭晓时 evaluation 可为 null，不凭空造评分。
- 旧迁移 turn 没有可核验响应时返回 legacy_result_unavailable，不制造成功重放。

## 验证与未验证

71 项 TS-04 定向测试（54 原阶段 + 17 独立审查永久回归）通过；加旧局兼容共 88 定向通过。当前完整门禁包含 TS-05 初步请求保护：442 pytest、7 Vitest、6 子进程回收、3 API-only Playwright，合计 458 passed / 9 skipped。真实运行目录 239 个文件 hash 前后均为 d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a；测试进程 104132 正常回收，typecheck 退出 0。

A11–A17 映射到开局/问答幂等、最后机会并发、事务故障回滚、旧局保留/恢复、终态与揭晓快照、到期迟到 fencing 和取消后不收费的离线证据。独立本地审查修复已完成，不签收外部门禁。ASGI 脚本化断开不是移动端真实断网实测；真实模型质量、浏览器 UI、云供应商收尾、跨 OS/远程 CI/生产迁移与发布均未验证。评分算法仍是旧确定性版本，TS-07 必须修正语义；已在快照入口排除免费/失败行，不把这一步称为完整评分正确性。

实施记录与已发现失败见 [TS-04 ledger](superpowers/plans/2026-10-07-ts04-progress.md)。确实无法决定的事项单列于 [自主实施进度](autonomous-progress.md)，不暂停无关工作。

审查修复：严格保存响应白名单与身份/状态/计数标记绑定、停用空旧局也能绕过的单条写接口、单连接读事务恢复一致快照；损坏 JSON 统一安全 503/code/requestId。永久用例 14 failed / 3 passed → 全通过，没有删除原历史或修改生产。未发布 evaluation v1 追加 session/puzzle/rule envelope；旧开发中间态无绑定 blob 明确拒绝，不作为生产兼容承诺。
