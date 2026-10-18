"""Independent monotonic policy accounting with explicit synthetic clocks."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app import rate_policy as module


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def limiter():
    clock = FakeClock()
    return module.SlidingWindowLimiter(clock=clock, max_keys=4096), clock


def policies():
    return (module.RatePolicy("minute", 30, 60), module.RatePolicy("hour", 300, 3600))


def test_minute_boundary_and_hour_history_are_independent():
    guard, clock = limiter()
    selected = policies()
    for minute in range(10):
        clock.now = minute * 60
        assert all(guard.check("synthetic-ip", "/api/chat", selected).allowed for _ in range(30))
        decision = guard.check("synthetic-ip", "/api/chat", selected)
        assert not decision.allowed and decision.retryAfterSeconds >= 1
    clock.now = 600
    decision = guard.check("synthetic-ip", "/api/chat", selected)
    assert not decision.allowed and decision.retryAfterSeconds == 3000
    clock.now = 3599.999
    assert not guard.check("synthetic-ip", "/api/chat", selected).allowed
    clock.now = 3600
    assert guard.check("synthetic-ip", "/api/chat", selected).allowed


def test_exact_minute_expiry_and_round_up_retry_after():
    guard, clock = limiter()
    selected = (module.RatePolicy("minute", 30, 60),)
    assert all(guard.check("synthetic-ip", "/api/chat", selected).allowed for _ in range(30))
    clock.now = 59.999
    decision = guard.check("synthetic-ip", "/api/chat", selected)
    assert not decision.allowed and decision.retryAfterSeconds == 1
    clock.now = 60
    assert guard.check("synthetic-ip", "/api/chat", selected).allowed


@pytest.mark.parametrize("dimension", ["identity", "endpoint", "policy"])
def test_identity_endpoint_and_policy_cannot_consume_each_other(dimension):
    guard, _ = limiter()
    one = module.RatePolicy("one", 1, 60)
    assert guard.check("synthetic-ip", "/api/chat", (one,)).allowed
    identity = "another-ip" if dimension == "identity" else "synthetic-ip"
    endpoint = "/api/evaluate" if dimension == "endpoint" else "/api/chat"
    policy = module.RatePolicy("other", 1, 60) if dimension == "policy" else one
    assert guard.check(identity, endpoint, (policy,)).allowed


def test_multi_policy_rejection_does_not_partially_consume_free_window():
    guard, _ = limiter()
    minute, hour = module.RatePolicy("minute", 30, 60), module.RatePolicy("hour", 1, 3600)
    assert guard.check("synthetic-ip", "/api/chat", (hour,)).allowed
    assert not guard.check("synthetic-ip", "/api/chat", (minute, hour)).allowed
    assert all(guard.check("synthetic-ip", "/api/chat", (minute,)).allowed for _ in range(30))
    assert not guard.check("synthetic-ip", "/api/chat", (minute,)).allowed


def test_concurrent_admission_cannot_exceed_one_policy_budget():
    guard, _ = limiter()
    gate = Barrier(40)
    selected = (module.RatePolicy("minute", 30, 60),)

    def check(_):
        gate.wait(timeout=3)
        return guard.check("synthetic-ip", "/api/chat", selected).allowed

    with ThreadPoolExecutor(max_workers=40) as pool:
        decisions = list(pool.map(check, range(40)))
    assert sum(decisions) == 30


def test_full_active_key_capacity_refuses_instead_of_forgetting_existing_budget():
    clock = FakeClock()
    guard = module.SlidingWindowLimiter(clock=clock, max_keys=2)
    one = (module.RatePolicy("one", 1, 60),)
    assert guard.check("ip-1", "/api/chat", one).allowed
    assert guard.check("ip-2", "/api/chat", one).allowed
    assert not guard.check("ip-3", "/api/chat", one).allowed
    assert not guard.check("ip-1", "/api/chat", one).allowed
    clock.now = 60
    assert guard.check("ip-3", "/api/chat", one).allowed
    assert guard.snapshot()["keys"] <= 2


def test_compatibility_allow_isolates_different_window_policies():
    guard, clock = limiter()
    assert all(guard.allow("synthetic-key", 30, 60) for _ in range(30))
    assert guard.allow("synthetic-key", 300, 3600)
    clock.now = 60
    assert all(guard.allow("synthetic-key", 30, 60) for _ in range(30))
    assert guard.allow("synthetic-key", 300, 3600)
