#!/bin/bash
set -e
echo "== 修正 backend 目录结构 =="
if [ -d /opt/turtle-soup/backend/backend ]; then
  cd /opt/turtle-soup/backend/backend
  cp -a . /opt/turtle-soup/backend/
  cd /opt/turtle-soup/backend
  rm -rf backend
fi
echo "backend 内容:"; ls /opt/turtle-soup/backend

echo "== venv + pip 安装后端依赖 =="
cd /opt/turtle-soup/backend
python3 -m venv venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q
echo "pip 完成"

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

systemctl daemon-reload
systemctl enable turtle-backend turtle-frontend
systemctl restart turtle-backend turtle-frontend
systemctl restart nginx
sleep 4
echo "=== backend:"; systemctl is-active turtle-backend
echo "=== frontend:"; systemctl is-active turtle-frontend
echo "=== nginx:"; systemctl is-active nginx
echo "FINISH_DONE"
