# A01 本地干净检出与锁定安装验证计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 按既有连续执行授权直接实施，不请求阶段确认。

**Goal:** 证明当前许可源码的本地验证快照可经真实 Git checkout，在没有依赖目录和私有运行数据的目录按锁文件建立环境；准确保留未验收范围。

**Architecture:** 主仓库只读；在其已忽略的 .cache/a01 下创建独立 seed 仓库及无硬链接的本地 clone。seed 的唯一生成提交标记为 validation snapshot，逐文件绑定当前400文件及必要构建/静态资源输入；不冒称原仓库已提交、远程或公开 clone。新环境不链接或复制主仓库 node_modules/venv。

**Tech Stack:** Git 2.53.0、Node22.17.0/npm10.9.2、uv0.12.3、基础Python3.13.13；版本均再次记录。

**Spec:** D:/CODE/turtle-soup-audit/TurtleSoup_秋招升级验收清单_2026-10-06.md A01；原实施计划TS01；当前README/docs/testing锁定安装步骤。

## Global Constraints

- 原239运行文件、主HEAD/index和用户修改不变；不复制任何真实 .env、backend/data、根data、私有holdout、依赖目录或原Git目录。
- 当前400文件摘要 f9e13b9879bd11ebabf2b5d9330cdbb6411ef6dcace3bb929dc99c29e3b663ee；额外输入单列来源/SHA。
- 零新增付费；不发布、上传、部署、迁移生产；仅本地loopback/FakeModel测试，npm lifecycle安装脚本/遥测/审计上传禁用；Python本地editable构建实际执行，见审查处置。
- 先离线锁定安装；如缺缓存准确记录缺失，不猜安装成功。任何免费依赖下载另按正式权限执行，保持锁文件不变。
- 不用新快照覆盖现有仓库/备份；新输出独占，失败输出保留。不用平台配置或未运行矩阵冒称通过。

## Review Focus

- 快照遗漏tsconfig/postcss/public或被测试读取的README/部署文本：建立显式补充清单，再逐文件对比checkout。
- symlink/junction/path traversal将真实数据引入快照：仅规范相对路径、逐段lstat拒绝链接、明确禁止目录。
- Git过滤器/换行导致代码漂移：禁外部/全局配置、自动换行和钩子，checkout后逐文件校验。
- 安装悄悄复用主依赖或真实配置：起始无node_modules/venv；使用独立路径和清洁环境，记录实际安装清单与模块来源。
- 新环境能安装但不能运行：依次验证前端测试/类型及后端隔离设置、必要owned启动；完整统一入口如运行则保留真实结果，未运行不签收。

## Task 1: 快照、安装与运行证据

**Files:** 缓存验证工具/生成证据仅 .cache/a01；本计划及同名progress；最终更新acceptance-a01-a12/current audit，不改应用或锁文件。

**Interfaces:** 输入400源清单、原安装指南、额外许可构建输入；输出seed提交、clean checkout身份、每步实际exit、依赖版本、运行证据与保留的限制。

- [x] 读取并检查所需额外输入及测试的源码文件依赖；核原Git/data保护和 .cache 忽略。
- [x] 生成许可清单和本地seed提交；本地clone/check out，确认所有许可文件字节相同、无依赖/私有运行目录，Git status干净。
- [x] 用uv --locked及npm ci --ignore-scripts先离线建立独立环境；记录版本、锁文件前后SHA及实际安装清单。Node两项缺缓存经官方请求补齐后，最终npm ci --offline成功；不称空缓存全程离线。
- [x] 在checkout中按指南执行适当验证和owned启动，检查依赖/源码来自checkout；失败先定位，禁用真实外部服务仍生效。实际50Python/399前端/103进程/3API通过，类型0；3040仅收集/2平台skip。
- [x] 只读自审与独立限定审查结束，更新A01实际证明与残留依赖，核主仓库/原数据保护；不因本地快照签远程CI/生产/公开/跨OS。

## Rulings

- 不创建改变主仓库Git注册的worktree：当前是用户已有特性分支、无附加worktree，HEAD不包含已批准工作树。使用独立缓存验证仓库进行真正checkout，并明确它的来源；代价是不能把验证提交称为用户仓库已提交或远程可克隆。
- 用户已明确无需阶段确认；执行方式沿用inline。此计划不扩大生产/付费/公开权限。
