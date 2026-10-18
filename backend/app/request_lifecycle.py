"""Request-owned cooperative cancellation, including ASGI disconnect events."""
import asyncio
from contextvars import ContextVar
from threading import Event

_cancelled: ContextVar[Event | None] = ContextVar("turtle_soup_request_cancelled", default=None)


def cancellation_signal():
    return _cancelled.get()


async def run_request(app, scope, receive, send):
    if scope["type"] != "http" or scope.get("path") != "/api/chat" or scope.get("method") != "POST":
        await app(scope, receive, send)
        return
    signal = Event()
    token = _cancelled.set(signal)
    # One consumer of the underlying ASGI receive; bounded forwarding avoids
    # competing reads between request.body() and the disconnect observer.
    messages = asyncio.Queue(maxsize=1)

    async def observe():
        try:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    signal.set()
                    await messages.put(message)
                    return
                await messages.put(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            signal.set()
            await messages.put({"type": "http.disconnect"})

    observer = asyncio.create_task(observe())
    try:
        await app(scope, messages.get, send)
    finally:
        signal.set()
        observer.cancel()
        try:
            await observer
        except asyncio.CancelledError:
            pass
        _cancelled.reset(token)
