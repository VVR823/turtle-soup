"""One mutable collector per attempt; finishing seals copied worker contexts."""
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock

from .baselines import canonical_json
from .audit_events import AuditEvent, AttemptDetails, BusinessDetails, MAX_EVENT_BYTES, ModelCallObservation, ROUTE_TEMPLATES, TokenUsage, UUID_PATTERN
from .schemas import HostResult, HostVersions

_current: ContextVar["AttemptCollector | None"] = ContextVar("turtle_soup_audit_attempt", default=None)


def current_attempt():
    return _current.get()


@contextmanager
def attempt_context(collector):
    token = _current.set(collector)
    try:
        yield collector
    finally:
        _current.reset(token)


class AttemptCollector:
    def __init__(self, event_id: str, *, clock=time.monotonic, wall_clock=time.time, traffic_class=None):
        if not isinstance(event_id, str) or not UUID_PATTERN.fullmatch(event_id):
            raise ValueError("Attempt requires a canonical UUID")
        self._lock = RLock()
        self._event_id, self._clock = event_id, clock
        self._started, self._created = clock(), wall_clock()
        self._ids = {"requestId": None, "sessionId": None, "turnId": None, "runId": None}
        self._metadata = {"trafficClass": traffic_class}
        self._calls = []
        self._calls_truncated = False
        self._snapshot = None

    def bind_ids(self, *, request_id=None, session_id=None, turn_id=None, run_id=None):
        with self._lock:
            if self._snapshot is not None:
                return False
            values = dict(zip(self._ids, (request_id, session_id, turn_id, run_id)))
            for key, value in values.items():
                if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 200
                    or key == "requestId" and not UUID_PATTERN.fullmatch(value)):
                    # Optional metadata must not reject otherwise valid legacy
                    # history. Omit, never truncate an ID into another identity.
                    self._metadata["metadataTruncated"] = True
                    return False
                if value is not None and self._ids[key] is not None and value != self._ids[key]:
                    self._metadata["metadataTruncated"] = True
                    return False
            self._ids.update({key: value for key, value in values.items() if value is not None})
            return True

    def observe_host(self, host: HostResult, *, turn_id=None, versions: HostVersions | None = None, replayed=False):
        with self._lock:
            if self._snapshot is not None:
                return False
            if not isinstance(host, HostResult) or not self.bind_ids(turn_id=turn_id):
                return False
            ids = tuple(value for value in host.evidenceIds if isinstance(value, str) and 1 <= len(value) <= 200)[:128]
            self._metadata.update(source=host.source, kind=host.kind, charged=host.chargeable, cacheHit=host.cacheHit,
                versions=versions or host.versions, reasonCode=host.errorCode or host.kind, replayed=replayed,
                evidenceIds=ids, evidenceCount=len(host.evidenceIds), evidenceTruncated=len(ids) != len(host.evidenceIds))
            return True

    def observe_model(self, call: ModelCallObservation):
        with self._lock:
            if self._snapshot is not None:
                return False
            if not isinstance(call, ModelCallObservation):
                raise ValueError("Only validated model observations are allowed")
            index = call.ordinal - 1
            if index < len(self._calls):
                before = self._calls[index]
                if before.status != "started" or call.status == "started" or (before.provider, before.model) != (call.provider, call.model):
                    self._calls_truncated = True
                    return False
                self._calls[index] = call
            elif index == len(self._calls) and len(self._calls) < 2:
                self._calls.append(call)
            else:
                self._calls_truncated = True
                return False
            return True

    def observe_metadata(self, details: BusinessDetails, *, replayed=False):
        """Program-owned transaction/read metadata, never arbitrary body fields."""
        with self._lock:
            if self._snapshot is not None:
                return False
            checked = BusinessDetails.model_validate_json(details.model_dump_json())
            values = checked.model_dump(mode="python")
            values["metadataTruncated"] |= self._metadata.get("metadataTruncated", False)
            if values["trafficClass"] is None:
                values.pop("trafficClass")
            self._metadata.update(values, replayed=replayed)
            return True

    def note_metadata_gap(self):
        with self._lock:
            if self._snapshot is not None:
                return False
            self._metadata["metadataTruncated"] = True
            return True

    def _aggregate_usage(self):
        return TokenUsage(**{field: sum(getattr(call.usage, field) for call in self._calls)
            if self._calls and all(getattr(call.usage, field) is not None for call in self._calls) else None
            for field in ("inputTokens", "outputTokens", "totalTokens")})

    def finish(self, *, status_code, method, route_template, response_started, disconnected):
        with self._lock:
            if self._snapshot is not None:
                return self._snapshot
            status = status_code if type(status_code) is int and 100 <= status_code <= 599 else None
            outcome = "disconnected" if disconnected else "error" if status is None or status >= 500 else "rejected" if status >= 400 else "success"
            values = dict(self._metadata)
            values.update(method=method if isinstance(method, str) and re.fullmatch(r"[A-Z]{1,20}", method) else "OTHER",
                routeTemplate=route_template if route_template in ROUTE_TEMPLATES else "unmatched", statusCode=status,
                durationMs=max(0.0, (self._clock() - self._started) * 1000), outcome=outcome,
                responseStarted=response_started, disconnected=disconnected, modelCalls=tuple(self._calls),
                modelCallsTruncated=self._calls_truncated, usage=self._aggregate_usage())
            header = {"schemaVersion": 1, "eventId": self._event_id, "eventType": "http_attempt", **self._ids, "createdAt": self._created}
            # Evidence and inherited HostVersions can exceed the overall byte
            # budget. Drop only with explicit flags, never invent shorter IDs.
            while True:
                details = AttemptDetails(**values)
                if len(canonical_json({**header, "details": details.model_dump(mode="json")}).encode("utf-8")) <= MAX_EVENT_BYTES:
                    break
                if values.get("evidenceIds"):
                    values["evidenceIds"] = values["evidenceIds"][:-1]
                    values["evidenceTruncated"] = True
                elif values.get("versions") is not None:
                    values["versions"] = None
                    values["metadataTruncated"] = True
                else:
                    raise ValueError("Audit metadata cannot fit its byte budget")
            self._snapshot = AuditEvent(**header, details=details)
            return self._snapshot
