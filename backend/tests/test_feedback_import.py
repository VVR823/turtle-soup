"""Explicit owned JSONL import preserves provenance and never grants AI access."""
import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import UUID

import pytest

from app import audit_store, db
from .test_feedback_storage import body, rows, snapshot, storage


def legacy(**changes):
    values = {"id": "duplicate-old-id", "ts": "2026-10-08T00:00:00Z",
        **body().model_dump(exclude={"turnId"}), "status": "approved",
        "soupTitle": "Synthetic", "reviewedAt": "2026-10-08T00:01:00Z",
        "mergedAt": None, "mergedAnswer": None}
    return {**values, **changes}


def source_file(tmp_path, records):
    source = tmp_path / "owned-feedback.jsonl"
    raw = b"".join(json.dumps(row, ensure_ascii=False).encode() + b"\n" for row in records)
    source.write_bytes(raw)
    return source, hashlib.sha256(raw).hexdigest(), raw


def imported(source, digest):
    from app.feedback_import import import_feedback_jsonl
    conn = db._connect()
    try:
        return import_feedback_jsonl(conn, source, source_digest=digest)
    finally:
        conn.close()


def test_duplicate_legacy_id_different_questions_are_distinct_rows(storage, tmp_path):
    source, digest, raw = source_file(tmp_path, [legacy(), legacy(question="第二个问题？")])
    report = imported(source, digest)
    saved = rows("feedback_items")
    assert report.imported == 2 and report.duplicates == 0 and not report.productionReady
    assert len(saved) == 2 and len({row["id"] for row in saved}) == 2
    assert all(UUID(row["id"]).version == 5 for row in saved)
    assert {json.loads(row["payload_json"])["question"] for row in saved} == {"是谁？", "第二个问题？"}
    assert all(row["status"] == "approved" and row["safe_for_model"] == 0 and row["turn_id"] is None for row in saved)
    origins = [json.loads(row["source_json"]) for row in saved]
    assert {origin["lineNumber"] for origin in origins} == {1, 2}
    assert all(origin["sourceFileDigest"] == digest and origin["state"] == "legacy" for origin in origins)
    assert len(rows("audit_events")) == 2 and source.read_bytes() == raw
    assert all("PRIVATE" not in row["details_json"] for row in rows("audit_events"))


def test_same_source_repeat_no_new_rows_or_overwritten_review(storage, tmp_path):
    from app.feedback_store import review_feedback
    source, digest, raw = source_file(tmp_path, [legacy()])
    first = imported(source, digest)
    identity = rows("feedback_items")[0]["id"]
    review_feedback(identity, 0, status="rejected")
    before = snapshot()
    repeat = imported(source, digest)
    assert first.imported == 1 and repeat.imported == 0 and repeat.duplicates == 1
    assert snapshot() == before and source.read_bytes() == raw


@pytest.mark.parametrize("later", ["granted", "revoked", "reviewed-again"])
def test_same_source_repeat_preserves_later_privacy_decisions(storage, tmp_path, later):
    from app.feedback_store import set_model_permission, review_feedback
    from app.feedback_contract import PrivacyReview
    from .test_feedback_privacy import permission
    source, digest, raw = source_file(tmp_path, [legacy()])
    imported(source, digest)
    identity = rows("feedback_items")[0]["id"]
    granted = set_model_permission(identity, 0, review=permission())
    if later == "revoked":
        set_model_permission(identity, granted.rowVersion,
            review=PrivacyReview(safeForModel=False, reviewNote="Synthetic revoke"))
    elif later == "reviewed-again":
        review_feedback(identity, granted.rowVersion, status="rejected")
    before = snapshot()
    repeat = imported(source, digest)
    assert repeat.imported == 0 and repeat.duplicates == 1
    assert snapshot() == before and source.read_bytes() == raw and storage.model.calls == []


