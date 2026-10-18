"""Actual feedback transactions/CAS on owned SQLite, never a JSONL writer."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from app import db
from app.runtime import runtime_context
from app.schemas import FeedbackSubmit, HostResult, HostVersions
from .test_migrations import puzzle


@pytest.fixture
def storage(runtime):
    runtime.soups = [puzzle()]
    db.initialize()
    return runtime


def body(**changes):
    values = dict(soupId=puzzle().id, question="是谁？", hostAnswer="是", expectedAnswer="不知道",
        reason="PRIVATE synthetic claim")
    return FeedbackSubmit(**{**values, **changes})


def rows(table):
    assert table in {"feedback_items", "audit_events"}
    conn = db._connect()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM " + table + " ORDER BY rowid")]
    finally:
        conn.close()


def snapshot():
    conn = db._connect()
    try:
        return "\n".join(conn.iterdump())
    finally:
        conn.close()


def parallel(active, operations):
    gate = Barrier(len(operations))
    def run(operation):
        with runtime_context(active):
            gate.wait(timeout=5)
            return operation()
    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return list(pool.map(run, operations))


def test_submit_parallel_twenty_keeps_every_record(storage):
    from app.feedback_store import submit_feedback
    results = parallel(storage, [lambda index=index: submit_feedback(body(question=f"第{index}个是谁？")) for index in range(20)])
    assert len({item.id for item in results}) == 20
    assert all(item.status == "pending" and item.rowVersion == 0 and not item.safeForModel
        and item.sourceState == "unverified" for item in results)
    saved, audited = rows("feedback_items"), rows("audit_events")
    assert len(saved) == len(audited) == 20
    assert {json.loads(row["payload_json"])["question"] for row in saved} == {f"第{i}个是谁？" for i in range(20)}
    assert all(row["event_type"] == "feedback_submitted" for row in audited)
    assert all("PRIVATE" not in row["details_json"] for row in audited)
    assert not (storage.settings.DATA_DIR / "feedback.jsonl").exists()


def test_submit_and_review_race_retains_new_rows(storage):
    from app.feedback_store import review_feedback, submit_feedback
    old = submit_feedback(body())
    parallel(storage, [lambda: submit_feedback(body(question="新的问题？")),
        lambda: review_feedback(old.id, 0, status="approved")])
    saved = rows("feedback_items")
    assert len(saved) == 2
    reviewed = next(row for row in saved if row["id"] == old.id)
    assert reviewed["status"] == "approved" and reviewed["row_version"] == 1
    assert reviewed["safe_for_model"] == 0
    assert len(rows("audit_events")) == 3


def test_two_reviewers_same_version_only_one_wins(storage):
    from app.feedback_contract import FeedbackError
    from app.feedback_store import review_feedback, submit_feedback
    old = submit_feedback(body())
    def decide(status):
        try:
            return review_feedback(old.id, 0, status=status)
        except FeedbackError as error:
            return error
    results = parallel(storage, [lambda: decide("approved"), lambda: decide("rejected")])
    errors = [item for item in results if isinstance(item, FeedbackError)]
    assert len(errors) == 1 and errors[0].code == "feedback_version_conflict" and errors[0].status == 409
    assert rows("feedback_items")[0]["row_version"] == 1
    assert len(rows("audit_events")) == 2


def test_unknown_soup_rejected_without_any_feedback(storage):
    from app.feedback_contract import FeedbackError
    from app.feedback_store import submit_feedback
    with pytest.raises(FeedbackError) as caught:
        submit_feedback(body(soupId="foreign-soup"))
    assert caught.value.code == "feedback_soup_unknown" and caught.value.status == 422
    assert rows("feedback_items") == rows("audit_events") == []


def completed_turn():
    sid = db.create_game_once(puzzle().id, "xuermu", str(uuid4()))["sessionId"]
    owner = db.reserve_turn(sid, str(uuid4()), "是谁？")
    db.finish_turn(owner, HostResult(kind="answer", answer="是", reply="是", source="llm", chargeable=True,
        versions=HostVersions(puzzleVersion=owner.puzzleVersion, ruleVersion=owner.ruleVersion)))
    return owner


def test_linked_turn_checks_real_soup_question_result_versions(storage):
    from app.feedback_store import submit_feedback
    owner = completed_turn()
    item = submit_feedback(body(turnId=owner.turnId))
    source = json.loads(rows("feedback_items")[0]["source_json"])
    assert item.sourceState == "linked" and item.turnId == owner.turnId
    assert source["sessionId"] == owner.sessionId and source["turnId"] == owner.turnId
    assert source["puzzleVersion"] == owner.puzzleVersion and source["ruleVersion"] == owner.ruleVersion
    assert source["state"] == "linked"
    assert item.expectedAnswer == "不知道" and item.safeForModel is False


@pytest.mark.parametrize("changed", [{"question": "另一个问题？"}, {"hostAnswer": "不是"}, {"soupId": "foreign"}])
def test_wrong_question_or_display_answer_cannot_borrow_trace(storage, changed):
    from app.feedback_contract import FeedbackError
    from app.feedback_store import submit_feedback
    owner = completed_turn()
    before = snapshot()
    with pytest.raises(FeedbackError) as caught:
        submit_feedback(body(turnId=owner.turnId, **changed))
    assert caught.value.code == "feedback_source_mismatch" and snapshot() == before


def test_unavailable_turn_stays_rejected_not_another_turn_substitution(storage):
    from app.feedback_contract import FeedbackError
    from app.feedback_store import submit_feedback
    completed_turn()
    with pytest.raises(FeedbackError) as caught:
        submit_feedback(body(turnId=str(uuid4())))
    assert caught.value.code == "feedback_source_unavailable" and rows("feedback_items") == []


@pytest.mark.parametrize("operation", ["submit", "review"])
@pytest.mark.parametrize("boundary", ["row", "audit", "commit"])
def test_feedback_audit_failure_rolls_back_all_writes(storage, monkeypatch, operation, boundary, capsys):
    from app.feedback_store import review_feedback, submit_feedback
    item = submit_feedback(body()) if operation == "review" else None
    before = snapshot(); connect = db._connect
    class Fault:
        def __init__(self):
            self.inner = connect()
        def __getattr__(self, name):
            return getattr(self.inner, name)
        def execute(self, sql, params=()):
            if ((boundary == "row" and sql.startswith(("INSERT INTO feedback_items", "UPDATE feedback_items")))
                or boundary == "audit" and sql.startswith("INSERT INTO audit_events")):
                raise sqlite3.OperationalError("PRIVATE synthetic DB failure")
            return self.inner.execute(sql, params)
        def commit(self):
            if boundary == "commit":
                raise sqlite3.OperationalError("PRIVATE synthetic commit")
            self.inner.commit()
    with monkeypatch.context() as patch:
        patch.setattr(db, "_connect", lambda **_kw: Fault())
        with pytest.raises(Exception):
            if operation == "submit":
                submit_feedback(body())
            else:
                review_feedback(item.id, 0, status="approved")
    assert snapshot() == before
    assert "PRIVATE" not in capsys.readouterr().err


def test_missing_m2_blocks_feedback_without_legacy_writer(storage):
    from app.feedback_store import submit_feedback
    conn = db._connect()
    conn.execute("DELETE FROM schema_migrations WHERE version=2"); conn.commit(); conn.close()
    before = snapshot()
    with pytest.raises(Exception):
        submit_feedback(body())
    assert snapshot() == before and not (storage.settings.DATA_DIR / "feedback.jsonl").exists()


def test_bounded_stable_page_has_no_duplicates_when_default_clock_moves(storage, monkeypatch):
    from app import feedback_store
    now = 1000000.0
    monkeypatch.setattr(feedback_store.time, "time", lambda: now - 7 * 86400 + 0.5)
    for index in range(3):
        feedback_store.submit_feedback(body(question=f"问题{index}？"))
    monkeypatch.setattr(feedback_store.time, "time", lambda: now)
    first = feedback_store.list_feedback(limit=1)
    monkeypatch.setattr(feedback_store.time, "time", lambda: now + 1)
    second = feedback_store.list_feedback(limit=2, cursor=first.nextCursor)
    assert first.totalInRange == second.totalInRange == 3
    assert len(second.feedbacks) == 2 and second.nextCursor is None
    assert len({item.id for item in first.feedbacks + second.feedbacks}) == 3


def test_private_list_refuses_mirrored_soup_identity_drift(storage):
    from app.feedback_contract import FeedbackError
    from app.feedback_store import list_feedback, submit_feedback
    item = submit_feedback(body())
    conn = db._connect()
    conn.execute("UPDATE feedback_items SET soup_id='foreign' WHERE id=?", (item.id,)); conn.commit(); conn.close()
    with pytest.raises(FeedbackError) as caught:
        list_feedback()
    assert caught.value.code == "feedback_unavailable"


def test_time_window_cannot_contain_more_than_fifty_by_default_or_hundred_max(storage):
    from app.feedback_store import list_feedback, submit_feedback
    for index in range(103):
        submit_feedback(body(question=f"第{index}问？"))
    first = list_feedback()
    largest = list_feedback(limit=100)
    assert len(first.feedbacks) == 50 and first.totalInRange == 103 and first.nextCursor
    assert len(largest.feedbacks) == 100 and largest.nextCursor
    tail = list_feedback(limit=100, cursor=largest.nextCursor)
    assert len(tail.feedbacks) == 3 and tail.nextCursor is None


def test_list_filtered_cursor_requires_same_soup_digest_without_raw_filter_growth(storage):
    from app.feedback_contract import FeedbackError
    from app.feedback_store import list_feedback, submit_feedback
    for index in range(3):
        submit_feedback(body(question=f"第{index}问？"))
    first = list_feedback(limit=1, status="pending", soup_id=puzzle().id)
    assert len(first.nextCursor) <= 512
    next_page = list_feedback(limit=2, cursor=first.nextCursor, soup_id=puzzle().id)
    assert len(next_page.feedbacks) == 2
    for params in ({"soup_id": "foreign"}, {"status": "approved", "soup_id": puzzle().id}, {}):
        with pytest.raises(FeedbackError) as caught:
            list_feedback(cursor=first.nextCursor, **params)
        assert caught.value.code == "feedback_query_invalid"


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"limit": True},
    {"start": 0, "end": 31 * 86400 + 1}, {"end": float("nan")}, {"cursor": "x" * 513}])
def test_list_refuses_unbounded_or_invalid_query(storage, params):
    from app.feedback_contract import FeedbackError
    from app.feedback_store import list_feedback
    with pytest.raises(FeedbackError) as caught:
        list_feedback(**params)
    assert caught.value.code == "feedback_query_invalid" and caught.value.status == 422
