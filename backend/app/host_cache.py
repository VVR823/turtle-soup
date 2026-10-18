"""App-local, bounded deterministic result LRU with insertion-time expiry."""
from collections import OrderedDict
from dataclasses import dataclass
import math
import re
from threading import RLock
import time

from pydantic import ValidationError

from .schemas import HostResult


@dataclass(frozen=True, slots=True)
class HostCacheKey:
    soupId: str
    puzzleVersion: str
    ruleVersion: str
    engineVersion: str
    normalizationVersion: str
    questionKey: str


def _content_id(prefix, value):
    return isinstance(value, str) and re.fullmatch(re.escape(prefix) + r"[a-f0-9]{64}", value) is not None


def is_cacheable(host) -> bool:
    if not isinstance(host, HostResult):
        return False
    try:
        checked = HostResult.model_validate(host.model_dump(mode="python"))
    except (ValidationError, ValueError, TypeError):
        return False
    return (checked.kind == "answer" and checked.source == "deterministic"
            and checked.contextIndependent and bool(checked.evidenceIds)
            and all(_content_id("f1:", value) for value in checked.evidenceIds)
            and _content_id("rule1:", checked.matchedCheckpoint)
            and _content_id("p1:", checked.versions.puzzleVersion)
            and _content_id("r1:", checked.versions.ruleVersion)
            and checked.versions.engineVersion != "unversioned"
            and checked.versions.normalizationVersion != "unversioned")


class DeterministicHostCache:
    def __init__(self, *, capacity=1024, ttl_seconds=600, clock=time.monotonic):
        if type(capacity) is not int or not 1 <= capacity <= 1024:
            raise ValueError("Cache capacity must be an integer between 1 and 1024")
        if (type(ttl_seconds) not in {int, float} or not math.isfinite(ttl_seconds)
                or not 0 < ttl_seconds <= 600 or not callable(clock)):
            raise ValueError("Cache requires a finite TTL up to 600 seconds and a clock")
        self._capacity, self._ttl, self._clock = capacity, ttl_seconds, clock
        self._entries = OrderedDict()
        self._lock = RLock()
        self._hits = self._misses = self._evictions = self._expirations = 0

    def _now(self):
        now = self._clock()
        if type(now) not in {int, float} or not math.isfinite(now):
            raise ValueError("Invalid cache clock")
        return now

    @staticmethod
    def _valid_key(key):
        return (type(key) is HostCacheKey and all(isinstance(getattr(key, name), str)
                and getattr(key, name) for name in key.__dataclass_fields__)
                and _content_id("p1:", key.puzzleVersion) and _content_id("r1:", key.ruleVersion))

    def get(self, key):
        if not self._valid_key(key):
            return None
        with self._lock:
            now = self._now()
            saved = self._entries.get(key)
            if saved is None or now >= saved[0]:
                if saved is not None:
                    self._expirations += 1
                self._entries.pop(key, None)
                self._misses += 1
                return None
            try:
                checked = HostResult.model_validate(saved[1].model_dump(mode="python"))
            except (ValidationError, ValueError, TypeError):
                checked = None
            if (not is_cacheable(checked) or any(getattr(checked.versions, name) != getattr(key, name)
                    for name in ("puzzleVersion", "ruleVersion", "engineVersion", "normalizationVersion"))):
                self._entries.pop(key, None)
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return checked.model_copy(deep=True, update={"cacheHit": True})

    def put(self, key, result):
        if not self._valid_key(key) or not isinstance(result, HostResult):
            return False
        try:
            checked = HostResult.model_validate(result.model_dump(mode="python"))
        except (ValidationError, ValueError, TypeError):
            return False
        if not is_cacheable(checked):
            return False
        if any(getattr(checked.versions, name) != getattr(key, name) for name in
               ("puzzleVersion", "ruleVersion", "engineVersion", "normalizationVersion")):
            return False
        # Revalidation and deep copies protect against model_copy bypasses and
        # mutations of caller-held values. No session/remaining response stored.
        checked = checked.model_copy(deep=True, update={"cacheHit": False})
        with self._lock:
            self._entries[key] = (self._now() + self._ttl, checked)
            self._entries.move_to_end(key)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)
                self._evictions += 1
        return True

    def clear(self):
        with self._lock:
            self._entries.clear()

    def snapshot(self):
        with self._lock:
            now = self._now()
            for key in [key for key, (expires, _) in self._entries.items() if now >= expires]:
                del self._entries[key]
                self._expirations += 1
            return {"entries": len(self._entries), "capacity": self._capacity,
                    "hits": self._hits, "misses": self._misses, "evictions": self._evictions,
                    "expirations": self._expirations}
