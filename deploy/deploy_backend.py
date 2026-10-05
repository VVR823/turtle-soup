#!/usr/bin/env python3
"""只部署后端指定文件并重启 turtle-backend。

用法:
  python deploy/deploy_backend.py --password <服务器root密码> --file backend/app/ai_host.py
"""
import argparse
import os
import posixpath
import sys

import paramiko


def run_cmd(ssh, cmd: str):
    print(f"$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        print("  out:", out)
    if err:
        print("  err:", err)
    return exit_code, out, err


def main() -> None:
    p = argparse.ArgumentParser(description="部署后端文件并重启服务")
    p.add_argument("--host", default="47.97.33.174")
    p.add_argument("--port", type=int, default=22)
    p.add_argument("--user", default="root")
    p.add_argument("--password", required=True)
    p.add_argument("--file", required=True, help="本地后端文件路径，如 backend/app/ai_host.py")
    p.add_argument("--remote-backend-dir", default="/opt/turtle-soup/backend")
    args = p.parse_args()

    if not os.path.exists(args.file):
        print(f"❌ 找不到后端文件: {args.file}")
        sys.exit(1)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"🔌 连接 {args.user}@{args.host}:{args.port} ...")
    try:
        ssh.connect(args.host, port=args.port, username=args.user, password=args.password, timeout=30)
    except Exception as e:
        print(f"❌ SSH 连接失败: {e}")
        sys.exit(1)

    sftp = ssh.open_sftp()
    # 支持相对路径（backend/app/xxx.py）或绝对路径（D:/.../backend/app/xxx.py）
    abs_file = os.path.abspath(args.file).replace("\\", "/")
    if "/backend/" in abs_file:
        rel_in_backend = abs_file.split("/backend/", 1)[1]
    else:
        rel_in_backend = os.path.basename(abs_file)
    remote_file = posixpath.join(args.remote_backend_dir, rel_in_backend)
    print(f"⬆️  {args.file} -> {remote_file}")
    sftp.put(args.file, remote_file)
    sftp.close()

    print("\n🔄 重启 turtle-backend ...")
    code, out, _ = run_cmd(ssh, "systemctl restart turtle-backend && sleep 2 && systemctl is-active turtle-backend")
    ssh.close()

    if code == 0 and out == "active":
        print("✅ turtle-backend 部署成功且状态 active")
    else:
        print(f"⚠️  turtle-backend 状态异常: {out or 'unknown'} (exit {code})")
        sys.exit(1)


if __name__ == "__main__":
    main()