@pytest.mark.parametrize("mutation", ["origin", "unknown", "privacy"])
def test_reimport_still_rejects_corrupt_source_after_privacy_review(storage, tmp_path, mutation):
    from app.feedback_import import FeedbackImportError
    from app.feedback_store import set_model_permission
    from .test_feedback_privacy import permission
    source, digest, raw = source_file(tmp_path, [legacy()])
    imported(source, digest)
    identity = rows("feedback_items")[0]["id"]
    set_model_permission(identity, 0, review=permission())
    origin = json.loads(rows("feedback_items")[0]["source_json"])
    if mutation == "origin": origin["lineDigest"] = "a" * 64
    elif mutation == "unknown": origin["unexpected"] = "ignored data"
    else: origin["privacy"]["inputDigest"] = "a" * 64
    conn = db._connect()
    conn.execute("UPDATE feedback_items SET source_json=? WHERE id=?", (json.dumps(origin), identity))
    conn.commit(); conn.close(); before = snapshot()
    with pytest.raises(FeedbackImportError) as caught: imported(source, digest)
    assert caught.value.code == "feedback_import_conflict"
    assert snapshot() == before and source.read_bytes() == raw


def test_identical_physical_lines_keep_separate_provenance(storage, tmp_path):
    source, digest, _ = source_file(tmp_path, [legacy(), legacy()])
    report = imported(source, digest)
    assert report.imported == 2 and len(rows("feedback_items")) == 2


@pytest.mark.parametrize("bad", [b'{"broken":\n', b'\xff\n', b'{"partial":',
    json.dumps(legacy(ts="wrong-date")).encode() + b"\n",
    json.dumps(legacy(unsafe="PRIVATE unknown field")).encode() + b"\n",
    b"x" * 32769 + b"\n",
], ids=["broken-json", "invalid-utf8", "partial-tail", "invalid-time", "unknown-field", "oversized-line"])
def test_bad_row_is_reported_without_raw_text_or_source_modification(storage, tmp_path, bad, capsys):
    source = tmp_path / "bad-source.jsonl"
    good = json.dumps(legacy(), ensure_ascii=False).encode() + b"\n"
    raw = good + bad; source.write_bytes(raw); digest = hashlib.sha256(raw).hexdigest()
    report = imported(source, digest)
    assert report.imported == 1 and len(report.badRows) == 1 and report.needsReview
    assert report.badRows[0].lineNumber == 2 and len(report.badRows[0].lineDigest) == 64
    assert report.sourceDigest == digest and source.read_bytes() == raw
    assert "PRIVATE" not in report.model_dump_json() + capsys.readouterr().err


def test_changed_source_digest_refuses_before_any_write(storage, tmp_path):
    from app.feedback_import import FeedbackImportError
    source, _, raw = source_file(tmp_path, [legacy()])
    before = snapshot()
    with pytest.raises(FeedbackImportError) as caught:
        imported(source, "a" * 64)
    assert caught.value.code == "feedback_source_changed"
    assert snapshot() == before and source.read_bytes() == raw


def test_import_audit_refusal_rolls_back_and_can_retry(storage, tmp_path, monkeypatch):
    from app.feedback_import import FeedbackImportError
    source, digest, raw = source_file(tmp_path, [legacy(), legacy(question="另一问？")])
    before = snapshot()
    def denied(*_args):
        raise audit_store.AuditPersistenceError("Synthetic refusal")
    with monkeypatch.context() as patch:
        patch.setattr(audit_store, "insert_business_event", denied)
        with pytest.raises(FeedbackImportError):
            imported(source, digest)
    assert snapshot() == before and source.read_bytes() == raw
    assert imported(source, digest).imported == 2


def test_known_missing_m2_cannot_import_via_legacy_writer(storage, tmp_path):
    from app.feedback_import import FeedbackImportError
    source, digest, raw = source_file(tmp_path, [legacy()])
    conn = db._connect()
    conn.execute("DELETE FROM schema_migrations WHERE version=2"); conn.commit(); conn.close()
    before = snapshot()
    with pytest.raises(FeedbackImportError):
        imported(source, digest)
    assert snapshot() == before and source.read_bytes() == raw


