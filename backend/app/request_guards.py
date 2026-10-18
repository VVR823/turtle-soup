"""Bounded ASGI input and program-owned independent access credentials."""
import hmac
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class GuardFailure(HTTPException):
    def __init__(self, status_code, code, detail):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def _matches(provided, configured):
    return isinstance(provided, str) and hmac.compare_digest(provided.encode("utf-8"), configured.encode("utf-8"))


def require_site_token(provided, settings):
    if settings.SITE_PASSWORD and not _matches(provided, settings.SITE_PASSWORD):
        raise GuardFailure(401, "site_token_required", "需要正确的访问口令。")


def require_admin_token(provided, settings):
    if not settings.ADMIN_TOKEN:
        raise GuardFailure(503, "admin_not_configured", "管理口令未配置，管理功能不可用。")
    if not _matches(provided, settings.ADMIN_TOKEN):
        raise GuardFailure(401, "admin_token_required", "需要正确的管理口令。")


class BodyLimitMiddleware:
    """Collect at most one bounded body before any route side effect.

    The upstream request-lifecycle receive observer remains the only reader of
    the real ASGI receive. After forwarding the preserved body once, downstream
    receives still observe the original queue/disconnect, not invented silence.
    """

    def __init__(self, app, *, max_bytes=32768):
        if type(max_bytes) is not int or not 1 <= max_bytes <= 32768:
            raise ValueError("Body bound must be 1..32768 bytes")
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, scope, receive, send, status, code):
        detail = "请求体太大，请缩短输入后再试。" if status == 413 else "请求体格式不符合要求。"
        headers = {"Cache-Control": "no-store"} if scope.get("path") in {
            "/api/metrics/admin", "/api/metrics/admin/export"} else None
        await JSONResponse({"detail": detail, "code": code, "requestId": str(uuid4())},
                           status_code=status, headers=headers)(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = [value for key, value in scope.get("headers", ()) if key.lower() == b"content-length"]
        expected = None
        if declared:
            try:
                if len(declared) != 1:
                    raise ValueError("Ambiguous body size")
                value = declared[0].decode("ascii").strip()
                if not value.isdecimal():
                    raise ValueError("Invalid body size")
                expected = int(value)
            except (ValueError, UnicodeError):
                await self._reject(scope, receive, send, 400, "request_body_invalid")
                return
            if expected > self.max_bytes:
                await self._reject(scope, receive, send, 413, "request_body_too_large")
                return
        chunks, total = [], 0
        while True:
            message = await receive()
            if message["type"] != "http.request" or not isinstance(message.get("body", b""), bytes):
                await self._reject(scope, receive, send, 400, "request_body_invalid")
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                await self._reject(scope, receive, send, 413, "request_body_too_large")
                return
            # Empty intermediate ASGI frames grant no data but must not grow
            # retained fragment/join metadata without a byte-limit boundary.
            if chunk:
                chunks.append(chunk)
            if not message.get("more_body", False):
                break
        if expected is not None and expected != total:
            await self._reject(scope, receive, send, 400, "request_body_invalid")
            return
        delivered = False
        body = b"".join(chunks)

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
