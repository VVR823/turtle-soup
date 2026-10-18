"""Bounded local pending intent, not durable Agent tasks or a worker scheduler."""
from threading import Lock


class PendingAgentQueue:
    def __init__(self, *, capacity: int = 10):
        if type(capacity) is not int or not 1 <= capacity <= 10:
            raise ValueError("Pending Agent capacity must be between 1 and 10")
        self._capacity = capacity
        self._pending = {}
        self._lock = Lock()

    def enqueue(self, operation_key: str, payload_digest: str) -> bool:
        with self._lock:
            if operation_key in self._pending:
                if self._pending[operation_key] != payload_digest:
                    raise ValueError("Pending operation payload conflict")
                return True
            if len(self._pending) >= self._capacity:
                return False
            self._pending[operation_key] = payload_digest
            return True

    def cancel(self, operation_key: str) -> bool:
        with self._lock:
            if operation_key not in self._pending:
                return False
            del self._pending[operation_key]
            return True

    def snapshot(self) -> dict:
        with self._lock:
            return {"queued": len(self._pending), "capacity": self._capacity}
