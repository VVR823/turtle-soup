# -*- coding: utf-8 -*-
"""织梦者特殊评分映射与彩蛋解锁（源自 tests/online/test_zhimengzhe_unlock.py）。

模拟正确回答覆盖要点 → 当前 special_scoring 门槛解锁；
模拟无关回答不能解锁。这是状态/评分集成证据，不是真实模型准确率。
严格评分和移除虚高映射仍由 TS-07 完成。
"""
import pytest

from .conftest import make_session


@pytest.mark.parametrize("scripted_answer,expected_unlock", [("是", "xinshijie"), ("与此无关", None)])
def test_zhimengzhe_unlock_xinshijie(client, scripted_answer, expected_unlock):
    # Script the transport explicitly: conservative rules now defer narrator
    # references with history to the model instead of unsafe regex shortcuts.
    client.app.state.runtime.model.answer = scripted_answer
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
    assert ev.get("unlockSoupId") == expected_unlock
