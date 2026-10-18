"""Real archived algorithms behind case-owned offline budgets, not gold oracles."""
import time
import pytest
from app.config import Settings
from app.schemas import HostVersions
from app.testing import FakeModel
from eval.contracts import DatasetError
from eval.frozen_old_driver import FrozenOldDriver, frozen_old_system_spec
from eval.run_contracts import EvaluationInput, HistoryTurn
from .support import ScriptedFakeModel, answer_json, small_snapshot


def request(catalog, *, attempts=2, timeout=45.0, history=(), question="灯已经灭了吗？"):
    spec = frozen_old_system_spec("与此无关")
    spec = spec.model_copy(update={"budget": spec.budget.model_copy(update={
        "modelAttemptsPerCase": attempts, "caseTimeoutSeconds": timeout})})
    return EvaluationInput(caseId="00000000-0000-0000-0000-000000000001",
        soupId=catalog[0].soupId, puzzleVersion=catalog[0].puzzleVersion,
        puzzle=catalog[0], question=question, history=history, system=spec)


def invoke(catalog, tmp_path, outputs, **options):
    model = ScriptedFakeModel(outputs)
    driver = FrozenOldDriver(settings=Settings.for_test(tmp_path), fake_model=model)
    try:
        outcome = driver.decide(request(catalog, **options), deadline=time.monotonic()+5)
    finally:
        assert driver.close()
    return outcome, model


def test_old_invalid_label_remains_the_actual_normalization_defect(catalog, tmp_path):
    # Substituting the modern parser would reject this; old parser really accepts it.
    outcome, model = invoke(catalog, tmp_path, ('{"answer":"nonsense","reasoning":"synthetic"}',))
    assert outcome.host is not None and outcome.host.answer == "与此无关"
    assert outcome.host.source == "legacy" and outcome.modelAttemptCount == len(model.calls) == 1
    assert outcome.host.versions.engineVersion == "host-ts01-frozen-v1"
    assert outcome.modelObservations[0].usageStatus == "unknown"
    assert outcome.modelObservations[0].usage.totalTokens is None


def test_old_parse_fallback_gets_raw_second_call_with_case_ordinals(catalog, tmp_path, capsys):
    # Strict new parsing or one collector shared across both invocations hides the defect/accounting.
    outcome, model = invoke(catalog, tmp_path, ("PRIVATE-SYNTHETIC-PARSER-ERROR", "不是"))
    assert outcome.host is not None and outcome.host.answer == "不是"
    assert outcome.modelAttemptCount == len(model.calls) == 2
    assert [o.ordinal for o in outcome.modelObservations] == [1, 2]
    assert [o.status for o in outcome.modelObservations] == ["failed", "succeeded"]
    assert outcome.modelObservations[0].errorCode == "model_output_invalid"
    captured = capsys.readouterr()
    assert "PRIVATE-SYNTHETIC" not in captured.out + captured.err


def test_one_case_budget_refuses_the_old_second_dispatch(catalog, tmp_path):
    # Per-invoke resetting of budget illegally grants a second call.
    outcome, model = invoke(catalog, tmp_path, ("not-json", "不是"), attempts=1)
    assert outcome.host is None and outcome.errorCode == "model_output_invalid"
    assert outcome.modelAttemptCount == len(model.calls) == 1 and outcome.cleanupComplete


def test_old_actual_window_is_five_complete_turns_not_new_twelve(catalog, tmp_path):
    spec = frozen_old_system_spec("与此无关")
    versions = HostVersions(puzzleVersion=catalog[0].puzzleVersion,
        ruleVersion=catalog[0].ruleSnapshot.ruleVersion, engineVersion=spec.engineVersion)
    history = tuple(HistoryTurn(question=f"marker-{n:02d}吗？", answer="不是", versions=versions) for n in range(14))
    outcome, model = invoke(catalog, tmp_path, (answer_json(),), history=history)
    assert len(model.calls) == 1
    prompt = model.calls[0][1]["content"]
    assert all(f"marker-{n:02d}" not in prompt for n in range(9))
    assert all(f"marker-{n:02d}" in prompt for n in range(9, 14))
    assert outcome.contextTurnsIncluded == 5 and len(history) == 14
    assert outcome.inputChars == sum(len(m["content"]) for m in model.calls[0]) <= 8000


@pytest.mark.parametrize("changes", [{"ALLOW_REAL_MODEL": True}, {"TESTING": False},
    {"LOAD_RUNTIME_PUZZLES": True}, {"LLM_PROVIDER": "ollama"}])
def test_refuses_nonoffline_settings_before_initializing_old_runtime(tmp_path, changes):
    model = FakeModel()
    with pytest.raises(DatasetError, match="eval_offline_driver_required"):
        FrozenOldDriver(settings=Settings.for_test(tmp_path, **changes), fake_model=model)
    assert model.calls == []


def test_refuses_nonfake_before_initialization(tmp_path):
    with pytest.raises(DatasetError, match="eval_offline_driver_required"):
        FrozenOldDriver(settings=Settings.for_test(tmp_path), fake_model=object())


