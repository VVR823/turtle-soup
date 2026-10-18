"""App-local state carried across ASGI and FastAPI's copied thread context.

factory -> lifespan initializes Runtime -> request context -> short DB operations
                                            -> isolated cache / model / limiter
shutdown -> close owned transports; reset context, never mutate another instance
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import RLock
from typing import Any
from uuid import uuid4

from .config import Settings, load_settings
from .host_cache import DeterministicHostCache

_current: ContextVar["Runtime | None"] = ContextVar("turtle_soup_runtime", default=None)
_standalone: "Runtime | None" = None
_standalone_lock = RLock()


def _verified_repair_corpus(corpus, *, testing, soups):
    """Explicit frozen server input only; no file discovery, I/O or model setup."""
    if corpus is None:
        return None
    from .agents.contracts import AgentError
    from .baselines import canonical_json, strict_json
    from eval.manifest import FrozenDataset, load_repair_corpus, verify_frozen_dataset
    try:
        if type(corpus) is not FrozenDataset:
            raise ValueError("A trusted FrozenDataset is required")
        checked = verify_frozen_dataset(corpus)
        cases = load_repair_corpus(checked)
        catalog = strict_json(checked.catalogJson)
        if not 1 <= len(cases) <= 100 or len(catalog) != 1:
            raise ValueError("Single bounded repair corpus required")
        if testing is not True and any(case.authorRole == "synthetic" or case.origin == "public_synthetic" for case in cases):
            raise ValueError("Synthetic corpus cannot authorize production review")
        if soups is not None:
            source = catalog[0]
            matching = [soup for soup in soups if soup.id == source["soupId"]]
            if len(matching) != 1 or canonical_json(matching[0].model_dump(mode="json")) != source["soupJson"]:
                raise ValueError("Corpus source differs from owned puzzle")
        return checked
    except Exception:
        raise AgentError("agent_corpus_invalid", 422) from None


@dataclass
class Runtime:
    settings: Settings
    model: Any = None
    soups: Any = None
    host_cache: dict = field(default_factory=dict)  # inert legacy compatibility, never online lookup
    deterministic_host_cache: DeterministicHostCache = field(default_factory=DeterministicHostCache)
    llm_cache: dict = field(default_factory=dict)
    lock: Any = field(default_factory=RLock)
    http_client: Any = None
    http_async_client: Any = None
    limiter: Any = None
    initialized: bool = False
    instance_id: str = field(default_factory=lambda: str(uuid4()))
    closed: bool = False
    model_gateway: Any = None
    model_shutdown: Any = None
    pending_agents: Any = None
    audit_store: Any = None
    audit_shutdown: Any = None
    audit_startup_recovery: Any = None
    agent_worker: Any = None
    agent_shutdown: Any = None
    repair_corpus: Any = None

    def __setattr__(self, name, value):
        # Trusted server corpus replacement/withdrawal shares the final
        # candidate commit lock. It is not an HTTP/model capability. Before
        # dataclass initialization has created the lock, assign normally.
        lock = self.__dict__.get("lock") if name == "repair_corpus" else None
        if lock is None:
            object.__setattr__(self, name, value)
        else:
            with lock:
                object.__setattr__(self, name, value)

    def __post_init__(self):
        if self.soups is not None:
            self.soups = [s.model_copy(deep=True) for s in self.soups]
        self.repair_corpus = _verified_repair_corpus(self.repair_corpus,
            testing=self.settings.TESTING, soups=self.soups)
        from .rate_limit import SlidingWindowLimiter
        from .model_admission import PendingAgentQueue
        self.limiter = SlidingWindowLimiter()
        self.pending_agents = PendingAgentQueue()

    async def aclose(self):
        # Gateway creation and shutdown admission share one lock. Mark closing
        # before the first await, so no first-use gateway can escape teardown.
        with self.lock:
            if self.closed:
                return
            self.closed = True
            gateway = self.model_gateway
            worker = self.agent_worker
        try:
            try:
                import asyncio
                if worker is not None:
                    worker.stop_admission()
                try:
                    if gateway is not None:
                        self.model_shutdown = await asyncio.to_thread(gateway.close, wait_seconds=2)
                finally:
                    if worker is not None:
                        self.agent_shutdown = await asyncio.to_thread(worker.close, wait_seconds=2)
                if self.http_client is not None:
                    self.http_client.close()
            finally:
                try:
                    if self.http_async_client is not None:
                        await self.http_async_client.aclose()
                finally:
                    if self.audit_store is not None:
                        self.audit_shutdown = await self.audit_store.close(wait_seconds=2)
        finally:
            self.llm_cache.clear()
            self.host_cache.clear()
            self.deterministic_host_cache.clear()
            self.closed = True

    def start_agent_worker(self):
        """Explicit opt-in lifespan operation; no migration/provider call.

        Feature schema is verified before allocating the shared gateway.
        No corpus is auto-discovered: absent independent evidence remains an
        incomplete report, never a passing candidate from model claims.
        """
        if not self.settings.ENABLE_AGENT:
            return None
        from .agents.contracts import AgentError
        from .agents.store import AgentStore
        from .agents.tools import ToolExecutor
        from .agents.regression import FixedRegression
        from .agents.repair_agent import RepairAgent
        from .agents.worker import AgentWorker
        with self.lock:
            if self.closed or self.settings.API_WORKER_COUNT != 1:
                raise AgentError("agent_unavailable", 503)
            if self.agent_worker is not None:
                return self.agent_worker
            store = AgentStore(self, authorize_create=lambda context: self.settings.ENABLE_AGENT and not self.closed,
                lease_seconds=60)
            with store._transaction(write=False):
                pass
            # Explicit shared corpus, never discovered by the worker/model.
            self.repair_corpus = _verified_repair_corpus(self.repair_corpus,
                testing=self.settings.TESTING, soups=self.soups)
            regression = FixedRegression(self, corpus=self.repair_corpus)
            gateway = self.get_model_gateway()
            self.agent_worker = AgentWorker(self, store,
                RepairAgent(store, ToolExecutor(store, regression=regression), gateway))
            self.agent_worker.start()
            return self.agent_worker

    def get_model_gateway(self):
        from .model_gateway import CompatibleAdapter, InjectedAdapter, ModelGateway
        with self.lock:
            if self.closed:
                from .model_gateway import ModelFailure
                raise ModelFailure("model_unavailable")
            if self.model_gateway is None:
                self.model_gateway = ModelGateway(adapter_factory=lambda: (
                    InjectedAdapter(self.model) if self.model is not None else CompatibleAdapter(self.settings)))
            return self.model_gateway


def get_runtime() -> Runtime:
    active = _current.get()
    if active is not None:
        return active
    # Legacy explicitly invoked CLI functions still work. Import never gets here.
    global _standalone
    with _standalone_lock:
        if _standalone is None:
            _standalone = Runtime(load_settings())
        return _standalone


@contextmanager
def runtime_context(runtime: Runtime):
    token = _current.set(runtime)
    try:
        yield runtime
    finally:
        _current.reset(token)
