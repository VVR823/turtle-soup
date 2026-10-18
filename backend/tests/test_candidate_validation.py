"""Real frozen source and rules, synthetic context authority, no model oracle."""
import json
from uuid import uuid4

import pytest

from app import baselines, db
from app.host_evidence import build_evidence_catalog
from app.rule_contract import read_rule_snapshot, exact_targets_from_source
from app.schemas import Soup
from app.task_context import TaskContext, ScopedFact
from app.feedback_contract import SanitizedInput
from .test_rule_snapshots import rule_storage
from .test_repair_contracts import draft_body


def scope(soup=None):
    conn = db._connect()
    try:
        if soup is not None:
            conn.execute("DELETE FROM runtime_meta WHERE key='active_baseline'")
            baselines.store_baseline(conn, [soup]); conn.commit()
        active = baselines.active_manifest(conn); p1 = active["puzzleVersions"]["synthetic"]
        soup = baselines.session_soup(conn, p1); r1 = active["ruleVersion"]
        snapshot = read_rule_snapshot(conn, p1, r1)
        input = SanitizedInput(question="小明是凶手吗？", hostAnswer="不是", expectedClaim="是")
        facts = tuple(ScopedFact(id=f.id, soupId=f.soupId, puzzleVersion=f.puzzleVersion,
            sourcePath=f.sourcePath, category=f.category, payload=f.payload) for f in build_evidence_catalog(soup, p1))
        context = TaskContext(feedbackId=str(uuid4()), sourceFeedbackVersion=2, turnId=str(uuid4()),
            soupId=soup.id, observedPuzzleVersion=p1, observedRuleVersion=r1, baseRuleVersion=r1,
            sanitizedInput=input, inputDigest=baselines.digest(input.model_dump(mode="json")),
            allowedTools=("find_rule_conflicts", "run_regression", "save_candidate_rule"), factScope=facts)
        rules, _ = baselines._rule_release(conn, r1)
        targets = exact_targets_from_source(soup, p1, r1, rules, "小明是凶手吗？")
        body = draft_body(soupId=soup.id, puzzleVersion=p1, baseRuleVersion=r1, factIds=[facts[0].id],
            operation="replace", targetRuleDigest=targets[0].targetRuleDigest if len(targets) == 1 else "d" * 64)
        return context, soup, snapshot, body
    finally:
        conn.close()


def inspect(source, **changes):
    from app.agents.contracts import checked_draft
    from app.agents.validation import validate_candidate
    context, soup, snapshot, body = source
    draft = checked_draft(json.dumps({**body, **changes}))
    return validate_candidate(draft, context=context, soup=soup, rule_snapshot=snapshot)


def test_opposite_corrected_answer_can_replace_unique_wrong_old_rule_pending_human(rule_storage):
    result = inspect(scope())
    assert result.status == "reviewable_replace" and len(result.targets) == 1
    assert result.answerSupported is None and result.contextIndependentConfirmed is None
    assert rule_storage.model.calls == []


@pytest.mark.parametrize("answer,status", [("不是", "duplicate"), ("是", "conflict"), ("算是", "conflict")])
def test_add_cannot_overwrite_same_or_opposite_existing_answer(rule_storage, answer, status):
    result = inspect(scope(), operation="add", targetRuleDigest=None, answer=answer)
    assert result.status == status


@pytest.mark.parametrize("question", ["小明不是凶手吗？", "小王是凶手吗？", "故事里有2个人吗？", "如果下雨，小明是凶手吗？"])
def test_replace_target_cannot_transfer_to_opposite_subject_count_or_condition(rule_storage, question):
    result = inspect(scope(), question=question)
    assert result.status == "needs_human"


def test_changed_target_digest_is_not_authorized_by_same_question(rule_storage):
    assert inspect(scope(), targetRuleDigest="f" * 64).status == "needs_human"


@pytest.mark.parametrize("field,value", [("soupId", "foreign"), ("puzzleVersion", "p1:" + "e" * 64),
    ("baseRuleVersion", "r1:" + "e" * 64), ("factIds", ["f1:" + "e" * 64])])
def test_foreign_soup_version_or_fact_id_refuses_before_conflict_decision(rule_storage, field, value):
    from app.agents.contracts import AgentError
    with pytest.raises(AgentError): inspect(scope(), **{field: value})


@pytest.mark.parametrize("question", ["他死了吗？", "我死了吗？", "刚才那个人是凶手吗？"])
def test_same_pronoun_cannot_become_context_independent_exact_rule(rule_storage, question):
    result = inspect(scope(), operation="add", targetRuleDigest=None, question=question)
    assert result.status == "needs_human" and result.contextIndependentConfirmed is None


def test_real_fact_id_does_not_certify_an_uncovered_arbitrary_wrong_claim(rule_storage):
    result = inspect(scope(), operation="add", targetRuleDigest=None, question="小王是医生吗？", answer="是")
    assert result.status == "no_known_conflict" and result.answerSupported is None


