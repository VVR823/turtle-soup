# -*- coding: utf-8 -*-
"""织梦者特殊评分映射与彩蛋解锁（源自 tests/online/test_zhimengzhe_unlock.py）。

覆盖 6 个 checkpoint → 真实完成度 ~86% → special_scoring 映射后 ≥70% → 解锁 xinshijie。
"""
from .conftest import make_session


def test_zhimengzhe_unlock_xinshijie(client):
    sid = make_session(client, "zhimengzhe", level="tianyi")
    questions = [
        "催眠我的人是我妻子吗",   # 主角被妻子催眠
        "我妻子是催眠师吗",       # 妻子是催眠师
        "小珊是我情人吗",         # 小珊是情人
        "幽灵是真的幽灵吗",       # 幽灵不是真幽灵
        "星期一还是梦境吗",       # 一二梦境
        "星期三是妻子的视角吗",   # 星期三妻子视角
    ]
    for q in questions:
        d = client.post("/api/chat", json={"sessionId": sid, "question": q}).json()
        assert d.get("reply") in ("是", "不是", "是也不是", "算是", "与此无关"), f"{q} -> {d}"

    ev = client.post("/api/evaluate", json={"sessionId": sid}).json()
    assert ev.get("unlockSoupId") == "xinshijie", f"应解锁 xinshijie，实际: {ev.get('unlockSoupId')}"
