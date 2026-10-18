# 历史退役资料：旧服务器部署指南

> **禁止按下文执行当前版本上线。** 本页与旧deploy覆盖脚本只保留历史来源，不是新的部署runbook。整目录上传、root密码、HTTP对外、未经测量的“2核2G够用”与“内存不超过1G”没有当前验证依据；不得用这些旧步骤覆盖真实数据或触发生产迁移/重启。当前只授权LOCAL升级，没有执行生产操作。
>
> 请使用[本地隔离发布与恢复指南](../docs/howto-local-release.md)，其中生产阻断项必须另行授权、逐项实证核验。以下正文仅为旧版历史，不要复制运行。

## 你需要什么

- 一台阿里云轻量应用服务器（2 核 2G 就够）
- 系统镜像：**Ubuntu 22.04**
- 服务器的 **公网 IP** 和 **root 密码**
- 智谱 GLM-4-Flash API Key（已经申请好的）

## 部署原理（一句话）

- **后端**：Python FastAPI 跑在服务器本机 `127.0.0.1:8000`
- **前端**：Next.js 独立包跑在服务器本机 `127.0.0.1:3000`
- **nginx**：把用户访问的 `http://你的IP/` 分给前端，`http://你的IP/api/` 分给后端
- 对外只暴露 80 端口，朋友和面试官直接访问 IP 就能玩

## 第一步：本机准备上传文件

1. 确保本机已经跑过 `npm run build`（我已经帮你构建好了 `.next/standalone`）。
2. 把本机的两个文件夹上传到服务器：

| 本机路径 | 服务器路径 |
|---|---|
| `backend/` | `/opt/turtle-soup/backend/` |
| `.next/standalone/` | `/opt/turtle-soup/frontend/` |

上传工具推荐（Windows）：
- **WinSCP**（免费、图形界面、像 FTP 一样拖拽）
- **MobaXterm**（自带 SFTP 文件管理）

> 上传前注意：可以删掉 `backend/.env`，脚本运行时会重新询问你并生成新的生产环境配置。

## 第二步：SSH 连上服务器，运行一键脚本

```bash
# 用 root 登录后执行
sudo bash /opt/turtle-soup/backend/deploy/setup_server.sh
```

脚本会依次问你三个问题：
1. **公网地址**：填 `http://47.xxx.xxx.xxx`（就是你的服务器 IP，注意前面加 `http://`）
2. **智谱 GLM-4-Flash API Key**：填你的 `sk-...`
3. **访问口令**：设一个密码（别人打开网站要先输这个才能玩）；直接回车就是不设口令

等它跑完，会提示「部署完成」，并给出网站地址。

## 第三步：验证

用浏览器打开 `http://你的IP/`：
- 能看到海龟汤首页 → 前端 OK
- 能进游戏、AI 能回答 → 后端 + 智谱 GLM-4-Flash OK
- 如果设了口令，会先弹锁屏，输对才能玩

## 如果以后加新汤

流程不变：
1. 在本机改好 `backend/app/soups.py`，测试通过。
2. 用 WinSCP 重新上传 `backend/` 到 `/opt/turtle-soup/backend/`（覆盖即可）。
3. SSH 执行 `systemctl restart turtle-backend`。

前端代码如果也改了，需要在本机重新 `npm run build`，再上传 `.next/standalone/` 到 `/opt/turtle-soup/frontend/`，然后 `systemctl restart turtle-frontend`。

## 常见问题

**Q：买服务器时选的 Alibaba Cloud Linux 行不行？**  
A：建议换成 **Ubuntu 22.04**。本脚本用 `apt` 安装软件；Alibaba Cloud Linux 用 `dnf`，需要你自己改脚本里的包管理器命令。

**Q：怎么买域名、怎么上 HTTPS？**  
A：不买域名也能用 IP 访问。想买域名的话，去阿里云买个 `.cn`（约 ¥30–80/年），解析到服务器 IP，然后把脚本里问的「公网地址」改成 `https://你的域名`，再配个 SSL 证书（可以用 `certbot` 免费申请 Let's Encrypt）。

**Q：服务器 2 核 2G 够吗？**  
A：对海龟汤这种小流量项目完全够。前端 + 后端 + nginx 同时跑，内存占用一般不超过 1G。
