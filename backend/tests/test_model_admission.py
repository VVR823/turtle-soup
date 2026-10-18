"""Real gateway admission with scripted I/O and deterministic scheduler gates.

Breaks caught: premature owner release, queue overflow/overtaking, deadline
renewal, attempt counting before admission, and duplicate pending capacity.
Caller threads below are test drivers, not a new production executor.
"""
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Condition, Event, Lock, get_ident
import time

import pytest

from app.model_gateway import ModelFailure, ModelGateway


def eventually(predicate, timeout=3):
    stop = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < stop, "Expected bounded state transition did not occur"
        Event().wait(0.002)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class ControlledIO:
    def __init__(self):
        self.lock = Lock()
        self.started = []
        self.factory_threads = []
        self.releases = {}
        self.closed = []
        self.cleanup_entered = Event()
        self.cleanup_release = None

    def hold(self, label):
        gate = self.releases[label] = Event()
        return gate

    def factory(self):
        with self.lock:
            self.factory_threads.append(get_ident())
        fixture = self

        class Adapter:
            label = None

            def invoke(self, messages, *, deadline, cancelled):
                self.label = messages[0]
                with fixture.lock:
                    fixture.started.append((self.label, deadline))
                gate = fixture.releases.get(self.label)
                if gate is not None:
                    assert gate.wait(5), "Test-owned I/O gate was not released"
                return '{"answer":"是","reasoning":"synthetic"}'

            def request_cancel(self):
                pass  # Deliberately ignores cancellation: actual exit owns capacity.

            def close(self):
                if self.label == "first" and fixture.cleanup_release is not None:
                    fixture.cleanup_entered.set()
                    assert fixture.cleanup_release.wait(5)
                with fixture.lock:
                    fixture.closed.append(self.label)

        return Adapter()

    def release_all(self):
        for gate in self.releases.values():
            gate.set()
        if self.cleanup_release:
            self.cleanup_release.set()


def ask(runner, label, *, deadline=None, **options):
    try:
        return runner.invoke([label], deadline=deadline if deadline is not None else time.monotonic() + 4,
                             **options).answer
    except ModelFailure as error:
        return error.code


def test_two_owners_32_waiters_and_33rd_rejection_create_only_two_model_workers():
    io = ControlledIO()
    io.hold("first")
    io.hold("second")
    runner = ModelGateway(adapter_factory=io.factory)
    signals = [Event() for _ in range(32)]
    try:
        with ThreadPoolExecutor(max_workers=34) as pool:
            active = [pool.submit(ask, runner, label) for label in ("first", "second")]
            eventually(lambda: len(io.started) == 2)
            queued = [pool.submit(ask, runner, f"queued-{i}", cancelled=signal)
                      for i, signal in enumerate(signals)]
            eventually(lambda: runner.snapshot()["waiting_online"] == 32)
            assert ask(runner, "overflow") == "model_busy"
            assert len(io.factory_threads) == 2
            assert runner.snapshot()["active_online"] == 2
            assert runner.snapshot()["active_agent"] == 0
            for signal in signals:
                signal.set()
            assert [call.result(timeout=2) for call in queued] == ["model_cancelled"] * 32
            assert runner.snapshot()["waiting_online"] == 0
            io.release_all()
            assert [call.result(timeout=2) for call in active] == ["是", "是"]
    finally:
        io.release_all()
        runner.close(wait_seconds=1)
    assert len(io.factory_threads) == 2 and runner.snapshot()["active"] == 0


