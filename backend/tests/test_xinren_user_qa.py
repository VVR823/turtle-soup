# -*- coding: utf-8 -*-
"""「新人」用户补充 QA（18 题，源自 tests/online/test_xinren_user_qa.py）。"""
import pytest

from .conftest import run_qa

SOUP_ID = "xinren"

QA = [
    ("是不是凶杀案", "不是"),
    ("他们俩是同时在台上", "是"),
    ("他俩是不是有人快死了", "是"),
    ("是冥婚吗", "不是"),
    ("新人是新婚夫妻吗", "是"),
    ("他们俩是不是遭到什么胁迫了", "是"),
    ("这是婚礼吗", "不是"),
    ("他俩是不是行动不便", "是"),
    ("台下的人是坏人吗", "不重要"),
    ("这是现代发生的事吗", "不是"),
    ("是祭祀或者仪式吗", "不是"),
    ("这事合法吗", "不是"),
    ("他们是不是都是人类", "是"),
    ("台下的人和他俩认识吗", "不是"),
    ("台下的人是参观他们吗", "是"),
    ("他们是没有手或者脚吗", "是"),
    ("是人彘吗", "是"),
    ("这是一场畸形秀吗", "是"),
]


@pytest.mark.real_model
def test_xinren_user_full_qa(client):
    hard, _ = run_qa(client, SOUP_ID, QA)
    assert not hard, f"硬错误 {len(hard)} 个: {hard[:5]}"
