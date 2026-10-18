"""Exact identity must not collapse negation/entities/numbers/conditions.

Changing to old extract_core/normalize_question would fail these literal pairs.
This module depends on no live app/runtime and uses only synthetic text.
"""
import importlib.util

import pytest


def normalize(text):
    assert importlib.util.find_spec("app.question_normalization") is not None, "Missing conservative exact-key function"
    from app.question_normalization import normalize_exact_question
    return normalize_exact_question(text)


@pytest.mark.parametrize("text,expected", [
    (" 小明是凶手？ ", "小明是凶手"),
    ("小明是凶手??？", "小明是凶手"),
    (" 小明\t是\n 凶手吗？", "小明 是 凶手吗"),
    ("Cafe\u0301 是店名吗?", "Café 是店名吗"),
    (" 小明是凶手。 ", "小明是凶手。"),
])
def test_only_explicit_unicode_whitespace_and_terminal_marks_normalize(text, expected):
    assert normalize(text) == expected
    assert normalize(expected) == expected


@pytest.mark.parametrize("left,right", [
    ("小明是凶手吗？", "小明不是凶手吗？"),
    ("小明是凶手吗？", "小红是凶手吗？"),
    ("故事里有3人吗？", "故事里有4人吗？"),
    ("故事里有3人吗？", "故事里有３人吗？"),
    ("2004年死了吗？", "2006年死了吗？"),
    ("只有他死了吗？", "他死了吗？"),
    ("如果他离开了，小明会死吗？", "小明会死吗？"),
    ("小明是凶手吗？", "小明是凶手吗。"),
    ("是凶手，不是警察吗？", "是凶手不是警察吗？"),
    ("ID-A存在吗？", "id-a存在吗？"),
    ("他死了吗？", "小明死了吗？"),
    ("A?B是人吗？", "AB是人吗？"),
])
def test_business_meaning_changes_never_share_one_exact_key(left, right):
    assert normalize(left) != normalize(right)


@pytest.mark.parametrize("text", ["", " \n\t ", "？??", None, 1, b"synthetic"])
def test_empty_or_nontext_cannot_masquerade_as_a_valid_question_key(text):
    with pytest.raises(ValueError):
        normalize(text)