@pytest.mark.parametrize("deadline,advance", [(45, 10), (2, 2)])
def test_admission_wait_uses_minimum_of_ten_seconds_and_original_deadline(deadline, advance):
    io, clock, cancel = ControlledIO(), Clock(), Event()
    io.hold("first")
    runner = ModelGateway(adapter_factory=io.factory, max_active=1, clock=clock)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            active = pool.submit(ask, runner, "first", deadline=45, cancelled=cancel)
            eventually(lambda: len(io.started) == 1)
            queued = pool.submit(ask, runner, "queued", deadline=deadline)
            eventually(lambda: runner.snapshot()["waiting_online"] == 1)
            clock.now = advance
            assert queued.result(timeout=1) == "model_busy"
            assert runner.snapshot()["waiting_online"] == 0
            assert len(io.factory_threads) == 1
            io.release_all()
            assert active.result(timeout=1) == "是"
    finally:
        io.release_all()
        runner.close(wait_seconds=1)


def test_fifo_waiters_keep_original_deadline_and_cancelled_middle_does_not_block():
    io = ControlledIO()
    runner = ModelGateway(adapter_factory=io.factory, max_active=1)
    io.hold("first")
    cancelled = Event()
    deadline = time.monotonic() + 4
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            active = pool.submit(ask, runner, "first", deadline=deadline)
            eventually(lambda: len(io.started) == 1)
            one = pool.submit(ask, runner, "one", deadline=deadline)
            eventually(lambda: runner.snapshot()["waiting_online"] == 1)
            middle = pool.submit(ask, runner, "middle", deadline=deadline, cancelled=cancelled)
            eventually(lambda: runner.snapshot()["waiting_online"] == 2)
            last = pool.submit(ask, runner, "last", deadline=deadline)
            eventually(lambda: runner.snapshot()["waiting_online"] == 3)
            cancelled.set()
            assert middle.result(timeout=1) == "model_cancelled"
            io.release_all()
            assert [f.result(timeout=2) for f in (active, one, last)] == ["是"] * 3
    finally:
        io.release_all()
        runner.close(wait_seconds=1)
    assert io.started == [("first", deadline), ("one", deadline), ("last", deadline)]


def test_transport_exit_without_completed_cleanup_does_not_admit_waiter():
    io = ControlledIO()
    io.hold("first")
    io.cleanup_release = Event()
    runner = ModelGateway(adapter_factory=io.factory, max_active=1)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            active = pool.submit(ask, runner, "first")
            eventually(lambda: len(io.started) == 1)
            queued = pool.submit(ask, runner, "queued")
            eventually(lambda: runner.snapshot()["waiting_online"] == 1)
            io.releases["first"].set()
            assert io.cleanup_entered.wait(1)
            assert runner.snapshot()["active"] == 1
            assert runner.snapshot()["waiting_online"] == 1
            assert len(io.factory_threads) == 1
            io.cleanup_release.set()
            assert [active.result(timeout=1), queued.result(timeout=1)] == ["是", "是"]
    finally:
        io.release_all()
        runner.close(wait_seconds=1)


class PausedWakeCondition(Condition):
    """Make a woken admission caller lose its CPU slice, without holding lock."""
    def __init__(self):
        super().__init__()
        self.woken = Event()
        self.resume = Event()

    def wait(self, timeout=None):
        result = super().wait(timeout)
        self.release()
        try:
            self.woken.set()
            assert self.resume.wait(5)
        finally:
            self.acquire()
        return result


def test_agent_cannot_overtake_woken_online_ticket_even_when_slot_is_free():
    io = ControlledIO()
    io.hold("first")
    runner = ModelGateway(adapter_factory=io.factory, max_active=1)
    scheduler = PausedWakeCondition()
    runner._condition = scheduler
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            active = pool.submit(ask, runner, "first")
            eventually(lambda: len(io.started) == 1)
            online = pool.submit(ask, runner, "online")
            eventually(lambda: runner.snapshot()["waiting_online"] == 1)
            io.releases["first"].set()
            assert scheduler.woken.wait(1)
            assert active.result(timeout=1) == "是"
            assert runner.snapshot()["active"] == 0
            assert ask(runner, "agent", traffic_class="agent") == "model_busy"
            assert len(io.factory_threads) == 1
            scheduler.resume.set()
            assert online.result(timeout=1) == "是"
    finally:
        io.release_all()
        scheduler.resume.set()
        runner.close(wait_seconds=1)


