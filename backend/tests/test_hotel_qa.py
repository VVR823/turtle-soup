# -*- coding: utf-8 -*-
"""旅馆汤 QA 回归（10 题，源自 test_hotel_qa.py）。"""
import pytest

from .conftest import run_qa

SOUP_ID = "hotel"

QA = [
    ("故事中只存在一个死人吗", "是"),
    ("故事中存在凶手吗", "不是"),
    ("女孩的亲吻是在向我传递一种信号吗", "不是"),
    ("女孩和大叔的关系正常吗", "是"),
    ("故事中除了我 中年妇女 孩子 老太太  女孩 大叔 警察以外还有其他人吗", "不是"),
    ("是孩子造成其他人死亡的吗", "是"),
    ("120房间的人和其他房间的人相关吗", "不是"),
    ("120房间的女孩是死者吗", "不是"),
    ("旅馆真的是旅馆吗", "不是"),
    ("这些是不是我在弥留之际发生的事情", "是"),
]


@pytest.mark.real_model
def test_hotel_full_qa(client):
    hard, _ = run_qa(client, SOUP_ID, QA)
    assert not hard, f"硬错误 {len(hard)} 个: {hard[:5]}"
