"""Owned contexts, real copied threads, and sealed observations; no provider."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import Event

from app.audit_context import AttemptCollector, attempt_context, current_attempt
from app.audit_events import ModelCallObservation, TokenUsage
from app.schemas import HostResult, HostVersions

ID_A = "802939c0-e6de-414f-b8b9-121511a8a025"
ID_B = "e4d001de-2da8-484e-9a02-78a01609cbbb"
REQUEST = "29ab9f58-d899-41dd-a2ab-8e7b3667c9f1"


def finish(collector, **changes):
    args = dict(status_code=200, method="POST", route_template="/api/chat", response_started=True, disconnected=False)
    args.update(changes)
    return collector.finish(**args)


def test_same_request_id_has_distinct_event_ids_and_context_restores():
    first, second = AttemptCollector(ID_A), AttemptCollector(ID_B)
    assert current_attempt() is None
    with attempt_context(first):
        assert first.bind_ids(request_id=REQUEST, session_id="session-a") is True
        with attempt_context(second):
            assert current_attempt() is second
            assert second.bind_ids(request_id=REQUEST, session_id="session-a") is True
        assert current_attempt() is first
    assert current_attempt() is None
    a, b = finish(first), finish(second)
    assert a.eventId != b.eventId and a.requestId == b.requestId == REQUEST


def test_concurrent_copied_thread_contexts_never_cross_contaminate():
    release = Event(); entered = [Event(), Event()]
    collectors = [AttemptCollector(ID_A), AttemptCollector(ID_B)]
    def worker(index):
        entered[index].set(); assert release.wait(2)
        assert current_attempt() is collectors[index]
        assert current_attempt().bind_ids(session_id=f"session-{index}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = []
        for index, collector in enumerate(collectors):
            with attempt_context(collector):
                context = copy_context()
            futures.append(pool.submit(context.run, worker, index))
        try:
            assert all(mark.wait(2) for mark in entered)
        finally:
            release.set()
        for future in futures:
            future.result(timeout=2)
    assert [finish(c).sessionId for c in collectors] == ["session-0", "session-1"]


def test_finish_seals_and_returns_same_snapshot_despite_late_model_and_id_updates():
    collector = AttemptCollector(ID_A)
    assert collector.observe_model(ModelCallObservation(ordinal=1, status="started"))
    item = finish(collector, status_code=None, response_started=False, disconnected=True)
    original = item.model_dump_json()
    assert collector.observe_model(ModelCallObservation(ordinal=1, status="succeeded", usageStatus="partial", usage=TokenUsage(totalTokens=9))) is False
    assert collector.bind_ids(session_id="late-session") is False
    assert finish(collector) is item
    assert item.model_dump_json() == original
    assert item.details.modelCalls[0].status == "started"
    assert item.details.usage.totalTokens is None


def test_program_host_metadata_excludes_reply_and_short_reason_is_not_reasoning():
    collector = AttemptCollector(ID_A)
    host = HostResult(kind="answer", answer="是", chargeable=True, source="deterministic", evidenceIds=("fact:a",),
                      cacheHit=True, versions=HostVersions(puzzleVersion="p1:synthetic", ruleVersion="r1:synthetic"), reply="synthetic private answer")
    assert collector.observe_host(host, turn_id="turn-a", versions=host.versions, replayed=True)
    item = finish(collector)
    assert item.turnId == "turn-a" and item.details.source == "deterministic"
    assert item.details.charged is True and item.details.cacheHit is True and item.details.replayed is True
    assert item.details.reasonCode == "answer"
    assert item.details.evidenceIds == ("fact:a",)
    assert "synthetic private answer" not in item.model_dump_json()


def test_two_attempts_one_unknown_keeps_total_unknown_and_known_call_visible():
    collector = AttemptCollector(ID_A)
    assert collector.observe_model(ModelCallObservation(ordinal=1, status="succeeded", usageStatus="known", usage=TokenUsage(inputTokens=12, outputTokens=3, totalTokens=15)))
    assert collector.observe_model(ModelCallObservation(ordinal=2, status="failed", errorCode="model_transport_error"))
    item = finish(collector)
    assert item.details.usage.totalTokens is None
    assert item.details.modelCalls[0].usage.totalTokens == 15
    assert len(item.details.modelCalls) == 2


def test_completed_observation_replaces_its_started_slot_not_an_extra_call():
    collector = AttemptCollector(ID_A)
    assert collector.observe_model(ModelCallObservation(ordinal=1, status="started"))
    assert collector.observe_model(ModelCallObservation(ordinal=1, status="succeeded", usageStatus="known", usage=TokenUsage(inputTokens=2, outputTokens=3, totalTokens=5)))
    item = finish(collector)
    assert len(item.details.modelCalls) == 1 and item.details.modelCalls[0].status == "succeeded"
    assert item.details.usage.totalTokens == 5


def test_oversized_evidence_is_bounded_with_actual_truncation_count():
    collector = AttemptCollector(ID_A)
    ids = tuple(f"{i:03d}:" + "x" * 190 for i in range(150))
    host = HostResult(kind="answer", answer="是", chargeable=True, source="deterministic", evidenceIds=ids, reply="是")
    collector.observe_host(host, turn_id="turn-a", versions=host.versions)
    item = finish(collector)
    assert len(item.model_dump_json().encode("utf-8")) <= 16384
    assert len(item.details.evidenceIds) < 128
    assert item.details.evidenceCount == 150 and item.details.evidenceTruncated is True
    assert set(item.details.evidenceIds) <= set(ids)


def test_unknown_status_and_unregistered_raw_route_do_not_become_success_or_leak():
    collector = AttemptCollector(ID_A)
    item = finish(collector, status_code=None, response_started=False, route_template="/api/session/private-player?token=private")
    assert item.details.statusCode is None and item.details.outcome == "error"
    assert item.details.routeTemplate == "unmatched"
    assert "private-player" not in item.model_dump_json() and "token=" not in item.model_dump_json()


def test_metadata_hook_failure_is_explicit_and_late_gap_notes_cannot_mutate_snapshot():
    collector = AttemptCollector(ID_A)
    assert collector.note_metadata_gap() is True
    item = finish(collector); before = item.model_dump_json()
    assert item.details.metadataTruncated is True
    assert collector.note_metadata_gap() is False and item.model_dump_json() == before


def test_refused_model_observation_marks_missing_coverage_instead_of_silent_drop():
    collector = AttemptCollector(ID_A)
    assert collector.observe_model(ModelCallObservation(ordinal=1, status="succeeded"))
    assert collector.observe_model(ModelCallObservation(ordinal=1, status="started")) is False
    item = finish(collector)
    assert item.details.modelCallsTruncated is True and len(item.details.modelCalls) == 1


def test_conflicting_association_is_refused_atomically_and_visible():
    collector = AttemptCollector(ID_A)
    assert collector.bind_ids(session_id="original")
    assert collector.bind_ids(session_id="foreign", request_id=REQUEST) is False
    item = finish(collector)
    assert item.sessionId == "original" and item.requestId is None
    assert item.details.metadataTruncated is True
