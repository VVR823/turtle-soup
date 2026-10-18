"""Bounded local call ownership, independent of a caller's response timeout.

Only the owner that finishes transport cleanup releases its slot. A cancellation
request is not proof a blocked local thread (or remote inference) has stopped.
Online waiters own only bounded FIFO tickets, never extra model workers.
"""
from collections import deque
import math
import time
from concurrent.futures import Future, TimeoutError as FutureTimeout
from contextvars import copy_context
from dataclasses import dataclass, field
from threading import Condition, Event, Thread

from pydantic import ValidationError

from .baselines import strict_json
from .schemas import HostJudgment, ModelErrorCode
from typing import get_args
import re


class ModelFailure(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False):
        self.code = code if code in get_args(ModelErrorCode) else "model_unavailable"
        self.retryable = retryable and self.code in {"model_transport_error", "model_output_invalid"}
        super().__init__(self.code)


@dataclass(eq=False)
class _Owner:
    future: Future = field(default_factory=Future)
    cancelled: Event = field(default_factory=Event)
    adapter: object = None
    timed_out: bool = False
    cleanup_failed: bool = False
    worker: Thread | None = None
    request_cancelled: Event | None = None
    traffic_class: str = "online"


class ModelGateway:
    def __init__(self, *, adapter_factory, max_active: int = 2, clock=time.monotonic):
        if type(max_active) is not int or not 1 <= max_active <= 2:
            raise ValueError("Local call limit must be 1 or 2")
        self._factory = adapter_factory
        self._max_active = max_active
        self._clock = clock
        self._condition = Condition()
        self._owners: set[_Owner] = set()
        self._waiting_online = deque()
        self._closed = False

    def snapshot(self) -> dict:
        with self._condition:
            return {"active": len(self._owners), "closed": self._closed,
                    "waiting_online": len(self._waiting_online),
                    "active_online": sum(o.traffic_class == "online" for o in self._owners),
                    "active_agent": sum(o.traffic_class == "agent" for o in self._owners),
                    "timed_out_but_running": sum(o.timed_out and not o.cleanup_failed for o in self._owners),
                    "cleanup_failed": sum(o.cleanup_failed for o in self._owners)}

    def _cancel(self, owner):
        owner.cancelled.set()
        # Adapter contract: this method only signals cancellation, never waits
        # for I/O cleanup or closes an application-global shared transport.
        adapter = owner.adapter
        if adapter is not None:
            try:
                adapter.request_cancel()
            except Exception:
                # Keep the slot; only confirmed cleanup can release it.
                pass

    def _admit(self, *, deadline, cancelled, traffic_class):
        """Called with the owner Condition held; all capacity has one authority."""
        ticket = None
        wait_until = min(deadline, self._clock() + 10)
        try:
            while True:
                if self._closed:
                    raise ModelFailure("model_unavailable")
                if cancelled is not None and cancelled.is_set():
                    raise ModelFailure("model_cancelled")
                if self._clock() >= wait_until:
                    raise ModelFailure("model_busy")
                free = len(self._owners) < self._max_active
                if traffic_class == "agent":
                    if (not free or self._waiting_online
                            or any(o.traffic_class == "agent" for o in self._owners)):
                        raise ModelFailure("model_busy")
                    return _Owner(request_cancelled=cancelled, traffic_class=traffic_class)
                if free and (not self._waiting_online or self._waiting_online[0] is ticket):
                    return _Owner(request_cancelled=cancelled, traffic_class=traffic_class)
                if ticket is None:
                    if len(self._waiting_online) >= 32:
                        raise ModelFailure("model_busy")
                    ticket = object()
                    self._waiting_online.append(ticket)
                # Bounded cancellation/deadline observation; no model thread is
                # created for this ticket. Framework caller pool stays separate.
                self._condition.wait(min(wait_until - self._clock(), 0.05))
        finally:
            if ticket is not None:
                self._waiting_online.remove(ticket)
                self._condition.notify_all()

    def invoke(self, messages, *, deadline: float, max_attempts: int = 2,
               cancelled: Event | None = None, traffic_class: str = "online",
               before_attempt=None, response_contract="host_judgment"):
        # Trusted server choice only, never a model-selected callback/module.
        if type(response_contract) is not str or response_contract not in {
                "host_judgment", "host_judgment_json", "repair_action", "legacy_raw"}:
            raise ValueError("Unknown response contract")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 2:
            raise ValueError("Attempt budget must be 1 or 2")
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError("Model deadline must be finite")
        if traffic_class not in ("online", "agent"):
            raise ValueError("Unknown traffic class")
        if before_attempt is not None and not callable(before_attempt):
            raise ValueError("Attempt hook must be callable")
        if deadline <= self._clock():
            raise ModelFailure("model_timeout")
        if cancelled is not None and cancelled.is_set():
            raise ModelFailure("model_cancelled")
        with self._condition:
            owner = self._admit(deadline=deadline, cancelled=cancelled, traffic_class=traffic_class)
            self._owners.add(owner)
            context = copy_context()
            owner.worker = Thread(target=context.run, args=(self._run, owner, messages, deadline, max_attempts, before_attempt, response_contract),
                                  name="turtle-soup-model", daemon=True)
            try:
                owner.worker.start()
            except BaseException:
                self._owners.remove(owner)
                self._condition.notify_all()
                raise
        while True:
            if cancelled is not None and cancelled.is_set():
                self._cancel(owner)
                raise ModelFailure("model_cancelled")
            remaining = deadline - self._clock()
            if remaining <= 0:
                with self._condition:
                    owner.timed_out = True
                self._cancel(owner)
                raise ModelFailure("model_timeout")
            try:
                return owner.future.result(timeout=remaining if cancelled is None else min(remaining, 0.05))
            except FutureTimeout:
                continue

    def _check(self, owner, deadline):
        if owner.request_cancelled is not None and owner.request_cancelled.is_set():
            self._cancel(owner)
        if owner.cancelled.is_set():
            raise ModelFailure("model_cancelled")
        if self._clock() >= deadline:
            raise ModelFailure("model_timeout")

    def _observe_model(self, adapter, ordinal, status, *, raw=None, error_code=None):
        from .audit_context import current_attempt
        collector = current_attempt()
        if collector is None:
            return
        try:
            from .audit_events import ModelCallObservation, TokenUsage, normalize_usage
            provider = "injected" if isinstance(adapter, InjectedAdapter) else adapter.provider if isinstance(adapter, CompatibleAdapter) else None
            model = adapter.model if isinstance(adapter, CompatibleAdapter) else None
            if model is not None and (not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}", model) or "://" in model):
                model = None
                collector.note_metadata_gap()
            usage, usage_status = TokenUsage(), "unknown"
            if status != "started" and raw is not None:
                if isinstance(adapter, CompatibleAdapter):
                    usage, usage_status = adapter.audit_usage
                elif isinstance(adapter, InjectedAdapter):
                    usage, usage_status = normalize_usage(getattr(raw, "usage_metadata", None), format="injected")
            collector.observe_model(ModelCallObservation(ordinal=ordinal, provider=provider, model=model, status=status,
                errorCode=error_code, usage=usage, usageStatus=usage_status))
        except Exception:
            # Metadata is not a business decision. No raw exception is logged,
            # and its missing coverage is explicit in the safe attempt DTO.
            collector.note_metadata_gap()

    def _run(self, owner, messages, deadline, max_attempts, before_attempt, response_contract):
        outcome, failure = None, None
        try:
            self._check(owner, deadline)
            owner.adapter = self._factory()
            if response_contract == "legacy_raw":
                # Fixed offline baseline only; refuse before any dispatch/hook.
                from .testing import FakeModel
                if (not isinstance(owner.adapter, InjectedAdapter)
                        or not isinstance(owner.adapter.model, FakeModel)):
                    raise ModelFailure("model_policy_unknown")
            for attempt in range(max_attempts):
                self._check(owner, deadline)
                if before_attempt is not None:
                    # Program-owned durable budget hook. A hook refusal is not
                    # a transport retry and never starts a provider attempt.
                    before_attempt(attempt + 1, deadline)
                    self._check(owner, deadline)
                raw = None
                try:
                    self._observe_model(owner.adapter, attempt + 1, "started")
                    raw = owner.adapter.invoke(messages, deadline=deadline, cancelled=owner.cancelled)
                    self._check(owner, deadline)
                    text = raw.content if hasattr(raw, "content") else raw
                    if (not isinstance(text, str)
                        or (response_contract in {"host_judgment", "host_judgment_json", "legacy_raw"} and len(text) > 16000)
                        or (response_contract == "repair_action" and len(text.encode("utf-8")) > 32768)):
                        raise ModelFailure("model_output_invalid", retryable=True)
                    if response_contract == "legacy_raw":
                        outcome = text
                    elif response_contract == "repair_action":
                        from .agents.contracts import AgentError, parse_agent_action
                        try:
                            outcome = parse_agent_action(text)
                        except AgentError:
                            raise ModelFailure("model_output_invalid", retryable=True) from None
                    else:
                        answers = {"是", "不是", "是也不是", "算是", "与此无关"}
                        canonical = text.strip()
                        if response_contract == "host_judgment" and canonical in answers:
                            outcome = HostJudgment(answer=canonical, reasoning="")
                        else:
                            try:
                                payload = strict_json(text)
                                if (type(payload) is dict and set(payload) == {"answer"}
                                        and payload.get("answer") in answers):
                                    payload = {"answer": payload["answer"], "reasoning": ""}
                                outcome = HostJudgment.model_validate(payload)
                            except (ValueError, TypeError, ValidationError):
                                raise ModelFailure("model_output_invalid", retryable=True) from None
                        # Discard internal host reasoning at the boundary.
                        outcome = outcome.model_copy(update={"reasoning": ""})
                    self._observe_model(owner.adapter, attempt + 1, "succeeded", raw=raw)
                    break
                except ModelFailure as error:
                    self._observe_model(owner.adapter, attempt + 1, "failed", raw=raw, error_code=error.code)
                    if not error.retryable or attempt + 1 == max_attempts:
                        raise
                    self._check(owner, deadline)
                except BaseException:
                    self._observe_model(owner.adapter, attempt + 1, "failed", raw=raw, error_code="model_unavailable")
                    raise
        except ModelFailure as error:
            failure = error
        except BaseException:
            # No raw exception text, keys, paths or facts leave the gateway.
            failure = ModelFailure("model_unavailable")
        finally:
            try:
                if owner.adapter is not None:
                    owner.adapter.close()
            except BaseException:
                failure = ModelFailure("model_cleanup_failed")
                with self._condition:
                    owner.cleanup_failed = True
            with self._condition:
                if owner.cancelled.is_set() and failure is None:
                    failure = ModelFailure("model_cancelled")
                if not owner.cleanup_failed:
                    self._owners.discard(owner)
                if failure is None:
                    owner.future.set_result(outcome)
                else:
                    owner.future.set_exception(failure)
                self._condition.notify_all()

    def close(self, *, wait_seconds: float = 2) -> dict:
        if wait_seconds < 0:
            raise ValueError("Shutdown waiting must be nonnegative")
        with self._condition:
            self._closed = True
            owners = tuple(self._owners)
            self._condition.notify_all()
        for owner in owners:
            self._cancel(owner)
        stop_at = time.monotonic() + wait_seconds
        with self._condition:
            while any(not owner.future.done() for owner in self._owners):
                remaining = stop_at - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
        return self.snapshot()


