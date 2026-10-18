"""Observe ASGI protocol only; never read bodies/headers or decode responses."""
import re
from uuid import uuid4

from .audit_context import AttemptCollector, attempt_context
from .audit_events import ROUTE_TEMPLATES, UUID_PATTERN

_ROUTES = tuple((template, re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template)) + "$"))
    for template in sorted(ROUTE_TEMPLATES - {"unmatched"}, key=len, reverse=True))


def route_template(scope):
    route = getattr(scope.get("route"), "path", None)
    if route in ROUTE_TEMPLATES:
        return route
    # CORS/body guards stop before routing. Match only a registered shape;
    # the raw path is never returned, persisted, or used as an identity.
    path = scope.get("path", "")
    return next((template for template, pattern in _ROUTES if pattern.fullmatch(path)), "unmatched")


class AuditMiddleware:
    def __init__(self, app, store, *, testing=False):
        self.app, self.store, self.testing = app, store, testing

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        collector = AttemptCollector(str(uuid4()), traffic_class="test" if self.testing else "real")
        status, started, disconnected = None, False, False
        async def observed_receive():
            nonlocal disconnected
            message = await receive()  # Delegates to the existing single reader.
            if message["type"] == "http.disconnect":
                disconnected = True
            return message
        async def observed_send(message):
            nonlocal status, started
            await send(message)
            if message["type"] == "http.response.start":
                status, started = message.get("status"), True
        with attempt_context(collector):
            try:
                await self.app(scope, observed_receive, observed_send)
            finally:
                request_id = scope.get("request_id")
                if isinstance(request_id, str) and UUID_PATTERN.fullmatch(request_id):
                    collector.bind_ids(request_id=request_id)
                item = collector.finish(status_code=status, method=scope.get("method"),
                    route_template=route_template(scope), response_started=started, disconnected=disconnected)
                try:
                    await self.store.save_attempt(item)
                except Exception:
                    # The business may already have committed and headers may
                    # already be sent. Never replace/retry that answer.
                    self.store.note_failure(item.eventId)
