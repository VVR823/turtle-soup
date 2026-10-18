"""Defense-in-depth for pytest, including collection-time I/O.

Not an OS sandbox. Native extensions/subprocesses need separate controls.
Loopback is permitted only for ports bound by this test process, including
Windows asyncio's socketpair implementation, never arbitrary local services.
"""
import builtins
import io
import ipaddress
import os
import re
import socket
import sqlite3
from pathlib import Path
from threading import RLock
from urllib.parse import unquote, urlsplit
from weakref import WeakKeyDictionary
from app.paths import canonical_path


class TestAccessBlocked(RuntimeError):
    __test__ = False


class NetworkGuard:
    def __init__(self):
        self.bindings = WeakKeyDictionary()
        self.lock = RLock()

    def check_address(self, sock, address):
        if sock.family == getattr(socket, "AF_UNIX", object()):
            with self.lock:
                owned = any(
                    owner.fileno() != -1 and owner.family == sock.family
                    and owner.type == sock.type and binding == os.fsencode(address)
                    for owner, binding in self.bindings.items()
                )
            if not owned:
                raise TestAccessBlocked("Only test-owned Unix sockets are allowed")
            return
        if not isinstance(address, tuple) or len(address) < 2:
            raise TestAccessBlocked("Network access is disabled in offline tests")
        host, port = address[:2]
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == "localhost"
        # Resolve aliases rather than treating every loopback IP as interchangeable.
        hosts = [host]
        if host == "localhost":
            hosts = [result[4][0] for result in self.resolve(host, port, sock.family, sock.type)]
        with self.lock:
            owned = bool(hosts) and all(
                any(
                    owner.fileno() != -1 and owner.family == sock.family
                    and owner.type == sock.type and binding == (resolved_host, port)
                    for owner, binding in self.bindings.items()
                ) for resolved_host in hosts
            )
        if not local or not owned:
            raise TestAccessBlocked("Only test-owned loopback ports are allowed")

    def install(self, monkeypatch):
        original_bind = socket.socket.bind
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_sendto = socket.socket.sendto
        original_resolve = socket.getaddrinfo
        self.resolve = original_resolve

        def bind(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                try:
                    local = ipaddress.ip_address(address[0]).is_loopback
                except ValueError:
                    local = address[0] == "localhost"
                if not local:
                    raise TestAccessBlocked("Offline tests may only bind loopback interfaces")
            result = original_bind(sock, address)
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                actual = sock.getsockname()
                if ipaddress.ip_address(actual[0]).is_loopback:
                    with self.lock:
                        self.bindings[sock] = actual[:2]
            elif sock.family == getattr(socket, "AF_UNIX", object()):
                with self.lock:
                    self.bindings[sock] = os.fsencode(sock.getsockname())
            return result

        def connect(sock, address):
            self.check_address(sock, address)
            return original_connect(sock, address)

        def connect_ex(sock, address):
            self.check_address(sock, address)
            return original_connect_ex(sock, address)

        def sendto(sock, data, *args):
            self.check_address(sock, args[-1])
            return original_sendto(sock, data, *args)

        def resolve(host, port, *args, **kwargs):
            if host is not None:
                try:
                    local = ipaddress.ip_address(host).is_loopback
                except ValueError:
                    local = host == "localhost"
                if not local:
                    raise TestAccessBlocked("External DNS is disabled in offline tests")
            return original_resolve(host, port, *args, **kwargs)

        monkeypatch.setattr(socket.socket, "bind", bind)
        monkeypatch.setattr(socket.socket, "connect", connect)
        monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
        monkeypatch.setattr(socket.socket, "sendto", sendto)
        monkeypatch.setattr(socket, "getaddrinfo", resolve)
        if hasattr(socket.socket, "sendmsg"):
            original_sendmsg = socket.socket.sendmsg

            def sendmsg(sock, buffers, ancdata=(), flags=0, address=None):
                if address is not None:
                    self.check_address(sock, address)
                return original_sendmsg(sock, buffers, ancdata, flags, address)

            monkeypatch.setattr(socket.socket, "sendmsg", sendmsg)


def protect_runtime_files(monkeypatch, project_root: Path):
    """Forbid content access to real dotenv/runtime paths before collection."""
    protected_dirs = (project_root / "backend" / "data", project_root / "data")
    protected_files = (
        project_root / ".env", project_root / ".env.local",
        project_root / "backend" / ".env",
    )
    # Preserve both the named entry and its resolved target (symlinks/junctions).
    protected_dirs = tuple({canonical_path(p, resolve=False) for p in protected_dirs} | {canonical_path(p) for p in protected_dirs})
    protected_files = tuple({canonical_path(p, resolve=False) for p in protected_files} | {canonical_path(p) for p in protected_files})

    def check(path):
        if isinstance(path, int):
            return
        raw = os.fsdecode(path)
        if raw == ":memory:":
            return
        if raw.startswith("file:"):
            uri = urlsplit(raw)
            raw = unquote(uri.path)
            if uri.netloc and uri.netloc != "localhost":
                raw = f"//{uri.netloc}{raw}"
            if os.name == "nt":
                # pathlib doesn't interpret /D:/... as a drive path on Windows.
                raw = re.sub(r"^/+([A-Za-z]:[/\\])", r"\1", raw)
        paths = (canonical_path(raw, resolve=False), canonical_path(raw))
        if any(
            candidate in protected_files or any(
                candidate == parent or candidate.is_relative_to(parent)
                for parent in protected_dirs
            ) for candidate in paths
        ):
            raise TestAccessBlocked("Real configuration/runtime data is forbidden in tests")

    def wrap(original, keyword):
        def guarded(*args, **kwargs):
            if args:
                check(args[0])
            elif keyword in kwargs:
                check(kwargs[keyword])
            return original(*args, **kwargs)
        return guarded

    monkeypatch.setattr(builtins, "open", wrap(builtins.open, "file"))
    monkeypatch.setattr(io, "open", wrap(io.open, "file"))
    monkeypatch.setattr(os, "open", wrap(os.open, "path"))
    monkeypatch.setattr(sqlite3, "connect", wrap(sqlite3.connect, "database"))


def validate_basetemp(path: Path, project_root: Path) -> Path:
    """Reject destructive pytest temp targets before tmp_path can clean them."""
    allowed = canonical_path(project_root) / ".cache" / "pytest"
    if canonical_path(allowed) != allowed:
        raise ValueError("pytest cache must not redirect through a symlink/junction")
    resolved = canonical_path(path)
    if resolved == allowed or not resolved.is_relative_to(allowed):
        raise ValueError("--basetemp must be a dedicated child of .cache/pytest")
    if resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir())):
        raise ValueError("--basetemp must be new or empty; pytest deletes its contents")
    return resolved
