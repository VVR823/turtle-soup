"""The sole TS15 review fix pass: actual synthetic stores, never human evidence."""
from pathlib import Path

import pytest

from app import audit_store
from app.candidate_review_contracts import CandidateReject, CandidateReviewError
from .test_candidate_review_publication import approved
from .test_candidate_review_store import proposal
from .test_candidate_review_mutations import approve_intent
from .test_candidate_validation import scope
from .test_feedback_storage import snapshot
from .test_repair_corpus import frozen_corpus
from .test_rule_snapshots import rule_storage


@pytest.mark.parametrize("action", ["approve", "publish"])
@pytest.mark.parametrize("change", ["withdraw", "replace", "code"])
def test_non_db_authority_change_after_necessary_audit_rolls_back_the_whole_mutation(rule_storage, monkeypatch, action, change):
    # Break caught: proof checked only before writes, not at the final commit.
    if action == "publish":
        owner, _, cid, request = approved(rule_storage)
        event_type = "candidate_published"
    else:
        owner, _, cid = proposal(rule_storage)
        request = approve_intent(owner.detail(cid))
        event_type = "candidate_reviewed"
    before = snapshot()
    insert, read_bytes = audit_store.insert_business_event, Path.read_bytes
    changed_corpus = frozen_corpus(scope()) if change == "replace" else None
    reached = []

    def changed_bytes(path):
        data = read_bytes(path)
        return data + b"\n# Synthetic after-proof source withdrawal\n" if path.name == "candidate_review.py" else data

    def withdraw_after_actual_insert(conn, event):
        result = insert(conn, event)
        if event.eventType == event_type:
            reached.append(event.eventType)
            if change == "code":
                monkeypatch.setattr(Path, "read_bytes", changed_bytes)
            else:
                rule_storage.repair_corpus = changed_corpus
        return result

    monkeypatch.setattr(audit_store, "insert_business_event", withdraw_after_actual_insert)
    with pytest.raises(CandidateReviewError) as caught:
        getattr(owner, action)(cid, request)
    assert caught.value.code == "candidate_proof_stale" and caught.value.status == 409
    assert reached == [event_type]
    # Includes releases, pointer, candidate, review, both receipts and audits.
    assert snapshot() == before


@pytest.mark.parametrize("action", ["approve", "publish"])
def test_unchanged_authority_still_commits_and_exact_replay_needs_no_new_authority(rule_storage, action):
    if action == "publish":
        owner, _, cid, request = approved(rule_storage)
    else:
        owner, _, cid = proposal(rule_storage)
        request = approve_intent(owner.detail(cid))
    result = getattr(owner, action)(cid, request)
    assert result.candidateStatus == ("published" if action == "publish" else "approved")
    rule_storage.repair_corpus = None
    before = snapshot()
    assert getattr(owner, action)(cid, request) == result and snapshot() == before


def test_stale_rejection_needs_no_fresh_corpus_at_commit(rule_storage):
    from uuid import uuid4
    owner, _, cid = proposal(rule_storage)
    rule_storage.repair_corpus = None
    result = owner.reject(cid, CandidateReject(operationKey=str(uuid4()), expectedReviewVersion=0,
        reviewNote="Synthetic explicit dismissal, not publication authority"))
    assert result.candidateStatus == "rejected"


def test_concurrent_corpus_assignment_waits_for_final_identity_check_and_commit(rule_storage, monkeypatch):
    from threading import Event, Thread, get_ident
    from app import runtime as runtime_module
    owner, _, cid, request = approved(rule_storage)
    commit_thread = get_ident()
    attempted, done = Event(), Event()
    native_lock = rule_storage.lock

    class ObservedLock:
        def __enter__(self):
            if get_ident() != commit_thread:
                attempted.set()
            native_lock.acquire()
            return self

        def __exit__(self, *args):
            native_lock.release()

    rule_storage.lock = ObservedLock()
    verify = runtime_module._verified_repair_corpus
    calls, observed = [], []

    def withdraw():
        rule_storage.repair_corpus = None
        done.set()

    writer = Thread(target=withdraw, name="ts15-owned-corpus-withdrawal")

    def observe_final(corpus, **kwargs):
        checked = verify(corpus, **kwargs)
        calls.append(True)
        if len(calls) == 2:  # Initial detail, then the real final commit check.
            writer.start()
            observed.append((attempted.wait(timeout=0.5), not done.is_set()))
        return checked

    monkeypatch.setattr(runtime_module, "_verified_repair_corpus", observe_final)
    try:
        result = owner.publish(cid, request)
    finally:
        if writer.ident is not None:
            writer.join(timeout=3)
        rule_storage.lock = native_lock
    assert observed == [(True, True)]  # Assignment actually attempted the same lock.
    assert not writer.is_alive() and done.is_set()
    assert result.candidateStatus == "published"
    assert rule_storage.repair_corpus is None
    assert owner.publish(cid, request) == result  # Historical ack survives withdrawal.