def test_agent_owner_limit_is_one_but_online_can_use_second_shared_slot():
    io = ControlledIO()
    io.hold("agent-one")
    runner = ModelGateway(adapter_factory=io.factory)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(ask, runner, "agent-one", traffic_class="agent")
            eventually(lambda: len(io.started) == 1)
            assert ask(runner, "agent-two", traffic_class="agent") == "model_busy"
            assert ask(runner, "online") == "是"
            assert runner.snapshot()["active_agent"] == 1
            assert len(io.factory_threads) == 2
            io.release_all()
            assert first.result(timeout=1) == "是"
    finally:
        io.release_all()
        runner.close(wait_seconds=1)


@pytest.mark.parametrize("traffic", ["player", "admin", None])
def test_unknown_traffic_class_is_not_accepted_as_an_authority(traffic):
    io = ControlledIO()
    runner = ModelGateway(adapter_factory=io.factory)
    with pytest.raises(ValueError):
        runner.invoke([], deadline=time.monotonic() + 1, traffic_class=traffic)
    assert not io.factory_threads


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), "45", None, True])
def test_nonfinite_or_untyped_deadline_cannot_create_an_unbounded_owner(deadline):
    io = ControlledIO()
    runner = ModelGateway(adapter_factory=io.factory)
    try:
        with pytest.raises(ValueError):
            runner.invoke(["invalid"], deadline=deadline)
    finally:
        runner.close(wait_seconds=0.1)
    assert not io.factory_threads


def test_noncallable_budget_hook_is_refused_before_worker_creation():
    io = ControlledIO()
    runner = ModelGateway(adapter_factory=io.factory)
    with pytest.raises(ValueError):
        runner.invoke(["invalid"], deadline=time.monotonic() + 1, before_attempt="player authority")
    assert not io.factory_threads


def test_actual_attempt_hook_runs_once_per_transport_attempt_on_original_deadline():
    from .test_model_gateway import ScriptedTransport
    transport = ScriptedTransport([ModelFailure("model_transport_error", retryable=True),
                                   '{"answer":"不是","reasoning":"synthetic"}'])
    runner = ModelGateway(adapter_factory=lambda: transport)
    attempts = []
    deadline = time.monotonic() + 2
    try:
        assert runner.invoke([], deadline=deadline, before_attempt=lambda n, d: attempts.append((n, d))).answer == "不是"
    finally:
        runner.close(wait_seconds=1)
    assert attempts == [(1, deadline), (2, deadline)]
    assert transport.calls == [deadline, deadline]


def test_budget_hook_refusal_makes_no_transport_attempt_and_owner_is_cleaned():
    from .test_model_gateway import ScriptedTransport
    transport = ScriptedTransport([])
    runner = ModelGateway(adapter_factory=lambda: transport)

    def exhausted(attempt, deadline):
        raise ModelFailure("model_quota")

    try:
        assert ask(runner, "agent", traffic_class="agent", before_attempt=exhausted) == "model_quota"
    finally:
        runner.close(wait_seconds=1)
    assert not transport.calls and transport.closed == 1
    assert runner.snapshot()["active"] == 0


def test_shutdown_wakes_queued_request_without_factory_or_budget_hook():
    io, cancelled = ControlledIO(), Event()
    io.hold("first")
    runner = ModelGateway(adapter_factory=io.factory, max_active=1)
    attempts = []
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            active = pool.submit(ask, runner, "first", cancelled=cancelled)
            eventually(lambda: len(io.started) == 1)
            queued = pool.submit(ask, runner, "queued", before_attempt=lambda n, d: attempts.append((n, d)))
            eventually(lambda: runner.snapshot()["waiting_online"] == 1)
            state = runner.close(wait_seconds=0)
            assert state["active"] == 1
            assert queued.result(timeout=1) == "model_unavailable"
            assert runner.snapshot()["waiting_online"] == 0
            assert not attempts and len(io.factory_threads) == 1
            io.release_all()
            assert active.result(timeout=1) == "model_cancelled"
    finally:
        io.release_all()
        runner.close(wait_seconds=1)


