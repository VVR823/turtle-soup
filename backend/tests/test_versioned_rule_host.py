"""Owned r1 overlay is exact, cache-isolated and subordinate to game flow."""
from uuid import uuid4

import pytest

from app import ai_host, baselines, db
from app.schemas import ChatRequest, HostVersions, Soup
from .test_rule_publication import prepare, publisher
from .test_rule_snapshots import rule_storage


def loaded(request, result):
    from app.rule_contract import read_rule_snapshot
    conn = db._connect()
    try:
        return (baselines.session_soup(conn, request.changeDraft.puzzleVersion),
            read_rule_snapshot(conn, request.changeDraft.puzzleVersion, result.ruleVersion),
            HostVersions(puzzleVersion=request.changeDraft.puzzleVersion, ruleVersion=result.ruleVersion))
    finally:
        conn.close()


def test_overlay_answers_only_full_exact_key_and_old_r1_remains_old(rule_storage):
    request = prepare(); result = publisher(request).publish(request); soup, rules, versions = loaded(request, result)
    old = HostVersions(puzzleVersion=versions.puzzleVersion, ruleVersion=request.expectedRuleVersion)
    assert ai_host.handle_host_response(soup, [], "小明是凶手吗？", versions=old).answer == "不是"
    new = ai_host.handle_host_response(soup, [], "小明是凶手吗?", versions=versions, rule_snapshot=rules)
    assert new.answer == "是" and new.contextIndependent and new.evidenceIds == request.changeDraft.factIds
    assert new.matchedCheckpoint.startswith("rule1:") and rule_storage.model.calls == []
    # Semantically similar text must not inherit this exact patch.
    similar = ai_host.handle_host_response(soup, [], "小明是凶手？", versions=versions, rule_snapshot=rules)
    assert similar.answer == "不是"


def test_cache_keys_do_not_mix_before_after_replacement(rule_storage):
    first = prepare(); r1 = publisher(first).publish(first); soup, rules, versions = loaded(first, r1)
    one = ai_host.handle_host_response(soup, [], first.changeDraft.question, versions=versions, rule_snapshot=rules)
    assert one.answer == "是" and not one.cacheHit
    assert ai_host.handle_host_response(soup, [], first.changeDraft.question, versions=versions, rule_snapshot=rules).cacheHit
    second = prepare(answer="算是"); r2 = publisher(second).publish(second); _, rules2, versions2 = loaded(second, r2)
    assert ai_host.handle_host_response(soup, [], first.changeDraft.question, versions=versions2, rule_snapshot=rules2).answer == "算是"
    assert ai_host.handle_host_response(soup, [], first.changeDraft.question, versions=versions, rule_snapshot=rules).answer == "是"
    assert rule_storage.model.calls == []


@pytest.mark.parametrize("change", [
    {"soupId": "foreign"}, {"ruleVersion": "r1:" + "e" * 64}, {"puzzleVersion": "p1:" + "e" * 64},
    {"exactRules": ()}, {"releaseRulesJson": "{}"}, {"releaseManifestJson": "{}"},
])
def test_forged_snapshot_refused_even_on_existing_cache_hit(rule_storage, change):
    request = prepare(); result = publisher(request).publish(request); soup, rules, versions = loaded(request, result)
    ai_host.handle_host_response(soup, [], request.changeDraft.question, versions=versions, rule_snapshot=rules)
    with pytest.raises(baselines.SnapshotError):
        ai_host.handle_host_response(soup, [], request.changeDraft.question, versions=versions,
            rule_snapshot=rules.model_copy(update=change))
    assert rule_storage.model.calls == []


def test_game_service_supplies_new_overlay_without_rewriting_old_game(rule_storage):
    from app.game_service import ask
    old = db.create_game_once("synthetic", None, str(uuid4()))
    request = prepare(); result = publisher(request).publish(request)
    new = db.create_game_once("synthetic", None, str(uuid4()))
    old_reply = ask(ChatRequest(sessionId=old["sessionId"], soupId="synthetic", question=request.changeDraft.question))
    new_reply = ask(ChatRequest(sessionId=new["sessionId"], soupId="synthetic", question=request.changeDraft.question))
    assert old_reply.safeResponse["reply"] == "不是" and new_reply.safeResponse["reply"] == "是"
    assert db.get_session(old["sessionId"])["ruleVersion"] == request.expectedRuleVersion
    assert db.get_session(new["sessionId"])["ruleVersion"] == result.ruleVersion and rule_storage.model.calls == []


def test_win_and_progress_flow_keep_priority_over_overlay(runtime):
    runtime.soups = [Soup(id="synthetic", title="T", surface="S", bottom="小明是凶手。",
        confusionPoints=[{"q": "小明是凶手吗？", "a": "不是"}],
        win_condition={"must_include": ["凶手"], "message": "Synthetic win"})]
    db.initialize()
    request = prepare(); result = publisher(request).publish(request); soup, rules, versions = loaded(request, result)
    win = ai_host.handle_host_response(soup, [], request.changeDraft.question, versions=versions, rule_snapshot=rules)
    assert win.kind == "win" and win.reply == "Synthetic win"
    progress = ai_host.handle_host_response(soup, [], "还缺哪些线索？", versions=versions, rule_snapshot=rules)
    assert progress.kind == "reminder" and not progress.chargeable and runtime.model.calls == []


def test_overlay_cannot_be_overridden_by_cache_seeded_without_snapshot(rule_storage):
    request = prepare(); result = publisher(request).publish(request); soup, rules, versions = loaded(request, result)
    assert ai_host.handle_host_response(soup, [], request.changeDraft.question, versions=versions).answer == "不是"
    answer = ai_host.handle_host_response(soup, [], request.changeDraft.question, versions=versions, rule_snapshot=rules)
    assert answer.answer == "是" and not answer.cacheHit
