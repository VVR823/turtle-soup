# -*- coding: utf-8 -*-
"""织梦者 QA 回归（17 题，源自 tests/online/test_zhimengzhe_qa.py）。

织梦者主持人对"是"类有时回复"……是"（如"嗯，是"），故启用 loose_is。
"""
import pytest

from .conftest import run_qa

SOUP_ID = "zhimengzhe"

QA = [
    ("我是不是被催眠了", "是也不是"),
    ("幽灵是真的幽灵吗", "不是"),
    ("幽灵是催眠我的人吗", "是"),
    ("小珊是我女友吗", "不是"),
    ("是我情人吗", "是"),
    ("催眠我的人是我妻子吗", "是"),
    ("小珊死了吗", "不是"),
    ("我从催眠中被解除了吗", "是也不是"),
    ("星期二还是梦境吗", "是"),
    ("是不是这些天全是梦境", "不是"),
    ("星期三不是梦境 对吗", "是"),
    ("我妻子是催眠师吗", "是"),
    ("我要杀的人是妻子吗", "不是"),
    ("星期三是妻子的视角吗", "是"),
    ("星期二是不是也是妻子的视角", "不是"),
    ("男的是不是醒不过来了", "是"),
    ("丈夫是催眠师吗", "不是"),
]


@pytest.mark.real_model
def test_zhimengzhe_full_qa(client):
    hard, _ = run_qa(client, SOUP_ID, QA, loose_is=True)
    assert not hard, f"硬错误 {len(hard)} 个: {hard[:5]}"
