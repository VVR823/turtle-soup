# -*- coding: utf-8 -*-
"""pytest 公共配置：限流关闭 + TestClient + 会话工厂。

注意：必须在 import app 之前把 RATE_LIMIT_ENABLED 设为 0，
否则 QA 回归（每套几十题连续请求）会触发每 IP 限流 429。
"""
import os
import sys

os.environ["RATE_LIMIT_ENABLED"] = "0"

# 让 pytest 能 import app 包（backend/ 目录）
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

# 线上验证脚本（直接打真实服务器，需部署后手动跑），pytest 不收集
collect_ignore = ["online"]


@pytest.fixture(scope="session")
def client() -> TestClient:
    """FastAPI TestClient：走完整请求链路（路由/校验/会话存储），无需起服务器。"""
    return TestClient(app)


def make_session(client: TestClient, soup_id: str, level: str = "tianyi") -> str:
    """创建一局游戏会话，返回 sessionId。"""
    r = client.post("/api/chat", json={"soupId": soup_id, "level": level})
    assert r.status_code == 200, r.text
    return r.json()["sessionId"]


def run_qa(client: TestClient, soup_id: str, qa: list[tuple[str, str]], level: str = "tianyi", loose_is: bool = False) -> list[tuple]:
    """把问答对逐题打到 /api/chat，返回硬错误列表 [(序号, 问题, 实际, 期望), ...]。

    期望含"不重要"（SOFT 类，原测试只打印人工看）不计入硬错误。
    提问次数用尽时自动开新会话续测。
    loose_is=True：期望为"是"时，回复以"是"开头也算通过（织梦者有时回复"……是"）。
    """
    sid = make_session(client, soup_id, level)
    hard: list[tuple] = []
    soft: list[tuple] = []
    for i, (q, exp) in enumerate(qa, 1):
        r = client.post("/api/chat", json={"sessionId": sid, "question": q})
        d = r.json()
        reply = d.get("reply", "")
        exp_clean = exp.replace(" 不重要", "").strip()
        if exp_clean == "不重要":
            soft.append((i, q, reply, exp))
            continue
        ok = reply == exp_clean or (loose_is and exp_clean == "是" and reply.startswith("是"))
        if not ok:
            hard.append((i, q, reply, exp))
        if d.get("limitReached"):
            sid = make_session(client, soup_id, level)
    return hard, soft
