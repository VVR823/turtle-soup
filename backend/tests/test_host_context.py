"""A bounded prompt is not a deletion of the user's stored game history."""
import pytest


def history(count):
    return [message for number in range(count) for message in (
        {"role": "user", "content": f"synthetic-question-{number}?"},
        {"role": "host", "content": "是"},
    )]


def test_last_twelve_complete_turns_only_and_original_history_unchanged():
    from app.host_context import build_context
    records = history(13)
    original = [dict(record) for record in records]
    window = build_context(system_prompt="system", facts_prompt="facts-v1", question="question?", history=records)
    assert window.turns_included == 12
    assert "synthetic-question-0?" not in window.user
    assert "synthetic-question-1?" in window.user
    assert "synthetic-question-12?" in window.user
    assert window.user.endswith("question?")
    assert records == original
    assert window.input_chars == len(window.system) + len(window.user)
    assert window.policy_version == "context-v1"


def test_free_error_incomplete_and_unknown_answer_pairs_are_not_valid_context():
    from app.host_context import build_context
    records = [
        {"role": "user", "content": "free?", "isFreeReminder": True},
        {"role": "host", "content": "reminder", "isFreeReminder": True},
        {"role": "user", "content": "error?", "kind": "system_error"},
        {"role": "host", "content": "service-error", "kind": "system_error"},
        {"role": "user", "content": "unknown?"},
        {"role": "host", "content": "不知道"},
        *history(1), {"role": "user", "content": "incomplete?"},
    ]
    window = build_context(system_prompt="system", facts_prompt="facts-v1", question="new?", history=records)
    assert window.turns_included == 1
    for excluded in ("free?", "error?", "unknown?", "incomplete?", "不知道", "service-error"):
        assert excluded not in window.user


def test_budget_drops_whole_oldest_turns_not_fixed_facts_or_half_turns():
    from app.host_context import build_context
    records = history(3)
    full = build_context(system_prompt="system", facts_prompt="private-facts-v1", question="new?", history=records)
    limited = build_context(system_prompt="system", facts_prompt="private-facts-v1", question="new?",
                            history=records, max_chars=full.input_chars - 1)
    assert limited.turns_included == 2
    assert "synthetic-question-0?" not in limited.user
    assert "synthetic-question-1?" in limited.user
    assert "private-facts-v1" in limited.user
    assert limited.system == "system"
    assert limited.input_chars < full.input_chars


def test_fixed_content_exceeding_budget_is_explicit_not_silent_fact_truncation():
    from app.host_context import ContextLimitError, build_context
    with pytest.raises(ContextLimitError):
        build_context(system_prompt="system", facts_prompt="F" * 8000, question="new?", history=[])


def test_exact_eight_thousand_boundary_is_allowed():
    from app.host_context import build_context
    empty = build_context(system_prompt="system", facts_prompt="facts", question="new?", history=[])
    padding = 8000 - empty.input_chars
    window = build_context(system_prompt="system", facts_prompt="facts" + "F" * padding,
                           question="new?", history=[])
    assert window.input_chars == 8000
