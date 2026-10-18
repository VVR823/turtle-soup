"""Independent-review regressions, using isolated API/runtime ownership only."""
from contextlib import closing
import asyncio

import pytest

from app import db
from app.model_gateway import ModelFailure
from app.runtime import Runtime, runtime_context


@pytest.mark.parametrize("body", [
    '{"soupId":"xin","question":"synthetic-private-question?","question":null}',
    '{"soupId":"xin","soupId":"xin"}',
    '{"soupId":"xin","requestId":null,"requestId":null}',
])
def test_duplicate_json_fields_are_rejected_before_any_game_is_created(client, application, body):
    with runtime_context(application.state.runtime), closing(db._connect()) as conn, conn:
        before = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    response = client.post("/api/chat", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json()["code"] == "request_validation_error"
    assert "synthetic-private-question" not in response.text
    with runtime_context(application.state.runtime), closing(db._connect()) as conn, conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == before


def test_runtime_rejects_first_gateway_creation_after_shutdown_has_started(runtime):
    # Pausing an actual teardown await exposes the former unlocked check/close gap.
    active = Runtime(runtime.settings, model=runtime.model)

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        class OwnedAsyncClient:
            async def aclose(self):
                entered.set()
                await release.wait()

        active.http_async_client = OwnedAsyncClient()
        closing = asyncio.create_task(active.aclose())
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            with pytest.raises(ModelFailure, match="model_unavailable"):
                active.get_model_gateway()
        finally:
            release.set()
            await closing
            if active.model_gateway is not None:
                active.model_gateway.close(wait_seconds=0.1)
        assert active.closed is True

    asyncio.run(exercise())
