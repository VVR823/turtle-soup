"""Internal publisher on actual owned DB; synthetic authority is not real human review."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from app import baselines, db
from app.host_evidence import build_evidence_catalog
from app.runtime import runtime_context
from app.schemas import Soup
from .test_feedback_storage import snapshot
from .test_rule_snapshots import rule_storage, release_rows


def prepare(*, op="replace", question="小明是凶手吗？", answer="是", target=None):
    from app.rule_contract import ChangeDraft, PublicationRequest
    from app.rule_publication import enumerate_exact_targets
    conn = db._connect()
    try:
        active = baselines.active_manifest(conn)
        pointer = conn.execute("SELECT row_version FROM runtime_meta WHERE key='active_baseline'").fetchone()[0]
        p1 = active["puzzleVersions"]["synthetic"]
        soup = baselines.session_soup(conn, p1)
        fact = build_evidence_catalog(soup, p1)[0]
        targets = enumerate_exact_targets(conn, p1, active["ruleVersion"], question)
        draft = ChangeDraft(op=op, question=question, canonicalQuestionKey=question.rstrip("？?"),
            answer=answer, factIds=(fact.id,), puzzleVersion=p1, baseRuleVersion=active["ruleVersion"],
            confirmedContext=True, targetRuleDigest=target if target is not None else
                (targets[0].targetRuleDigest if op == "replace" and len(targets) == 1 else None))
        return PublicationRequest(operationKey=str(uuid4()), expectedRuleVersion=active["ruleVersion"],
            expectedPointerVersion=pointer, changeDraft=draft, regressionReportId=str(uuid4()), candidateDigest="b" * 64)
    finally:
        conn.close()


def trusted(request, **changed_receipt):
    """Program-owned fixed reviewed record, not deriving approval from later body."""
    from app.rule_contract import ReviewReceipt
    record = dict(draftDigest=baselines.digest(request.changeDraft.model_dump(mode="json")),
        candidateDigest=request.candidateDigest, regressionReportId=request.regressionReportId,
        reportDigest="c" * 64, suiteManifestDigest="d" * 64,
        puzzleVersion=request.changeDraft.puzzleVersion, baseRuleVersion=request.expectedRuleVersion,
        status="complete", answerSupported=True, contextIndependent=True, reviewNote="Synthetic reviewed record")
    record.update(changed_receipt)
    def authorize(conn, submitted):
        assert conn.in_transaction
        return ReviewReceipt.model_validate_json(baselines.canonical_json(record))
    return authorize


def publisher(request, **changed_receipt):
    from app.rule_publication import RulePublisher
    return RulePublisher(authorizer=trusted(request, **changed_receipt))


def test_publisher_has_no_default_or_testing_authority(rule_storage):
    from app.rule_publication import RulePublisher
    with pytest.raises(TypeError):
        RulePublisher()
    with pytest.raises(TypeError):
        RulePublisher(authorizer=None)
    assert len(release_rows()) == 1


def test_publish_new_snapshot_atomic_audit_and_original_puzzle_retained(rule_storage):
    from app.rule_contract import read_rule_snapshot
    old = release_rows()[0]; request = prepare(); result = publisher(request).publish(request)
    conn = db._connect()
    try:
        assert result.ruleVersion != request.expectedRuleVersion and result.pointerVersion == 1
        assert baselines.active_manifest(conn)["ruleVersion"] == result.ruleVersion
        exact = read_rule_snapshot(conn, request.changeDraft.puzzleVersion, result.ruleVersion).exactRules
        assert len(exact) == 1 and exact[0].answer == "是"
        assert conn.execute("SELECT event_type FROM audit_events").fetchall()[0][0] == "rule_published"
        assert baselines.session_baseline(conn, request.changeDraft.puzzleVersion, request.expectedRuleVersion).confusionPoints[0].a == "不是"
    finally:
        conn.close()
    assert release_rows()[0] == old and rule_storage.model.calls == []


@pytest.mark.parametrize("change", [{"draftDigest": "e" * 64}, {"candidateDigest": "e" * 64},
    {"regressionReportId": str(uuid4())}, {"puzzleVersion": "p1:" + "e" * 64},
    {"baseRuleVersion": "r1:" + "e" * 64}, {"answerSupported": False}, {"contextIndependent": False},
    {"status": "incomplete"}, {"reviewNote": ""}, {"suiteManifestDigest": "not a digest"}])
def test_receipt_substitution_or_incomplete_confirmation_refuses_all_writes(rule_storage, change):
    from app.rule_publication import RulePublicationError
    request = prepare(); before = snapshot()
    with pytest.raises(RulePublicationError):
        publisher(request, **change).publish(request)
    assert snapshot() == before


def test_review_of_old_body_cannot_authorize_changed_answer(rule_storage):
    from app.rule_publication import RulePublicationError
    request = prepare(); approved = publisher(request)
    altered = request.model_copy(update={"changeDraft": request.changeDraft.model_copy(update={"answer": "算是"})})
    before = snapshot()
    with pytest.raises(RulePublicationError):
        approved.publish(altered)
    assert snapshot() == before


def test_double_publish_same_pointer_one_winner_one_stale(rule_storage):
    from app.rule_publication import RulePublicationError
    first, second = prepare(), prepare(); gate = Barrier(2)
    def run(request):
        with runtime_context(rule_storage):
            gate.wait(timeout=5)
            try:
                return publisher(request).publish(request)
            except RulePublicationError as error:
                return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, (first, second)))
    assert sum(not isinstance(item, str) for item in outcomes) == 1
    assert outcomes.count("rule_pointer_conflict") == 1 and len(release_rows()) == 2


def test_same_operation_replays_without_duplicate_release_or_event(rule_storage):
    request = prepare(); owned = publisher(request)
    result = owned.publish(request); before = snapshot()
    assert owned.publish(request) == result and snapshot() == before


def test_same_operation_key_with_changed_body_is_conflict(rule_storage):
    from app.rule_publication import RulePublicationError
    request = prepare(); publisher(request).publish(request); before = snapshot()
    altered = request.model_copy(update={"candidateDigest": "e" * 64})
    with pytest.raises(RulePublicationError) as caught:
        publisher(altered).publish(altered)
    assert caught.value.code == "rule_operation_conflict" and snapshot() == before


@pytest.mark.parametrize("boundary", ["release", "pointer", "operation", "audit", "commit"])
def test_publish_fault_whole_database_unchanged(rule_storage, monkeypatch, boundary):
    from app.rule_publication import RulePublicationError
    request = prepare(); before = snapshot(); connect = db._connect
    class Fault:
        def __init__(self): self.inner = connect()
        def __getattr__(self, name): return getattr(self.inner, name)
        def execute(self, sql, params=()):
            if ((boundary == "release" and sql.startswith("INSERT INTO rule_releases"))
                or (boundary == "pointer" and sql.startswith("UPDATE runtime_meta"))
                or (boundary == "operation" and sql.startswith("INSERT INTO runtime_meta"))
                or (boundary == "audit" and sql.startswith("INSERT INTO audit_events"))):
                raise sqlite3.OperationalError("PRIVATE injected failure")
            return self.inner.execute(sql, params)
        def commit(self):
            if boundary == "commit": raise sqlite3.OperationalError("PRIVATE commit")
            return self.inner.commit()
    with monkeypatch.context() as patch:
        patch.setattr(db, "_connect", lambda **_kw: Fault())
        with pytest.raises(RulePublicationError): publisher(request).publish(request)
    assert snapshot() == before


def test_add_cannot_cover_existing_literal_opposite_rule(rule_storage):
    from app.rule_publication import RulePublicationError
    request = prepare(op="add"); before = snapshot()
    with pytest.raises(RulePublicationError) as caught:
        publisher(request).publish(request)
    assert caught.value.code == "rule_target_conflict" and snapshot() == before


def test_replace_full_target_digest_not_question_only(rule_storage):
    from app.rule_publication import RulePublicationError
    request = prepare(target="f" * 64); before = snapshot()
    with pytest.raises(RulePublicationError) as caught:
        publisher(request).publish(request)
    assert caught.value.code == "rule_target_conflict" and snapshot() == before


def test_unique_published_overlay_can_be_replaced_without_mutating_previous(rule_storage):
    from app.rule_contract import read_rule_snapshot
    first = prepare(); previous = publisher(first).publish(first); before = release_rows()
    second = prepare(answer="算是"); result = publisher(second).publish(second)
    conn = db._connect()
    try:
        assert read_rule_snapshot(conn, first.changeDraft.puzzleVersion, previous.ruleVersion).exactRules[0].answer == "是"
        assert read_rule_snapshot(conn, first.changeDraft.puzzleVersion, result.ruleVersion).exactRules[0].answer == "算是"
    finally: conn.close()
    assert release_rows()[:2] == before


def test_published_r1_binds_full_review_and_suite_not_only_report_digest(rule_storage):
    from app.rule_contract import read_rule_snapshot
    request = prepare(); result = publisher(request).publish(request)
    conn = db._connect()
    try:
        rule = read_rule_snapshot(conn, request.changeDraft.puzzleVersion, result.ruleVersion).exactRules[0]
        assert rule.reviewReceipt.suiteManifestDigest == "d" * 64
        assert rule.reviewReceipt.regressionReportId == request.regressionReportId
        assert rule.reviewReceipt.draftDigest == baselines.digest(request.changeDraft.model_dump(mode="json"))
        assert rule.reviewReceipt.reviewNote == "Synthetic reviewed record"
    finally:
        conn.close()


@pytest.mark.parametrize("change", [{"reportDigest": "e" * 64}, {"suiteManifestDigest": "e" * 64}])
def test_replay_does_not_silently_accept_swapped_review_material(rule_storage, change):
    from app.rule_publication import RulePublicationError
    request = prepare(); publisher(request).publish(request); before = snapshot()
    with pytest.raises(RulePublicationError) as caught:
        publisher(request, **change).publish(request)
    assert caught.value.code == "rule_operation_conflict" and snapshot() == before


@pytest.mark.parametrize("kind", ["ambiguous", "regex", "checkpoint", "metadata", "conditional", "reference"])
def test_unknown_nonliteral_or_multitarget_replacements_need_human(runtime, kind):
    from app.rule_publication import RulePublicationError
    question = "小明是凶手吗？"
    args = dict(confusionPoints=[])
    if kind == "ambiguous":
        args["confusionPoints"] = [{"q": question, "a": "是"}, {"q": question, "a": "不是"}]
    elif kind == "regex":
        args["confusionPoints"] = [{"q": "关于凶手的问法", "a": "不是", "match": [".*凶手.*"]}]
    elif kind == "checkpoint":
        args["checkpoints"] = [{"key": "小明是凶手", "answer": True}]
    elif kind == "metadata":
        question = "故事是本格吗？"; args["genre"] = "本格"
    elif kind == "conditional":
        question = "如果小明离开了，他是凶手吗？"
        args["confusionPoints"] = [{"q": question, "a": "是"}]
    else:
        question = "他是凶手吗？"; args["confusionPoints"] = [{"q": question, "a": "是"}]
    runtime.soups = [Soup(id="synthetic", title="T", surface="S", bottom="Synthetic truth", **args)]
    db.initialize(); request = prepare(question=question); before = snapshot()
    with pytest.raises(RulePublicationError) as caught:
        publisher(request).publish(request)
    assert caught.value.code in {"rule_context_requires_human", "rule_target_conflict"}
    assert snapshot() == before and runtime.model.calls == []


def test_foreign_fact_cannot_be_published_even_with_owned_review_of_changed_body(rule_storage):
    from app.rule_publication import RulePublicationError
    request = prepare()
    forged = request.model_copy(update={"changeDraft": request.changeDraft.model_copy(update={"factIds": ("f1:" + "f" * 64,)})})
    before = snapshot()
    with pytest.raises(RulePublicationError, match="rule_fact_requires_human"):
        publisher(forged).publish(forged)
    assert snapshot() == before