def pending_type():
    assert importlib.util.find_spec("app.model_admission") is not None, "Missing bounded pending-agent primitive"
    from app.model_admission import PendingAgentQueue
    return PendingAgentQueue


def test_pending_agent_capacity_idempotency_conflict_and_exactly_once_cancel():
    queue = pending_type()()
    assert all(queue.enqueue(f"synthetic-{i}", "a" * 64) for i in range(10))
    assert queue.enqueue("synthetic-0", "a" * 64)
    with pytest.raises(ValueError):
        queue.enqueue("synthetic-0", "b" * 64)
    assert not queue.enqueue("overflow", "a" * 64)
    assert queue.snapshot() == {"queued": 10, "capacity": 10}
    assert queue.cancel("synthetic-0") and not queue.cancel("synthetic-0")
    assert queue.enqueue("replacement", "a" * 64)
    assert queue.snapshot() == {"queued": 10, "capacity": 10}


def test_pending_agent_concurrent_arrivals_cannot_exceed_capacity():
    queue = pending_type()()
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda i: queue.enqueue(f"synthetic-{i}", "a" * 64), range(50)))
    assert sum(results) == 10 and queue.snapshot()["queued"] == 10


@pytest.mark.parametrize("capacity", [0, 11, True])
def test_pending_capacity_cannot_disable_the_declared_ten_task_bound(capacity):
    with pytest.raises(ValueError):
        pending_type()(capacity=capacity)


def test_runtime_owns_separate_pending_agent_capacity_without_starting_agent(tmp_path):
    from app.config import Settings
    from app.runtime import Runtime
    first = Runtime(Settings.for_test(tmp_path / "one"))
    second = Runtime(Settings.for_test(tmp_path / "two"))
    assert first.pending_agents.enqueue("synthetic", "a" * 64)
    assert first.pending_agents.snapshot()["queued"] == 1
    assert second.pending_agents.snapshot()["queued"] == 0
    assert first.model_gateway is None and second.model_gateway is None


def test_synthetic_100_arrivals_remain_bounded_not_a_throughput_or_real_user_claim():
    io = ControlledIO()
    io.hold("first")
    io.hold("second")
    cancel = Event()
    runner = ModelGateway(adapter_factory=io.factory)
    report = {}
    try:
        with ThreadPoolExecutor(max_workers=100) as pool:
            active = [pool.submit(ask, runner, label) for label in ("first", "second")]
            eventually(lambda: len(io.started) == 2)
            arrivals = [pool.submit(ask, runner, f"synthetic-{i}", cancelled=cancel) for i in range(98)]
            eventually(lambda: sum(call.done() for call in arrivals) == 66 and runner.snapshot()["waiting_online"] == 32)
            report.update(peakOwners=runner.snapshot()["active"], peakWaiters=runner.snapshot()["waiting_online"])
            cancel.set()
            results = [call.result(timeout=2) for call in arrivals]
            io.release_all()
            successes = [call.result(timeout=2) for call in active]
            report.update(arrivals=100, admitted=successes.count("是"), refused=results.count("model_busy"),
                          cancelled=results.count("model_cancelled"), modelWorkers=len(io.factory_threads),
                          realUsers=False, throughputMeasured=False)
    finally:
        io.release_all()
        runner.close(wait_seconds=1)
    assert report == {"peakOwners": 2, "peakWaiters": 32, "arrivals": 100, "admitted": 2,
                      "refused": 66, "cancelled": 32, "modelWorkers": 2,
                      "realUsers": False, "throughputMeasured": False}
    print("SYNTHETIC_ADMISSION " + json.dumps(report, sort_keys=True))