@pytest.mark.parametrize("kind", ["bytes", "rows"])
def test_source_budget_refusal_is_atomic_not_partial_import(storage, tmp_path, kind):
    from app.feedback_import import FeedbackImportError
    source = tmp_path / "bounded-source.jsonl"
    if kind == "bytes":
        with source.open("wb") as stream:
            stream.truncate(100 * 1024 * 1024 + 1)
        digest = "a" * 64  # Byte budget must reject before digest scanning.
    else:
        raw = (json.dumps(legacy()).encode() + b"\n") * 5001
        source.write_bytes(raw); digest = hashlib.sha256(raw).hexdigest()
    before = snapshot()
    with pytest.raises(FeedbackImportError) as caught:
        imported(source, digest)
    assert caught.value.code == "feedback_source_limit" and snapshot() == before


def test_source_change_during_native_read_cannot_be_accepted(storage, tmp_path, monkeypatch):
    from app.feedback_import import FeedbackImportError
    source, digest, raw = source_file(tmp_path, [legacy()])
    before = snapshot(); original_open = Path.open; changed = False
    class ChangingReader:
        def __init__(self, stream):
            self.stream = stream
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def __enter__(self):
            return self
        def __iter__(self):
            return iter(self.stream)
        def __exit__(self, *args):
            nonlocal changed
            self.stream.close()
            if not changed:
                changed = True
                with original_open(source, "wb") as writer:
                    writer.write(raw + b"\n")
    def opening(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        return ChangingReader(stream) if path == source and mode in ("r", "rb") else stream
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", opening)
        with pytest.raises(FeedbackImportError) as caught:
            imported(source, digest)
    assert changed and caught.value.code == "feedback_source_changed" and snapshot() == before


def test_import_commit_failure_retains_source_and_whole_database(storage, tmp_path):
    from app.feedback_import import FeedbackImportError, import_feedback_jsonl
    source, digest, raw = source_file(tmp_path, [legacy()]); before = snapshot()
    conn = db._connect()
    class CommitFault:
        def __getattr__(self, name):
            return getattr(conn, name)
        def commit(self):
            raise sqlite3.OperationalError("PRIVATE synthetic commit")
    try:
        with pytest.raises(FeedbackImportError):
            import_feedback_jsonl(CommitFault(), source, source_digest=digest)
    finally:
        conn.close()
    assert source.read_bytes() == raw and snapshot() == before


def test_reimport_conflicting_identity_payload_never_overwrites(storage, tmp_path):
    from app.feedback_import import FeedbackImportError
    source, digest, _ = source_file(tmp_path, [legacy()])
    imported(source, digest)
    conn = db._connect()
    conn.execute("UPDATE feedback_items SET payload_json='{}'"); conn.commit(); conn.close()
    before = snapshot()
    with pytest.raises(FeedbackImportError) as caught:
        imported(source, digest)
    assert caught.value.code == "feedback_import_conflict" and snapshot() == before


def test_old_merge_labels_kept_as_history_not_rule_or_cloud_permission(storage, tmp_path):
    from app.feedback_store import list_feedback
    source, digest, _ = source_file(tmp_path, [legacy(mergedAt="2026-10-08T00:02:00Z", mergedAnswer="不是")])
    assert imported(source, digest).imported == 1
    row = rows("feedback_items")[0]
    origin = json.loads(row["source_json"])
    assert origin["legacyHistory"]["mergedAnswer"] == "不是"
    # Imported timestamps stay historical; this test is not a rolling-window test.
    page = list_feedback(start=row["created_at"] - 1, end=row["created_at"] + 1)
    assert page.totalInRange == 1
    assert page.feedbacks[0].mergedAnswer is None
    assert not page.feedbacks[0].safeForModel
