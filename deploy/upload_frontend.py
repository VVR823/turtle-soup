#!/usr/bin/env python3
"""上传前端 standalone 包到服务器并重启 turtle-frontend 服务。

用法:
  python deploy/upload_frontend.py --password <服务器root密码>

可选参数:
  --host        服务器IP (默认 47.97.33.174)
  --port        SSH端口 (默认 22)
  --user        SSH用户 (默认 root)
  --tarball     本地 tarball 路径 (默认 frontend-new.tar.gz)
  --remote-dir  服务器前端目录 (默认 /opt/turtle-soup/frontend)

流程:
  1. SSH 连上服务器，先把旧前端备份成 <remote-dir>_bak
  2. SFTP 上传 tarball 到 /tmp/frontend-new.tar.gz
  3. 在 remote-dir 内解压覆盖，并 systemctl restart turtle-frontend
  4. 校验服务状态为 active
"""
import argparse
import os
import sys

import paramiko


def main() -> None:
    p = argparse.ArgumentParser(description="上传前端 standalone 并重启服务")
    p.add_argument("--host", default="47.97.33.174")
    p.add_argument("--port", type=int, default=22)
    p.add_argument("--user", default="root")
    p.add_argument("--password", default=None, help="服务器 root 密码（无 key 时必填）")
    p.add_argument("--key", default=None, help="SSH 私钥路径(Ed25519)；默认尝试 C:/Users/HP/.ssh/turtle_deploy")
    p.add_argument("--tarball", default="frontend-new.tar.gz")
    p.add_argument("--remote-dir", default="/opt/turtle-soup/frontend")
    args = p.parse_args()

    # 登录凭据：优先用 key，否则用 password
    _KEY_DEFAULT = r"C:/Users/HP/.ssh/turtle_deploy"
    key_path = args.key or (_KEY_DEFAULT if os.path.exists(_KEY_DEFAULT) else None)
    if key_path and os.path.exists(key_path):
        try:
            _conn = {"pkey": paramiko.Ed25519Key.from_private_key_file(key_path)}
        except Exception as e:
            print(f"⚠️  读取私钥失败({key_path}): {e}，尝试密码登录")
            _conn = None
    else:
        _conn = None
    if not _conn:
        if not args.password:
            print("❌ 未找到可用私钥且未提供 --password，无法登录")
            sys.exit(1)
        _conn = {"password": args.password}

    if not os.path.exists(args.tarball):
        print(f"❌ 找不到本地 tarball: {args.tarball}")
        sys.exit(1)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"🔌 连接 {args.user}@{args.host}:{args.port} ...")
    try:
        ssh.connect(
            args.host,
            port=args.port,
            username=args.user,
            timeout=30,
            **_conn,
        )
    except Exception as e:
        print(f"❌ SSH 连接失败: {e}")
        sys.exit(1)

    # 1. 备份旧前端
    backup = f"{args.remote_dir}_bak"
    print("📦 备份旧前端 ...")
    _, stdout, _ = ssh.exec_command(
        f"rm -rf {backup}; cp -r {args.remote_dir} {backup} 2>/dev/null; mkdir -p {args.remote_dir}"
    )
    stdout.channel.recv_exit_status()

    # 2. 上传 tarball
    remote_tar = "/tmp/frontend-new.tar.gz"
    print(f"⬆️  上传 {args.tarball} -> {remote_tar} ...")
    sftp = ssh.open_sftp()
    sftp.put(args.tarball, remote_tar)
    sftp.close()

    # 3. 解压 + 重启
    print("📂 解压并重启 turtle-frontend ...")
    cmd = (
        f"cd {args.remote_dir} && tar -xzf {remote_tar} && rm -f {remote_tar} && "
        f"systemctl restart turtle-frontend && sleep 2 && systemctl is-active turtle-frontend"
    )
    stdin, stdout, stderr = ssh.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    print("STDOUT:", out)
    if err:
        print("STDERR:", err)
    ssh.close()

    if exit_code == 0 and out == "active":
        print("✅ 部署成功，turtle-frontend 状态: active")
    else:
        print(f"⚠️  部署命令退出码 {exit_code}，服务状态: {out or '未知'}")
        sys.exit(1)


if __name__ == "__main__":
    main()