def context_proposal(active, monkeypatch, *, previous=1, long_reply=False):
    """Real game writes precede the feedback/run; no report or approval seed."""
    from uuid import uuid4
    from app import db
    from app.schemas import HostResult, HostVersions
    from app.feedback_store import submit_feedback, review_feedback, set_model_permission
    from .test_feedback_storage import body
    from .test_feedback_privacy import permission
    ids = []

    def finish(sid, question, reply="是"):
        turn = db.reserve_turn(sid, str(uuid4()), question)
        db.finish_turn(turn, HostResult(kind="answer", answer="是", reply=reply,
            source="llm", chargeable=True, versions=HostVersions(
                puzzleVersion=turn.puzzleVersion, ruleVersion=turn.ruleVersion)))
        return turn

    def prepared_context():
        sid = db.create_game_once("synthetic", "xuermu", str(uuid4()))["sessionId"]
        # Owned test session only, so boundary tests can exceed the game limit.
        conn = db._connect()
        try:
            conn.execute("UPDATE sessions SET question_limit=NULL WHERE id=?", (sid,))
            conn.commit()
        finally:
            conn.close()
        for number in range(previous):
            finish(sid, f"原始前文{number}：刚才说的是小明吗？", "背景" * 1000 if long_reply else "是")
        target = finish(sid, "是谁？")
        ids.append(sid)
        submitted = submit_feedback(body(turnId=target.turnId))
        reviewed = review_feedback(submitted.id, 0, status="approved")
        return set_model_permission(reviewed.id, reviewed.rowVersion,
            review=permission(sanitizedQuestion="经过脱敏的问题？"))

    from . import test_repair_corpus as repair_fixtures
    monkeypatch.setattr(repair_fixtures, "prepared", prepared_context)
    owner, run, cid = proposal(active)
    return owner, run, cid, ids[0], finish


def test_original_context_is_bound_to_actual_pre_turn_messages_not_claim_or_later_history(rule_storage, monkeypatch):
    from uuid import uuid4
    from app import db
    owner, run, cid, sid, finish = context_proposal(rule_storage, monkeypatch)
    before = snapshot()
    detail = owner.detail(cid)
    assert detail.availability == "ready"
    source = getattr(detail.material, "sourceContext", None)
    assert source is not None, "Human review lacks actual original context"
    assert source.scope == "admin_review_only" and source.inputKind == "stored_private_source"
    assert source.sessionId == sid and source.turnId == run.manifest.context.turnId
    assert source.originalQuestion == "是谁？" and source.originalHostAnswer == "是"
    assert detail.material.sanitizedInput.question == "经过脱敏的问题？"
    assert [(m.role, m.content) for m in source.messages] == [
        ("user", "原始前文0：刚才说的是小明吗？"), ("host", "是")]
    assert snapshot() == before
    finish(sid, "后续提问绝不能成为原始前文？")
    other = db.create_game_once("synthetic", "xuermu", str(uuid4()))["sessionId"]
    finish(other, "别的会话不能成为原始前文？")
    later = owner.detail(cid)
    assert later.material.sourceContext == source and later.proofDigest == detail.proofDigest
    assert "原始前文" not in run.manifest.context.model_dump_json()
    assert "PRIVATE synthetic claim" not in later.model_dump_json()


@pytest.mark.parametrize("broken", ["missing_pair", "changed_previous"])
def test_missing_or_corrupt_source_context_is_not_empty_permission_to_approve(rule_storage, monkeypatch, broken):
    from app import db
    owner, run, cid, sid, _ = context_proposal(rule_storage, monkeypatch)
    request = approve_intent(owner.detail(cid))
    conn = db._connect()
    try:
        if broken == "missing_pair":
            conn.execute("DELETE FROM messages WHERE turn_id=? AND role='host'", (run.manifest.context.turnId,))
        else:
            conn.execute("UPDATE messages SET content='与真实来源不匹配' WHERE id=(SELECT min(id) FROM messages WHERE session_id=?)", (sid,))
        conn.commit()
    finally:
        conn.close()
    before = snapshot()
    detail = owner.detail(cid)
    assert detail.availability == "unavailable" and detail.blockers == ("candidate_context_unavailable",)
    assert detail.material is detail.proofDigest is None
    with pytest.raises(CandidateReviewError) as caught:
        owner.approve(cid, request)
    assert caught.value.code == "candidate_proof_stale" and snapshot() == before


@pytest.mark.parametrize("previous,long_reply,ready", [(50, False, True), (51, False, False), (25, True, False)])
def test_human_context_caps_refuse_complete_source_without_silently_trimming(rule_storage, monkeypatch, previous, long_reply, ready):
    owner, _, cid, _, _ = context_proposal(rule_storage, monkeypatch, previous=previous, long_reply=long_reply)
    before = snapshot()
    detail = owner.detail(cid)
    if ready:
        source = getattr(detail.material, "sourceContext", None)
        assert source is not None and len(source.messages) == 100
    else:
        assert detail.availability == "unavailable" and detail.material is detail.proofDigest is None
        assert detail.blockers == ("candidate_context_unavailable",)
    assert snapshot() == before
