#!/bin/bash
# 海龟汤服务器一键部署（由 _push.py 替换占位符后上传执行）
set -e
export DEBIAN_FRONTEND=noninteractive

echo "== 1. 安装系统依赖 =="
apt-get update -y
apt-get install -y curl ca-certificates gnupg
# Node.js 20（Next 16 standalone 需要较新 Node）
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y python3 python3-venv python3-pip nodejs nginx
echo "node: $(node --version)  npm: $(npm --version)"

echo "== 2. 解压前端 =="
mkdir -p /opt/turtle-soup/frontend
rm -rf /opt/turtle-soup/frontend/*
tar xzf /tmp/frontend.tgz -C /opt/turtle-soup/frontend
ls /opt/turtle-soup/frontend

echo "== 3. 解压后端 =="
mkdir -p /opt/turtle-soup/backend
tar xzf /tmp/backend.tgz -C /opt/turtle-soup/backend
ls /opt/turtle-soup/backend

echo "== 4. 写后端 .env =="
cat > /opt/turtle-soup/backend/.env <<'ENVEOF'
LLM_PROVIDER=siliconflow
SILICONFLOW_API_KEY=__SF_KEY__
SILICONFLOW_MODEL=__SF_MODEL__
CORS_ORIGINS=http://__SERVER_IP__,http://localhost:3000
SITE_PASSWORD=__SITE_PW__
ENVEOF
echo ".env 已写入"

echo "== 5. 建 venv 装依赖 =="
cd /opt/turtle-soup/backend
python3 -m venv venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q
echo "依赖安装完成"

echo "== 6. systemd: backend =="
cat > /etc/systemd/system/turtle-backend.service <<'EOF'
[Unit]
Description=Turtle Soup Backend (FastAPI)
After=network.target
[Service]
WorkingDirectory=/opt/turtle-soup/backend
ExecStart=/opt/turtle-soup/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
Restart=always
User=root
[Install]
WantedBy=multi-user.target
EOF

echo "== 7. systemd: frontend =="
cat > /etc/systemd/system/turtle-frontend.service <<'EOF'
[Unit]
Description=Turtle Soup Frontend (Next standalone)
After=network.target
[Service]
WorkingDirectory=/opt/turtle-soup/frontend
ExecStart=/usr/bin/node /opt/turtle-soup/frontend/server.js
Environment=HOSTNAME=0.0.0.0
Environment=PORT=3000
Restart=always
User=root
[Install]
WantedBy=multi-user.target
EOF

echo "== 8. nginx 反代 =="
cat > /etc/nginx/sites-available/turtle <<'EOF'
server {
  listen 80 default_server;
  server_name _;
  client_max_body_size 10m;
  location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }
  location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }
}
EOF
ln -sf /etc/nginx/sites-available/turtle /etc/nginx/sites-enabled/turtle
rm -f /etc/nginx/sites-enabled/default
nginx -t

echo "== 9. 启动服务 =="
systemctl daemon-reload
systemctl enable turtle-backend turtle-frontend
systemctl restart turtle-backend turtle-frontend
systemctl restart nginx
sleep 3
systemctl status turtle-backend --no-pager | head -5
systemctl status turtle-frontend --no-pager | head -5
echo "SETUP_DONE"
