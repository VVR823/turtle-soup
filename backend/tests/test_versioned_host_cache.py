"""Bounded pure-result cache; no provider/player state or semantic oracle."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import importlib
import importlib.util
import json
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import ai_host, db
from app.config import Settings
from app.main import create_app
from app.runtime import runtime_context
from app.schemas import Checkpoint, ConfusionPoint, DifficultyLimits, HostResult, HostVersions, Soup
from app.testing import FakeModel


def api():
    assert importlib.util.find_spec("app.host_cache") is not None, "Missing versioned bounded host cache"
    return importlib.import_module("app.host_cache")


def key(question="小明是凶手", **changes):
    return api().HostCacheKey(**{
        "soupId": "synthetic", "puzzleVersion": "p1:" + "a" * 64,
        "ruleVersion": "r1:" + "b" * 64, "engineVersion": "host-v3",
        "normalizationVersion": "exact-v1", "questionKey": question, **changes,
    })


def pure(selected=None, **changes):
    selected = selected or key()
    versions = HostVersions(**{name: getattr(selected, name) for name in
                               ("puzzleVersion", "ruleVersion", "engineVersion", "normalizationVersion")})
    return HostResult(**{
        "kind": "answer", "answer": "是", "reply": "是", "chargeable": True,
        "source": "deterministic", "contextIndependent": True, "cacheHit": False,
        "evidenceIds": ("f1:" + "c" * 64,), "matchedCheckpoint": "rule1:" + "d" * 64,
        "versions": versions, **changes,
    })


def test_default_capacity_1024_plus_one_evicts_exact_least_recently_used():
    cache = api().DeterministicHostCache()
    keys = [key(f"问题{i}") for i in range(1025)]
    for selected in keys[:1024]:
        assert cache.put(selected, pure(selected)) is True
    assert cache.get(keys[0]).cacheHit is True
    assert cache.put(keys[-1], pure(keys[-1]))
    assert cache.snapshot()["entries"] == 1024
    assert cache.get(keys[1]) is None
    assert cache.get(keys[0]) is not None and cache.get(keys[-1]) is not None


def test_insertion_ttl_599_999_hit_600_miss_access_does_not_renew():
    now = [0.0]
    cache = api().DeterministicHostCache(clock=lambda: now[0])
    assert cache.put(key(), pure())
    now[0] = 599.999
    assert cache.get(key()).cacheHit is True
    now[0] = 600
    assert cache.get(key()) is None and cache.snapshot()["entries"] == 0


@pytest.mark.parametrize("field,value", [
    ("soupId", "other"), ("puzzleVersion", "p1:" + "e" * 64),
    ("ruleVersion", "r1:" + "f" * 64), ("engineVersion", "host-v4"),
    ("normalizationVersion", "exact-v2"), ("questionKey", "小明不是凶手"),
])
def test_every_identity_and_version_dimension_isolated(field, value):
    cache = api().DeterministicHostCache()
    assert cache.put(key(), pure())
    assert cache.get(replace(key(), **{field: value})) is None
    assert cache.get(key()) is not None


def test_caller_input_and_each_hit_are_independent_copies():
    cache = api().DeterministicHostCache()
    result = pure()
    assert cache.put(key(), result)
    object.__setattr__(result, "reply", "mutated caller")
    hit = cache.get(key())
    assert hit.reply == "是" and hit is not result
    object.__setattr__(hit, "reply", "mutated hit")
    assert cache.get(key()).reply == "是" and cache.get(key()) is not hit


@pytest.mark.parametrize("changes", [
    {"source": "llm"}, {"contextIndependent": False}, {"evidenceIds": ()},
    {"matchedCheckpoint": "always_yes"}, {"matchedCheckpoint": "display marker only"},
    {"kind": "reminder", "answer": None, "chargeable": False},
    {"kind": "win", "answer": None},
    {"kind": "system_error", "answer": None, "chargeable": False,
     "source": "llm", "errorCode": "model_timeout"},
    {"versions": HostVersions()},
])
def test_llm_state_flow_special_modes_and_unversioned_results_never_cached(changes):
    cache = api().DeterministicHostCache()
    assert cache.put(key(), pure(**changes)) is False
    assert cache.get(key()) is None and cache.snapshot()["entries"] == 0


def test_revalidate_copied_invalid_decision_and_refuse_untyped_value():
    cache = api().DeterministicHostCache()
    assert cache.put(key(), pure().model_copy(update={"chargeable": False})) is False
    assert cache.put(key(), pure().model_dump()) is False
    assert cache.put(key(), None) is False
    assert cache.snapshot()["entries"] == 0


@pytest.mark.parametrize("options", [{"capacity": 0}, {"capacity": True}, {"capacity": 1025},
                                     {"ttl_seconds": 0}, {"ttl_seconds": float("nan")},
                                     {"ttl_seconds": float("inf")}, {"ttl_seconds": True}])
def test_invalid_or_unbounded_cache_configuration_refused(options):
    with pytest.raises(ValueError):
        api().DeterministicHostCache(**options)


@pytest.mark.parametrize("clock_value", [float("nan"), float("inf"), True, "0"])
def test_invalid_runtime_clock_value_is_refused_before_cache_state_changes(clock_value):
    cache = api().DeterministicHostCache(clock=lambda: clock_value)
    with pytest.raises(ValueError, match="Invalid cache clock"):
        cache.snapshot()


def test_forty_concurrent_put_get_operations_remain_bounded_and_clearable():
    cache = api().DeterministicHostCache(capacity=16)
    gate = Barrier(40)

    def work(index):
        selected = key(f"问题{index}")
        gate.wait(timeout=5)
        assert cache.put(selected, pure(selected))
        value = cache.get(selected)
        assert value is None or (value.cacheHit and value.reply == "是")

    with ThreadPoolExecutor(max_workers=40) as pool:
        list(pool.map(work, range(40)))
    assert 0 <= cache.snapshot()["entries"] <= 16
    cache.clear()
    assert cache.snapshot()["entries"] == 0


def selected_soup():
    return Soup(id="synthetic", title="Synthetic", surface="小明、小红。",
                bottom="Synthetic: 小明活着，是凶手；小红死了，不是凶手。",
                checkpoints=[Checkpoint(key="小明是凶手", answer=True)],
                confusionPoints=[ConfusionPoint(q="他死了吗", a="是", match=["死"])],
                difficultyLimits=DifficultyLimits(xuermu=4, baozi=4, tianyi=4))


def start(client):
    return client.post("/api/chat", json={"soupId": "synthetic"}).json()["sessionId"]


def ask(client, sid, question, request_id=None):
    response = client.post("/api/chat", json={"sessionId": sid, "question": question,
                                             "requestId": request_id or str(uuid4())})
    assert response.status_code == 200, response.text
    return response


def results(active):
    with runtime_context(active), closing(db._connect()) as conn, conn:
        return [json.loads(row[0]) for row in conn.execute("SELECT result_json FROM turns ORDER BY rowid")]


def test_pure_hit_charges_each_session_once_and_replays_own_remaining(tmp_path):
    app = create_app(Settings.for_test(tmp_path), model=FakeModel("不是"), soups=[selected_soup()])
    with TestClient(app) as client:
        a, b = start(client), start(client)
        ask(client, a, "小红是凶手吗？")
        first = ask(client, a, "小明是凶手吗？")
        request_id = str(uuid4())
        second = ask(client, b, "小明是凶手吗？", request_id)
        assert first.json()["remaining"] == 2 and second.json()["remaining"] == 3
        assert ask(client, b, "小明是凶手吗？", request_id).content == second.content
        stored = results(app.state.runtime)
        assert stored[-2]["cacheHit"] is False and stored[-1]["cacheHit"] is True
        assert stored[-1]["contextIndependent"] is True and stored[-1]["versions"]["engineVersion"] == "host-v3"
        assert client.get(f"/api/session/{a}").json()["questionsAsked"] == 2
        assert client.get(f"/api/session/{b}").json()["questionsAsked"] == 1
        assert len(app.state.runtime.model.calls) == 1


def test_opposite_pronoun_histories_and_model_results_never_cross_session_cache(tmp_path):
    app = create_app(Settings.for_test(tmp_path), model=FakeModel(), soups=[selected_soup()])
    with TestClient(app) as client:
        a, b = start(client), start(client)
        model = app.state.runtime.model
        model.answer = "是"
        ask(client, a, "下面他指的是小明，对吗？")
        ask(client, b, "下面他指的是小红，对吗？")
        model.answer = "不是"
        assert ask(client, a, "他死了吗？").json()["reply"] == "不是"
        model.answer = "是"
        assert ask(client, b, "他死了吗？").json()["reply"] == "是"
        assert all(result["cacheHit"] is False for result in results(app.state.runtime))
        assert len(model.calls) == 4
        assert "小明" in model.calls[-2][1]["content"] and "小红" in model.calls[-1][1]["content"]
        assert app.state.runtime.deterministic_host_cache.snapshot()["entries"] == 0


def test_service_supplies_frozen_versions_before_host_not_after(tmp_path, monkeypatch):
    seen = []

    def host(soup, history, question, *, versions=None):
        assert versions is not None and versions.puzzleVersion.startswith("p1:")
        assert versions.ruleVersion.startswith("r1:") and versions.engineVersion == "host-v3"
        seen.append(versions)
        return HostResult(kind="answer", answer="是", reply="是", chargeable=True,
                          source="llm", versions=versions)

    monkeypatch.setattr(ai_host, "handle_host_response", host)
    app = create_app(Settings.for_test(tmp_path), model=FakeModel(), soups=[selected_soup()])
    with TestClient(app) as client:
        assert ask(client, start(client), "小明是凶手吗？").json()["reply"] == "是"
        assert len(seen) == 1


def test_saved_host_v2_response_without_new_flags_replays_unchanged(tmp_path):
    app = create_app(Settings.for_test(tmp_path), model=FakeModel("是"), soups=[selected_soup()])
    with TestClient(app) as client:
        sid, request_id = start(client), str(uuid4())
        saved = ask(client, sid, "小明是凶手吗？", request_id)
        with runtime_context(app.state.runtime), closing(db._connect()) as conn, conn:
            row = conn.execute("SELECT * FROM turns WHERE request_id=?", (request_id,)).fetchone()
            old = json.loads(row["result_json"])
            old["versions"]["engineVersion"] = "host-v2"
            old.pop("cacheHit", None)
            old.pop("contextIndependent", None)
            encoded = json.dumps(old, ensure_ascii=False)
            conn.execute("UPDATE turns SET engine_version='host-v2',result_json=? WHERE id=?", (encoded, row["id"]))
            conn.commit()
        assert ask(client, sid, "小明是凶手吗？", request_id).content == saved.content
        with runtime_context(app.state.runtime), closing(db._connect()) as conn, conn:
            assert conn.execute("SELECT result_json FROM turns WHERE id=?", (row["id"],)).fetchone()[0] == encoded
        assert client.get(f"/api/session/{sid}").json()["questionsAsked"] == 1


def test_default_program_flags_are_false_not_inferred_from_marker():
    result = HostResult(kind="answer", answer="是", reply="是", chargeable=True,
                        source="deterministic", matchedCheckpoint="rule1:" + "d" * 64)
    assert result.cacheHit is False and result.contextIndependent is False


def test_put_rejects_key_result_version_mismatch_and_malformed_keys():
    cache = api().DeterministicHostCache()
    assert cache.put(key(ruleVersion="r1:" + "e" * 64), pure()) is False
    for invalid in (None, {}, "marker", key(puzzleVersion="unversioned")):
        assert cache.put(invalid, pure()) is False
        assert cache.get(invalid) is None
    assert cache.snapshot()["entries"] == 0


def test_actual_snapshot_mismatch_refused_even_with_warm_cache(runtime, tmp_path):
    from app.baselines import SnapshotError
    from .test_host_evidence import pin
    selected, version = pin(tmp_path / "pin", selected_soup())
    versions = HostVersions(puzzleVersion=version, ruleVersion="r1:" + "b" * 64)
    result = ai_host.handle_host_response(selected, [], "小明是凶手吗？", versions=versions)
    assert result.source == "deterministic"
    assert ai_host.handle_host_response(selected, [], "小明是凶手吗？", versions=versions).cacheHit
    modified = selected.model_copy(update={"bottom": "Different synthetic truth."})
    with pytest.raises(SnapshotError):
        ai_host.handle_host_response(modified, [], "小明是凶手吗？", versions=versions)


def test_unversioned_internal_rule_calls_do_not_fill_runtime_cache(runtime):
    selected = selected_soup()
    for _ in range(2):
        result = ai_host.handle_host_response(selected, [], "小明是凶手吗？")
        assert result.source == "deterministic" and result.cacheHit is False
    assert runtime.deterministic_host_cache.snapshot()["entries"] == 0


def test_empty_history_narrator_qa_cannot_prime_a_later_history_cache(tmp_path):
    selected = selected_soup().model_copy(update={"surface": "我是故事叙述者。", "checkpoints": [],
                                                 "confusionPoints": [ConfusionPoint(q="我是凶手吗", a="是")]})
    app = create_app(Settings.for_test(tmp_path), model=FakeModel("不是"), soups=[selected])
    with TestClient(app) as client:
        sid = start(client)
        assert ask(client, sid, "我是凶手吗？").json()["reply"] == "是"
        assert ask(client, sid, "我是凶手吗？").json()["reply"] == "不是"
        stored = results(app.state.runtime)
        assert all(not result["contextIndependent"] and not result["cacheHit"] for result in stored)
        assert len(app.state.runtime.model.calls) == 1
        assert app.state.runtime.deterministic_host_cache.snapshot()["entries"] == 0


def test_pinned_model_context_has_source_ids_full_truth_and_original_history(tmp_path):
    app = create_app(Settings.for_test(tmp_path), model=FakeModel("是"), soups=[selected_soup()])
    with TestClient(app) as client:
        sid = start(client)
        ask(client, sid, "下面他指的是小红，对吗？")
        ask(client, sid, "他死了吗？")
        content = app.state.runtime.model.calls[-1][1]["content"]
        assert selected_soup().bottom in content and "下面他指的是小红" in content
        assert "source=confusionPoints[0]" in content and "id=f1:" in content
        assert sum(len(message["content"]) for message in app.state.runtime.model.calls[-1]) <= 8000


def test_runtime_shutdown_clears_only_its_owned_new_cache(tmp_path):
    app = create_app(Settings.for_test(tmp_path), model=FakeModel(), soups=[selected_soup()])
    with TestClient(app) as client:
        ask(client, start(client), "小明是凶手吗？")
        active = app.state.runtime
        assert active.deterministic_host_cache.snapshot()["entries"] == 1
    assert active.closed and active.deterministic_host_cache.snapshot()["entries"] == 0


def test_expiration_aggregate_counted_once_by_get_or_snapshot():
    now = [0]
    cache = api().DeterministicHostCache(clock=lambda: now[0])
    cache.put(key("甲"), pure(key("甲")))
    cache.put(key("乙"), pure(key("乙")))
    assert cache.snapshot()["expirations"] == 0
    now[0] = 600
    assert cache.get(key("甲")) is None
    assert cache.snapshot()["expirations"] == 2
    assert cache.snapshot()["expirations"] == 2 and cache.get(key("乙")) is None


def test_get_revalidates_corrupt_owned_entry_instead_of_returning_invalid_answer():
    cache = api().DeterministicHostCache()
    cache.put(key(), pure())
    # Defensive developer/storage corruption probe, not a public mutation API.
    expires, value = cache._entries[key()]
    cache._entries[key()] = (expires, value.model_copy(update={"chargeable": False}))
    assert cache.get(key()) is None and cache.snapshot()["entries"] == 0
