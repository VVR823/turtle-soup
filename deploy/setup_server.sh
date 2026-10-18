#!/bin/bash
# 海龟汤 AI 主持人 — 服务器一键部署脚本
# 运行环境：Ubuntu 22.04 / Alibaba Cloud Linux 4（兼容 RHEL 9 的系统需手动把 apt 换成 dnf）
# 运行方式：sudo bash /opt/turtle-soup/backend/deploy/setup_server.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[部署]${NC} $1"; }
warn() { echo -e "${YELLOW}[注意]${NC} $1"; }
err() { echo -e "${RED}[错误]${NC} $1"; }

if [ "$(id -u)" -ne 0 ]; then
    err "请用 root 运行此脚本：sudo bash /opt/turtle-soup/backend/deploy/setup_server.sh"
    exit 1
fi

if [ ! -d "/opt/turtle-soup/backend" ] || [ ! -d "/opt/turtle-soup/frontend" ]; then
    err "请先上传项目文件到服务器："
    err "  /opt/turtle-soup/backend/    ← 本机 backend/ 文件夹"
    err "  /opt/turtle-soup/frontend/   ← 本机 .next/standalone/ 文件夹"
    exit 1
fi

# 1. 装系统依赖
log "安装系统依赖（nginx、python3、git、curl）..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y nginx python3 python3-venv python3-pip python-is-python3 curl git

# 2. 装 Node.js 22（运行 Next.js standalone 前端）
log "安装 Node.js 22..."
if ! command -v node &> /dev/null || [ "$(node -v | cut -d'v' -f2 | cut -d'.' -f1)" != "22" ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y nodejs
fi
log "Node 版本：$(node -v)"

# 3. 让用户填配置
echo ""
warn "下面请输入部署信息（输入时不会显示密码）："
read -rp "你的服务器公网地址（如 http://47.100.12.34 或 https://haiguitang.com）: " PUBLIC_URL
read -rp "硅基流动 API Key（sk-...）: " SF_KEY
read -rsp "访问口令（别人打开网站要输的密码，直接回车表示不设口令）: " SITE_PW
echo ""

if [ -z "$PUBLIC_URL" ]; then
    err "公网地址不能为空"; exit 1
fi
if [ -z "$SF_KEY" ]; then
    err "硅基流动 API Key 不能为空"; exit 1
fi

# 4. 配置 Python 后端
log "安装 Python 依赖..."
cd /opt/turtle-soup/backend
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

log "写入后端环境变量 .env..."
cat > .env <<EOF
LLM_PROVIDER=siliconflow
SILICONFLOW_API_KEY=${SF_KEY}
SILICONFLOW_MODEL=Qwen/Qwen2.5-7B-Instruct
CORS_ORIGINS=${PUBLIC_URL}
SITE_PASSWORD=${SITE_PW}
EOF

# 5. 创建 systemd 服务
log "创建后端服务..."
cat > /etc/systemd/system/turtle-backend.service <<EOF
[Unit]
Description=Turtle Soup Backend (FastAPI)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/turtle-soup/backend
ExecStart=/opt/turtle-soup/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

log "创建前端服务..."
cat > /etc/systemd/system/turtle-frontend.service <<EOF
[Unit]
Description=Turtle Soup Frontend (Next.js)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/turtle-soup/frontend
ExecStart=/usr/bin/node /opt/turtle-soup/frontend/server.js
Restart=always
RestartSec=3
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
EOF

# 6. 配置 nginx
log "配置 nginx..."
cat > /etc/nginx/sites-available/turtle-soup <<EOF
server {
    listen 80;
    server_name _;

    client_max_body_size 20M;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/turtle-soup /etc/nginx/sites-enabled/turtle-soup

nginx -t && systemctl restart nginx

# 7. 启动服务
log "启动海龟汤服务..."
systemctl daemon-reload
systemctl enable --now turtle-backend
systemctl enable --now turtle-frontend

sleep 3

# 8. 健康检查
log "检查服务状态..."
if systemctl is-active --quiet turtle-backend && systemctl is-active --quiet turtle-frontend; then
    echo ""
    log "✅ 部署完成！"
    log "网站地址：${PUBLIC_URL}"
    log "健康检查：${PUBLIC_URL}/api/health"
    log "口令检查：${PUBLIC_URL}/api/config"
    echo ""
    warn "常用命令："
    echo "  看后端正则日志：journalctl -u turtle-backend -f"
    echo "  看前端日志：    journalctl -u turtle-frontend -f"
    echo "  重启后端：      systemctl restart turtle-backend"
    echo "  重启前端：      systemctl restart turtle-frontend"
else
    err "服务启动异常，请查看日志："
    err "  journalctl -u turtle-backend -n 50"
    err "  journalctl -u turtle-frontend -n 50"
    exit 1
fi
