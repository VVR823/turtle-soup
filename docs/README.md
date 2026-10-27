# 技术文档

从项目使用、实现原理和上线维护三个方向阅读。项目介绍见 [首页](../README.md)，面试演示见 [展示指南](showcase.md)。

## 运行与测试

- [安装、完整离线验证及定向测试](testing.md)
- [后端启动、配置与接口](../backend/README.md)
- [测试运行时与数据隔离](test-runtime.md)

## 核心实现

- [对局恢复：请求编号、重试与事务](game-recovery.md)
- [请求审计](request-audit.md)
- [反馈与规则版本](feedback-rules.md)
- [修复 Agent 工具](agent-tools-reference.md)与 [执行循环](agent-loop-reference.md)
- [候选审核、发布与回滚](candidate-review-reference.md)
- [评测数据](evaluation-data.md)与 [评测运行器](evaluation-runner.md)
- [管理统计说明](metrics-explanation.md)

## 发布与维护

- [2026-10-25 发布记录](deployment-2026-10-25.md)与 [修复记录](repair-2026-10-25.md)
- [隔离发布与恢复指南](howto-local-release.md)
- [数据迁移](migrations.md)与 [版本恢复](release-recovery.md)
- [仓库同步与清理记录](repository-maintenance-2026-10-27.md)

## 项目展示与学习

- [简历稿](../RESUME.md)、[实现证据](resume-evidence.md)、[演示顺序](showcase.md)
- [学习路线](learning/project-learning-map.md)、[模块卡片](learning/core-module-cards.md)、[练习清单](learning/practice-checklist.md)

阶段计划、早期状态和旧稿统一从 [历史归档](archive/README.md)进入。历史文档保留当时的状态，判断当前功能时结合源码与最近发布记录。
