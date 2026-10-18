"""ASGI disconnect must persist noncharged failure while real owner stays held."""
import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app import db
from app.config import Settings
from app.main import create_app
from app.model_gateway import ModelFailure
from app.runtime import runtime_context
from app.schemas import Soup
from app.audit_events import AuditEvent
from .test_model_gateway import ScriptedTransport, gateway


def test_request_cancellation_stops_waiting_and_retries_but_retains_blocked_owner():
    entered, release, cancellation = Event(), Event(), Event()
    transport = ScriptedTransport(['{"answer":"是","reasoning":"synthetic"}'],
                                  before_return=lambda: (entered.set(), release.wait(timeout=2)))
    runner = gateway(transport, max_active=1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner.invoke, [], deadline=time.monotonic() + 1, cancelled=cancellation)
        try:
            assert entered.wait(timeout=1)
            cancellation.set()
            with pytest.raises(ModelFailure, match="model_cancelled"):
                future.result(timeout=0.5)
            assert runner.snapshot()["active"] == 1
            assert transport.cancel_requested.is_set()
            assert len(transport.calls) == 1
        finally:
            release.set()
            runner.close(wait_seconds=1)
    assert runner.snapshot()["active"] == 0


def test_asgi_disconnect_persists_failure_and_late_answer_cannot_charge(tmp_path):
    entered, release = Event(), Event()

    def ignored_cancel(_):
        entered.set()
        assert release.wait(timeout=3)
        return AIMessage(content='{"answer":"是","reasoning":"synthetic"}')

    soup = Soup(id="synthetic", title="Synthetic", surface="Surface", bottom="Synthetic private truth")
    app = create_app(Settings.for_test(tmp_path), model=RunnableLambda(ignored_cancel), soups=[soup])
    with TestClient(app) as client:
        sid = client.post("/api/chat", json={"soupId": soup.id}).json()["sessionId"]
        request_id = str(uuid4())

        async def disconnected_call():
            raw = json.dumps({"sessionId": sid, "question": "他是凶手吗？", "requestId": request_id}).encode()
            first, disconnected = True, False

            async def receive():
                nonlocal first, disconnected
                if first:
                    first = False
                    return {"type": "http.request", "body": raw, "more_body": False}
                assert await asyncio.to_thread(entered.wait, 1)
                disconnected = True
                return {"type": "http.disconnect"}

            responses = []

            async def send(message):
                responses.append(message)

            scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                     "method": "POST", "scheme": "http", "path": "/api/chat", "raw_path": b"/api/chat",
                     "query_string": b"", "root_path": "", "headers": [(b"content-type", b"application/json")],
                     "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 80)}
            await asyncio.wait_for(app(scope, receive, send), timeout=1)
            assert disconnected
            assert next(m for m in responses if m["type"] == "http.response.start")["status"] == 503

        try:
            asyncio.run(disconnected_call())
            with runtime_context(app.state.runtime):
                replay = db.get_turn_response(sid, request_id)
                assert replay.state == "failed" and replay.safeResponse["code"] == "model_cancelled"
                assert db.get_session(sid)["questionsAsked"] == 0
                assert app.state.runtime.get_model_gateway().snapshot()["active"] == 1
                conn = db._connect()
                try:
                    saved = conn.execute("SELECT details_json FROM audit_events WHERE event_type='http_attempt' AND request_id=?", (request_id,)).fetchall()
                    assert len(saved) == 1
                    event = AuditEvent.model_validate_json(saved[0][0])
                    assert event.details.disconnected and event.details.outcome == "disconnected"
                    assert event.details.charged is False and event.details.reasonCode == "model_cancelled"
                    assert event.details.modelCalls[0].status == "started"
                    sealed = saved[0][0]
                finally:
                    conn.close()
        finally:
            release.set()
            app.state.runtime.get_model_gateway().close(wait_seconds=1)
        with runtime_context(app.state.runtime):
            assert db.get_session(sid)["questionsAsked"] == 0
            assert db.get_turn_response(sid, request_id).state == "failed"
            conn = db._connect()
            try:
                assert conn.execute("SELECT details_json FROM audit_events WHERE id=?", (event.eventId,)).fetchone()[0] == sealed
            finally:
                conn.close()
