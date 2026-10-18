"""Isolated app fixtures. No real settings/app import at collection time."""
import asyncio
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

collect_ignore = ["online"]


@pytest.fixture(autouse=True)
def runtime(tmp_path, request):
    from app.config import Settings, load_settings
    from app.runtime import Runtime, runtime_context
    from app.testing import FakeModel

    if request.node.get_closest_marker("real_model") and request.config.getoption("--real-model"):
        settings = replace(
            load_settings(load_env=False), DATA_DIR=tmp_path,
            TESTING=True, LOAD_RUNTIME_PUZZLES=False, ALLOW_REAL_MODEL=True,
            RATE_LIMIT_ENABLED=False, ENABLE_TRACE=False,
        )
        model = None
    else:
        settings = Settings.for_test(tmp_path)
        model = FakeModel()
    active = Runtime(settings, model=model)
    with runtime_context(active):
        yield active
    asyncio.run(active.aclose())


@pytest.fixture
def application(runtime):
    from app.main import create_app
    return create_app(runtime.settings, model=runtime.model)


@pytest.fixture
def client(application):
    with TestClient(application) as test_client:
        yield test_client

def make_session(client: TestClient, soup_id: str, level: str = "tianyi") -> str:
    """创建一局游戏会话，返回 sessionId。"""
    r = client.post("/api/chat", json={"soupId": soup_id, "level": level})
    assert r.status_code == 200, r.text
    return r.json()["sessionId"]


def run_qa(client: TestClient, soup_id: str, qa: list[tuple[str, str]], level: str = "tianyi", loose_is: bool = False) -> tuple[list[tuple], list[tuple]]:
    """把问答对逐题打到 /api/chat，返回硬错误列表 [(序号, 问题, 实际, 期望), ...]。

    期望含"不重要"（SOFT 类，原测试只打印人工看）不计入硬错误。
    提问次数用尽时自动开新会话续测。
    loose_is 仅兼容原调用签名，不再放宽五类答案相等性。
    """
    sid = make_session(client, soup_id, level)
    hard: list[tuple] = []
    soft: list[tuple] = []
    for i, (q, exp) in enumerate(qa, 1):
        r = client.post("/api/chat", json={"sessionId": sid, "question": q})
        assert r.status_code == 200, r.text
        d = r.json()
        reply = d.get("reply", "")
        exp_clean = exp.replace(" 不重要", "").strip()
        if exp_clean == "不重要":
            soft.append((i, q, reply, exp))
            continue
        ok = reply == exp_clean
        if not ok:
            hard.append((i, q, reply, exp))
        if d.get("limitReached"):
            sid = make_session(client, soup_id, level)
    return hard, soft