def test_expired_deadline_is_unattempted_without_model(catalog, tmp_path):
    model = FakeModel()
    driver = FrozenOldDriver(settings=Settings.for_test(tmp_path), fake_model=model)
    try:
        outcome = driver.decide(request(catalog), deadline=time.monotonic()-1)
        assert outcome.errorCode == "budget_exhausted" and not outcome.decisionAttempted
        assert outcome.modelAttemptCount == 0 and not model.calls
    finally:
        assert driver.close()


def test_forged_system_identity_never_dispatches(catalog, tmp_path):
    model = FakeModel()
    driver = FrozenOldDriver(settings=Settings.for_test(tmp_path), fake_model=model)
    input = request(catalog)
    input = input.model_copy(update={"system": input.system.model_copy(update={"implementationDigest": "0"*64})})
    try:
        with pytest.raises(DatasetError, match="eval_driver_scope_mismatch"):
            driver.decide(input, deadline=time.monotonic()+5)
        assert not model.calls
    finally:
        assert driver.close()


def test_blocked_old_worker_keeps_ownership_and_full_case_denominator(reviewed, catalog, tmp_path):
    # A timeout cannot release the worker slot or turn remaining rows into success.
    from eval.runner import run_dataset
    model = ScriptedFakeModel(("BLOCK", answer_json(), answer_json()))
    driver = FrozenOldDriver(settings=Settings.for_test(tmp_path), fake_model=model)
    try:
        report = run_dataset(small_snapshot(reviewed, catalog, groups=1, standalone=False),
            system=request(catalog, timeout=0.2).system, driver=driver, repeat_index=0, repeat_count=1)
        assert report.metrics.total == 3 and report.metrics.notAttemptedCount == 2 and not report.complete
        assert report.records[0].errorCode == "model_timeout" and report.records[0].modelAttemptCount == 1
        assert report.records[0].usageStatus == "unknown" and len(model.calls) == 1
        assert driver.gateway.snapshot()["active"] == 1 and not driver.modules.closed
    finally:
        model.release.set()
        assert driver.close()


def test_cancelled_decision_keeps_reservation_and_refuses_subsequent_cases(catalog, tmp_path, monkeypatch):
    # Interrupting the owner must not allow another decision after cleanup.
    model = FakeModel()
    driver = FrozenOldDriver(settings=Settings.for_test(tmp_path), fake_model=model)
    reservations = []
    def reserve_then_interrupt(messages, *, before_attempt, deadline, **kwargs):
        before_attempt(1, deadline)
        reservations.append(1)
        raise KeyboardInterrupt()
    monkeypatch.setattr(driver.gateway, "invoke", reserve_then_interrupt)
    input = request(catalog)
    try:
        first = driver.decide(input, deadline=time.monotonic()+5)
        assert first.errorCode == "cancelled" and first.modelAttemptCount == 1
        assert not first.modelObservations and not model.calls
        second = driver.decide(input, deadline=time.monotonic()+5)
        assert second.errorCode == "driver_unavailable" and not second.decisionAttempted
        assert second.modelAttemptCount == 0 and reservations == [1]
    finally:
        assert driver.close()


def changed_catalog(catalog, **changes):
    # Complete synthetic p1/r1 payload, not an invalid model_copy bypass.
    from app.baselines import RULE_FIELDS, canonical_json, digest, strict_json
    from app.rule_contract import RuleSnapshot
    from eval.contracts import EvalPuzzle
    payload = {**strict_json(catalog[0].soupJson), **changes}
    p1 = "p1:" + digest({"schemaVersion": 1, "soup": payload})
    rules = {"schemaVersion": 1, "rulesBySoup": {payload["id"]: {name: payload[name] for name in RULE_FIELDS}}}
    manifest = {"schemaVersion": 1, "puzzleVersions": {payload["id"]: p1}, "origin": "legacy-baseline"}
    r1 = "r1:" + digest({"rules": rules, "manifest": manifest})
    snapshot = RuleSnapshot(ruleVersion=r1, puzzleVersion=p1, soupId=payload["id"], exactRules=(),
        releaseRulesJson=canonical_json(rules), releaseManifestJson=canonical_json(manifest))
    return (EvalPuzzle(soupId=payload["id"], puzzleVersion=p1, soupJson=canonical_json(payload), ruleSnapshot=snapshot),)


def test_interrupt_of_actual_owned_gateway_keeps_observed_reservation(catalog, tmp_path, monkeypatch):
    # Actual worker dispatch/parent interrupt; not a fabricated zero-attempt cancel.
    from concurrent.futures import Future
    model = ScriptedFakeModel(("BLOCK",))
    driver = FrozenOldDriver(settings=Settings.for_test(tmp_path), fake_model=model)
    original = Future.result
    fired = []
    def interrupt(future, *args, **kwargs):
        if not fired:
            assert model.entered.wait(1)
            fired.append(True)
            model.release.set()
            raise KeyboardInterrupt("synthetic-private-owned")
        return original(future, *args, **kwargs)
    monkeypatch.setattr(Future, "result", interrupt)
    try:
        outcome = driver.decide(request(catalog), deadline=time.monotonic()+5)
        assert outcome.errorCode == "cancelled" and outcome.decisionAttempted
        assert outcome.modelAttemptCount == len(model.calls) == 1
        assert len(outcome.modelObservations) == 1 and outcome.inputChars is not None
    finally:
        model.release.set()
        assert driver.close()


