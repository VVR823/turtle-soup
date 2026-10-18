"""Pure monotonic rate accounting; no runtime/request/file/network on import."""
import math
import time
from collections import deque
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class RatePolicy:
    id: str
    limit: int
    window: float

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id or len(self.id) > 128:
            raise ValueError("Invalid rate policy identity")
        if type(self.limit) is not int or self.limit < 1:
            raise ValueError("Rate limit must be a positive integer")
        if (isinstance(self.window, bool) or not isinstance(self.window, (int, float))
                or not math.isfinite(self.window) or self.window <= 0):
            raise ValueError("Rate window must be positive and finite")


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retryAfterSeconds: int = 0


class SlidingWindowLimiter:
    """All request policies admitted atomically, without evicting active hits."""

    def __init__(self, *, clock=time.monotonic, max_keys=4096):
        if type(max_keys) is not int or max_keys < 1:
            raise ValueError("Rate key capacity must be a positive integer")
        self._clock = clock
        self._capacity = max_keys
        self._hits: dict[tuple, deque] = {}
        self._lock = Lock()

    def _prune(self, key, now):
        hits = self._hits.get(key)
        if hits is not None:
            while hits and hits[0] <= now - key[-1]:
                hits.popleft()
        return hits

    def _reclaim(self, now):
        # Scan only under key-capacity pressure. This has a fixed maximum size,
        # not one ever-growing heap entry for each admitted HTTP request.
        for key in tuple(self._hits):
            if not self._prune(key, now):
                del self._hits[key]

    def check(self, identity: str, endpoint: str, policies) -> RateDecision:
        if not isinstance(identity, str) or not identity or not isinstance(endpoint, str) or not endpoint:
            raise ValueError("Rate identity and endpoint must be nonempty strings")
        selected = tuple(dict.fromkeys(policies))
        if not selected or any(not isinstance(policy, RatePolicy) for policy in selected):
            raise ValueError("Rate policies must be a nonempty set of RatePolicy")
        keys = tuple((identity, endpoint, policy.id, policy.limit, policy.window) for policy in selected)
        if len(keys) > self._capacity:
            raise ValueError("Rate policy set exceeds key capacity")
        with self._lock:
            now = self._clock()
            if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
                raise ValueError("Rate clock must be finite")
            delay = 0
            for key in keys:
                hits = self._prune(key, now)
                if hits and len(hits) >= key[-2]:
                    delay = max(delay, math.ceil(hits[0] + key[-1] - now))
            new = sum(key not in self._hits for key in keys)
            if len(self._hits) + new > self._capacity:
                self._reclaim(now)
                requested = set(keys)
                expiries = sorted(hits[-1] + key[-1] for key, hits in self._hits.items()
                                  if key not in requested)
                # Every requested policy needs a slot again even if its old
                # bucket expires. Only nonrequested expiry releases net room.
                needed = len(expiries) - (self._capacity - len(keys))
                if needed > 0:
                    delay = max(delay, math.ceil(expiries[needed - 1] - now))
            if delay:
                return RateDecision(False, max(1, delay))
            for key in keys:
                self._hits.setdefault(key, deque()).append(now)
            return RateDecision(True)

    def allow(self, key: str, limit: int, window: float) -> bool:
        policy = RatePolicy(f"legacy:{limit}:{window}", limit, window)
        return self.check(key, "legacy", (policy,)).allowed

    def snapshot(self) -> dict:
        with self._lock:
            return {"keys": len(self._hits), "capacity": self._capacity}
