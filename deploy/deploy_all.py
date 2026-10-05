#!/usr/bin/env python3
"""同时部署后端代码变更 + 前端 standalone 包，并重启两个服务。

用法:
  python deploy/deploy_all.py --password <服务器root密码>

可选:
  --host           服务器IP（默认 47.97.33.174）
  --backend-files  需要上传的后端文件，空格分隔（默认 backend/app/schemas.py backend/app/main.py）
  --remote-backend-dir  服务器后端目录（默认 /opt/turtle-soup/backend）
  --remote-frontend-dir 服务器前端目录（默认 /opt/turtle-soup/frontend）
  --tarball        本地前端包路径（默认 frontend-new.tar.gz）

流程:
  1. SSH 连接服务器
  2. 上传指定后端文件到 /opt/turtle-soup/backend/app/
  3. systemctl restart turtle-backend → 校验 active
  4. 备份旧前端 → 上传 tarball → 解压覆盖 /opt/turtle-soup/frontend/
  5. systemctl restart turtle-frontend → 校验 active
"""
import argparse
import os
import posixpath
import sys

import paramiko


def upload_file(sftp, local: str, remote: str) -> None:
    print(f"⬆️  {local} -> {remote}")
    sftp.put(local, remote)


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
    p = argparse.ArgumentParser(description="部署后端 + 前端并重启服务")
    p.add_argument("--host", default="47.97.33.174")
    p.add_argument("--port", type=int, default=22)
    p.add_argument("--user", default="root")
    p.add_argument("--password", required=True)
    p.add_argument(
        "--backend-files",
        nargs="+",
        default=["backend/app/schemas.py", "backend/app/main.py"],
    )
    p.add_argument("--remote-backend-dir", default="/opt/turtle-soup/backend")
    p.add_argument("--remote-frontend-dir", default="/opt/turtle-soup/frontend")
    p.add_argument("--tarball", default="frontend-new.tar.gz")
    args = p.parse_args()

    if not os.path.exists(args.tarball):
        print(f"❌ 找不到前端 tarball: {args.tarball}")
        sys.exit(1)
    for f in args.backend_files:
        if not os.path.exists(f):
            print(f"❌ 找不到后端文件: {f}")
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

    # 1. 上传后端文件
    print("\n📦 上传后端文件 ...")
    for local_file in args.backend_files:
        remote_file = posixpath.join(args.remote_backend_dir, local_file.replace("backend/", "", 1))
        upload_file(sftp, local_file, remote_file)

    # 2. 重启后端
    print("\n🔄 重启 turtle-backend ...")
    code, out, _ = run_cmd(ssh, "systemctl restart turtle-backend && sleep 2 && systemctl is-active turtle-backend")
    if code != 0 or out != "active":
        print("⚠️  turtle-backend 未正常启动")
        sftp.close()
        ssh.close()
        sys.exit(1)
    print("✅ turtle-backend active")

    # 3. 备份旧前端
    print("\n📦 备份旧前端 ...")
    backup = f"{args.remote_frontend_dir}_bak"
    run_cmd(ssh, f"rm -rf {backup}; cp -r {args.remote_frontend_dir} {backup} 2>/dev/null; mkdir -p {args.remote_frontend_dir}")

    # 4. 上传前端 tarball
    remote_tar = "/tmp/frontend-new.tar.gz"
    upload_file(sftp, args.tarball, remote_tar)
    sftp.close()

    # 5. 解压 + 重启前端
    print("\n🔄 解压并重启 turtle-frontend ...")
    cmd = (
        f"cd {args.remote_frontend_dir} && tar -xzf {remote_tar} && rm -f {remote_tar} && "
        f"systemctl restart turtle-frontend && sleep 2 && systemctl is-active turtle-frontend"
    )
    code, out, _ = run_cmd(ssh, cmd)
    ssh.close()

    if code == 0 and out == "active":
        print("\n✅ 全部部署成功：turtle-backend & turtle-frontend 均为 active")
    else:
        print(f"\n⚠️  前端服务状态异常: {out or 'unknown'} (exit {code})")
        sys.exit(1)


if __name__ == "__main__":
    main()