def test_fixed_large_truth_is_not_truncated_into_a_dispatch(catalog, tmp_path):
    # Guard already exists: a correct-control check, not a fabricated new RED.
    puzzles = changed_catalog(catalog, bottom="SYNTHETIC-TRUTH"*900)
    outcome, model = invoke(puzzles, tmp_path, (answer_json(),))
    assert outcome.errorCode == "context_too_large" and outcome.host is None
    assert outcome.modelAttemptCount == 0 and not model.calls
    assert outcome.inputChars is None and outcome.contextTurnsIncluded is None


def test_two_old_driver_owners_keep_real_rag_bug_and_close_independently(catalog, tmp_path):
    # Replacing old RAG/normalization or sharing modules/runtime would fail this.
    puzzles = changed_catalog(catalog, checkpoints=[{"key": "门", "answer": True,
        "hint": None, "category": None, "aliases": None}])
    first = FrozenOldDriver(settings=Settings.for_test(tmp_path/"first"), fake_model=FakeModel())
    second_model = ScriptedFakeModel((answer_json("不是"),))
    second = FrozenOldDriver(settings=Settings.for_test(tmp_path/"second"), fake_model=second_model)
    try:
        assert first.modules.host is not second.modules.host and first.runtime is not second.runtime
        rag = first.decide(request(puzzles, question="没有门吗"), deadline=time.monotonic()+5)
        assert rag.host is not None and rag.host.answer == "是" and rag.modelAttemptCount == 0
        assert rag.inputChars is None and rag.contextTurnsIncluded is None
        assert first.close() and not second.modules.closed
        llm = second.decide(request(catalog), deadline=time.monotonic()+5)
        assert llm.host is not None and llm.host.answer == "不是" and len(second_model.calls) == 1
    finally:
        assert first.close() and second.close()


def test_late_actual_deterministic_result_cannot_exceed_case_deadline(catalog, tmp_path, monkeypatch):
    # A budget applied only to model transport permits late old rule decisions.
    ticks = [0.0]
    model = FakeModel()
    driver = FrozenOldDriver(settings=Settings.for_test(tmp_path), fake_model=model, clock=lambda: ticks[0])
    original = driver.modules.host.handle_host_response
    def delayed_actual_host(*args, **kwargs):
        result = original(*args, **kwargs)
        ticks[0] = 6.0
        return result
    monkeypatch.setattr(driver.modules.host, "handle_host_response", delayed_actual_host)
    try:
        outcome = driver.decide(request(catalog, question="这是本格吗？"), deadline=5.0)
        assert outcome.host is None and outcome.errorCode == "budget_exhausted"
        assert outcome.decisionAttempted and outcome.modelAttemptCount == 0
        assert not model.calls and outcome.cleanupComplete
    finally:
        assert driver.close()


@pytest.mark.parametrize("rewind_after_return", [False, True])
def test_timed_out_case_cannot_gain_a_late_reservation(catalog, tmp_path, monkeypatch, rewind_after_return):
    # Catch a reservation hook resumed after the parent has returned its ledger.
    # Pause only the hook boundary; keep the actual gateway, Future and old host.
    from concurrent.futures import Future
    from threading import Event
    from eval import frozen_old_driver as module
    entered, release = Event(), Event()
    ticks, cases = [0.0], []
    actual_case = module._RawCase
    class TrackedCase(actual_case):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            cases.append(self)
    monkeypatch.setattr(module, "_RawCase", TrackedCase)
    model = FakeModel()
    driver = FrozenOldDriver(settings=Settings.for_test(tmp_path), fake_model=model, clock=lambda: ticks[0])
    actual_invoke, actual_result = driver.gateway.invoke, Future.result
    def pause_hook(messages, *, before_attempt, **kwargs):
        def delayed_reserve(ordinal, deadline):
            entered.set()
            assert release.wait(2)
            before_attempt(ordinal, deadline)
        return actual_invoke(messages, before_attempt=delayed_reserve, **kwargs)
    def expire_parent(future, *args, **kwargs):
        assert entered.wait(1)
        ticks[0] = 6.0
        return actual_result(future, timeout=0)
    monkeypatch.setattr(driver.gateway, "invoke", pause_hook)
    monkeypatch.setattr(Future, "result", expire_parent)
    try:
        outcome = driver.decide(request(catalog), deadline=5.0)
        assert outcome.errorCode == "model_timeout" and outcome.modelAttemptCount == 0
        assert driver.gateway.snapshot()["active"] == 1 and not outcome.cleanupComplete
        assert not driver.modules.closed and not model.calls
        if rewind_after_return:
            ticks[0] = 0.0
        release.set()
        assert driver.close()
        assert cases[0].count == outcome.modelAttemptCount == 0
        assert not model.calls
    finally:
        release.set()
        assert driver.close()