def test_multiple_old_literal_rules_cannot_be_replaced_as_one(rule_storage):
    soup = Soup(id="synthetic", title="Test", surface="Surface", bottom="小明是凶手。",
        confusionPoints=[{"q": "小明是凶手吗？", "a": "不是"}, {"q": "小明是凶手吗??", "a": "不是"}])
    assert inspect(scope(soup)).status == "needs_human"


def test_metadata_priority_is_not_overridden_by_a_literal_replacement(rule_storage):
    soup = Soup(id="synthetic", title="Test", surface="Surface", bottom="小明是凶手。", genre="本格",
        confusionPoints=[{"q": "本汤是本格吗？", "a": "不是"}])
    source = scope(soup)
    context, soup, snapshot, body = source
    rules = baselines.strict_json(snapshot.releaseRulesJson)
    target = exact_targets_from_source(soup, context.observedPuzzleVersion, context.baseRuleVersion, rules, "本汤是本格吗？")[0]
    assert inspect(source, question="本汤是本格吗？", targetRuleDigest=target.targetRuleDigest).status == "needs_human"


def test_forged_context_fact_payload_with_valid_id_is_not_real_evidence(rule_storage):
    from app.agents.contracts import AgentError, checked_draft
    from app.agents.validation import validate_candidate
    context, soup, snapshot, body = scope()
    altered = context.model_copy(update={"factScope": (context.factScope[0].model_copy(update={"payload": "Synthetic invented truth"}),)})
    with pytest.raises(AgentError): validate_candidate(checked_draft(json.dumps(body)), context=altered, soup=soup, rule_snapshot=snapshot)


def test_source_proof_is_checked_not_just_matching_version_strings(rule_storage):
    from app.agents.contracts import AgentError, checked_draft
    from app.agents.validation import validate_candidate
    context, soup, snapshot, body = scope()
    changed = soup.model_copy(update={"bottom": "Different synthetic truth"})
    with pytest.raises(AgentError): validate_candidate(checked_draft(json.dumps(body)), context=context, soup=changed, rule_snapshot=snapshot)


def test_manifest_has_typed_frozen_context_digest_and_no_model_selected_assets(rule_storage):
    from app.agents.contracts import AgentError, AgentManifest, checked_model
    context, _, _, _ = scope()
    body = dict(schemaVersion=1, policyVersion="repair-tools-v1", context=context.model_dump(mode="json"),
        contextDigest=baselines.digest(context.model_dump(mode="json")), suiteManifestDigest=None, trafficClass="synthetic")
    manifest = checked_model(AgentManifest, body, max_bytes=524288)
    assert manifest.context == context and manifest.suiteManifestDigest is None
    for changes in ({"schemaVersion": True}, {"contextDigest": "e" * 64},
        {"trafficClass": "human_approved"}, {"datasetPath": "holdout.json"}, {"policyVersion": "unlimited"}):
        with pytest.raises(AgentError): checked_model(AgentManifest, {**body, **changes}, max_bytes=524288)


def test_other_checkpoint_cannot_be_hidden_by_unique_literal_target(rule_storage):
    soup = Soup(id="synthetic", title="Test", surface="Surface", bottom="小明是凶手。",
        confusionPoints=[{"q": "小明是凶手吗？", "a": "不是"}],
        checkpoints=[{"id": "synthetic-cp", "key": "小明是凶手", "answer": False}])
    assert inspect(scope(soup)).status == "needs_human"


def test_copied_source_with_coercible_wrong_type_is_not_a_valid_frozen_source(rule_storage):
    from app.agents.contracts import AgentError, checked_draft
    from app.agents.validation import validate_candidate
    soup = Soup(id="synthetic", title="Test", surface="Surface", bottom="小明是凶手。", castCount=2,
        confusionPoints=[{"q": "小明是凶手吗？", "a": "不是"}])
    context, soup, snapshot, body = scope(soup)
    altered = soup.model_copy(update={"castCount": "2"})
    with pytest.raises(AgentError): validate_candidate(checked_draft(json.dumps(body)),
        context=context, soup=altered, rule_snapshot=snapshot)


@pytest.mark.parametrize("special", [{"always_yes": True},
    {"win_condition": {"must_include": ["小明"], "any_of": ["凶手"], "message": "Synthetic win"}}])
@pytest.mark.parametrize("operation", ["add", "replace"])
def test_unapproved_patch_cannot_hide_higher_priority_special_game_flow(rule_storage, special, operation):
    soup = Soup(id="synthetic", title="Test", surface="Surface", bottom="小明是凶手。",
        confusionPoints=[{"q": "小明是凶手吗？", "a": "不是"}], **special)
    source = scope(soup)
    changes = {"answer": "不是"} if operation == "replace" else dict(operation="add", targetRuleDigest=None, question="小王是医生吗？", answer="不是")
    result = inspect(source, **changes)
    assert result.status == "needs_human" and result.reason == "priority_unproven"
