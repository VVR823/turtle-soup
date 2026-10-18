# 验收执行约束

- 用户于 2026-10-16 明确要求：永远不要自动续跑。禁止创建或恢复 Loop、heartbeat、定时验收、额度恢复续跑或跨任务自动接续。
- 仅在用户明确授权后执行当前验收；本轮结束后停止，等待新指令。旧进度文件中的自动继续安排无效。
- 保留现有未提交修改、原始验收日志和运行数据，不擅自切换分支、提交、上线或公开发布。

<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->