class InjectedAdapter:
    """Trusted dependency injection, e.g. FakeModel; owns no shared client."""
    def __init__(self, model):
        self.model = model
        self.cancelled = Event()

    def invoke(self, messages, *, deadline, cancelled):
        if self.cancelled.is_set() or cancelled.is_set():
            raise ModelFailure("model_cancelled")
        return self.model.invoke(messages)

    def request_cancel(self):
        self.cancelled.set()

    def close(self):
        pass


class CompatibleAdapter:
    """One owned HTTPX client, OpenAI-compatible endpoint, zero hidden retries.

    Cancellation is cooperative: an already-blocked network operation can run
    until its transport timeout. The gateway keeps its slot until close finishes.
    A local cancellation/close is not proof of cancelled remote inference.
    """
    def __init__(self, settings, *, transport=None):
        from urllib.parse import urlsplit
        import httpx
        if not settings.ALLOW_REAL_MODEL:
            raise ModelFailure("model_policy_unknown")
        options = {
            "ollama": (settings.OLLAMA_MODEL, "ollama", settings.OLLAMA_BASE_URL),
            "qwen": (settings.QWEN_MODEL, settings.QWEN_API_KEY, settings.QWEN_BASE_URL),
            "siliconflow": (settings.SILICONFLOW_MODEL, settings.SILICONFLOW_API_KEY, settings.SILICONFLOW_BASE_URL),
            "zhipu": (settings.ZHIPU_MODEL, settings.ZHIPU_API_KEY, settings.ZHIPU_BASE_URL),
        }
        if settings.LLM_PROVIDER not in options:
            raise ModelFailure("model_policy_unknown")
        self.model, self._key, base_url = options[settings.LLM_PROVIDER]
        self.provider = settings.LLM_PROVIDER
        from .audit_events import TokenUsage
        self.audit_usage = (TokenUsage(), "unknown")
        endpoint = urlsplit(base_url)
        if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ModelFailure("model_policy_unknown")
        if settings.LLM_PROVIDER == "ollama":
            if endpoint.scheme not in {"http", "https"} or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ModelFailure("model_policy_unknown")
        elif (not settings.MODEL_FREE_VERIFIED or endpoint.scheme != "https"
              or (settings.FREE_MODEL_PROVIDER, settings.FREE_MODEL_NAME, settings.FREE_MODEL_BASE_URL)
                 != (settings.LLM_PROVIDER, self.model, base_url)):
            raise ModelFailure("model_policy_unknown")
        if not self.model or not self._key:
            raise ModelFailure("model_auth")
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._client = httpx.Client(transport=transport if transport is not None else httpx.HTTPTransport(retries=0),
                                    follow_redirects=False, trust_env=False)
        self.cancelled = Event()
        self.closed = False

    def invoke(self, messages, *, deadline, cancelled):
        import httpx
        from langchain_core.messages import HumanMessage, SystemMessage
        from .audit_events import normalize_usage, TokenUsage
        self.audit_usage = (TokenUsage(), "unknown")
        if self.cancelled.is_set() or cancelled.is_set():
            raise ModelFailure("model_cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ModelFailure("model_timeout")
        timeout = httpx.Timeout(connect=min(10, remaining), read=remaining,
                                write=min(10, remaining), pool=min(10, remaining))
        # Repair prompts use typed messages, while the host already supplies
        # wire dictionaries. Normalize only at this owned HTTP boundary;
        # injected models continue receiving their original typed messages.
        wire_messages = [
            {"role": "system" if isinstance(message, SystemMessage) else "user", "content": message.content}
            if isinstance(message, (SystemMessage, HumanMessage)) else message
            for message in messages
        ]
        try:
            response = self._client.post(self._url, headers={"Authorization": "Bearer " + self._key},
                json={"model": self.model, "messages": wire_messages, "temperature": 0.1,
                      "max_tokens": 600, "stream": False,
                      "response_format": {"type": "json_object"}}, timeout=timeout)
        except httpx.HTTPError:
            raise ModelFailure("model_transport_error", retryable=True) from None
        if self.cancelled.is_set() or cancelled.is_set():
            raise ModelFailure("model_cancelled")
        if response.status_code in {401, 403}:
            raise ModelFailure("model_auth")
        if response.status_code == 429:
            raise ModelFailure("model_quota")
        if response.status_code >= 500:
            raise ModelFailure("model_transport_error", retryable=True)
        if not 200 <= response.status_code < 300:
            raise ModelFailure("model_unavailable")
        try:
            body = strict_json(response.text)
            value = body["choices"][0]["message"]["content"]
            if not isinstance(value, str):
                raise ValueError("Unknown provider content format")
            self.audit_usage = normalize_usage(body.get("usage"), format="compatible")
            return value
        except (ValueError, TypeError, KeyError, IndexError):
            raise ModelFailure("model_output_invalid", retryable=True) from None

    def request_cancel(self):
        self.cancelled.set()

    def close(self):
        self._client.close()
        self.closed = self._client.is_closed
