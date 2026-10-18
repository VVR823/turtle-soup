# TS-03 Host contract and model gateway implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make host decisions explicit, fail closed on invalid model output, and bound model response waiting without falsely releasing a still-running call.

**Architecture:** Keep the existing endpoints and game logic; introduce one validated HostResult contract and a runtime-owned bounded model gateway. Dedicated call ownership spans transport cleanup, while request waiting, retry budget and cancellation share one deadline. TS-04 supplies atomic turn fencing; TS-05 completes shared queue/admission policy; neither future guarantee is claimed by TS-03.

**Tech Stack:** Python 3.11–3.13, FastAPI, Pydantic 2, existing LangChain/HTTPX, SQLite; pytest with synthetic fixtures and FakeModel/FakeTransport.

**Spec:** `D:/CODE/turtle-soup-audit/TurtleSoup_秋招升级实施计划_2026-10-06.md`, sections 5.1 TS-03, 7, 8.2–8.3, 13 D9–D14, 15 D21; corresponding A07–A10 and C01–C24 test paths.

## Global constraints

- Zero new paid cost; no purchased quota, paid fallback provider or real model calls during offline development.
- Preserve `/api/chat`, `/api/evaluate`, `/api/session/{id}` and camelCase response fields. Unknown/invalid level still falls back to the strictest existing difficulty, per A29.
- Trimmed question length 1–500; feedback question ≤500, answers ≤100, reason ≤2000. Business scene errors 400, scalar validation 422, conflicting redundant soupId 409.
- New requestId is UUID; legacy omission gets a generated ID. Adding IDs in TS-03 does not claim TS-04 idempotency.
- Five-class answers only: 是、不是、是也不是、算是、与此无关. Unknown/unparseable output is system_error, not a factual answer.
- Online total waiting deadline initially 45 seconds, including admission, network, parsing and explicit retries; SDK retry count 0. Local call ownership ends only after confirmed transport cleanup.
- Context includes at most 12 complete valid turns; fixed prompt/question/facts must fit a conservative 8000-character bound or fail explicitly. No tokenizer-accurate TPM claim.
- Existing dirty TS-01/02 work retained, no automatic Git commit/push, production migration/deployment or public upload.
- User explicitly delegated design/plan decisions and continuous execution; replace skill handoff approval questions with documented self-review, not repeated user prompts. This does not authorize production changes.

## Review focus

1. Empty or mixed create/ask bodies must not silently create a game or discard the question; legacy equal soupId must still work.
2. Invalid JSON, duplicate keys, extra permissions/charge fields and “不知道” must never become 与此无关 or consume a question.
3. Provider secrets, internal reasoning, hidden facts and local paths must not appear in ordinary error responses/logs.
4. A timed-out call that ignores cancellation or whose cleanup fails must retain its owner slot and prevent unbounded new work.
5. Partial/free/error history and oversized fixed facts must not silently produce misleading context; original stored history is not truncated.

---

### Task 1: Authoritative host and API contracts

**Files:** Modify `backend/app/schemas.py`, `backend/app/main.py`; create `backend/tests/test_host_contract.py`, `backend/tests/test_request_contract.py`.

**Interfaces:** Produces immutable `HostResult(kind, answer, chargeable, source, evidenceIds, versions, errorCode, reply)` and `HostVersions(puzzleVersion, ruleVersion, engineVersion, normalizationVersion)`. `ChatRequest.scene()` returns create/ask or raises a scene error; requestId is populated at validation. Feedback/evaluate lengths are validated without echoing private inputs in public errors.

- [x] Write HostResult tests: answer requires a five-class answer/no error/chargeable true; reminder and error require null answer/chargeable false; error requires errorCode; win is explicit and not an answer inferred from text. Provider HostJudgment forbids extra fields and rejects unknown answers/duplicate JSON keys.
- [x] Write API tests: empty/whitespace/501-character question →422; create+question or ask+level →400; legacy equal soupId →200 and conflicting soupId →409; malformed UUID →422; IDs returned on create/ask; feedback length boundaries and unchanged strictest-level fallback.
- [x] Run those tests and observe missing-contract failures.
- [x] Implement validation with strict scalar fields and explicit scene checks. Keep typed result display separate from classification; mapping compatibility is temporary for existing internal tests, not a provider permission channel.
- [x] Re-run new tests and current API/host regressions.
- [x] Record exact commands/results in the stage ledger; no automatic commit.

### Task 2: Runtime-owned bounded call gateway

**Files:** Create `backend/app/model_gateway.py`, `backend/tests/test_model_gateway.py`; modify `backend/app/config.py`, `backend/app/runtime.py`, explicit example configurations.

**Interfaces:** `ModelGateway.invoke(messages, deadline, max_attempts=2)` returns validated judgment/metadata or raises a safe `ModelFailure(code)`. Per-call adapter accepts an absolute monotonic deadline and cancellation event; cleanup is owner-local. `close(wait_seconds)` stops admission, requests cancellation and reports remaining/cleanup-failed owners, never claims they exited. Runtime retains gateway shutdown result.

- [x] Add scripted transport tests for strict output validation, max 2 explicit attempts with one original deadline, no retry on quota/auth/config errors, and no raw provider error propagation.
- [x] Add event-barrier tests: two ignoring-cancel calls time out but retain two slots; a third cannot start; actual exit releases exactly once; cleanup failure conservatively retains a degraded slot; shutdown cancels and respects its wait bound.
- [x] Add provider-policy tests: unknown provider/remote unpaid status unverified or mismatched model/URL →fail before any transport creation; no fallback to Qwen. Local Ollama or explicitly verified matching free configuration only. FakeModel requires no credentials or HTTP clients.
- [x] Run failing tests, implement bounded ownership and attempt/deadline handling, rerun tests. No unlimited executor queue or app-global client cancellation.
- [x] Configure real adapter with SDK retries disabled and finite remaining transport timeouts; test configuration with an injected transport, never a live provider. Cancellation/cleanup behavior must have adapter-level evidence or remain a documented release blocker.
- [x] Record provider-policy and cancellation limitations separately from passing synthetic tests.

### Task 3: Host integration and bounded context

**Files:** Modify `backend/app/ai_host.py`, `backend/app/main.py`, `backend/app/trace_logger.py`, affected synthetic fixtures; create `backend/app/host_context.py`, `backend/tests/test_host_context.py`.

**Interfaces:** `handle_host_response(...) -> HostResult`; `call_llm(...) -> HostResult` invokes only the runtime gateway. Deterministic branches explicitly choose kind/answer/source rather than parsing emoji. Main charges solely from `HostResult.chargeable` and returns safe kind/requestId; TS-04 later writes the entire result atomically.

- [x] Test charge behavior with changed/absent emoji, strict malformed/unknown model responses and valid five-class responses; system_error does not charge and exposes no private details.
- [x] Test context builder with 13 complete pairs, incomplete pairs, free/error turns, same-version facts, over-limit fixed content; choose at most last 12 valid pairs and drop only whole oldest pairs to fit 8000 characters.
- [x] Observe failures; integrate typed deterministic branches and gateway, remove permissive model text fallback/implicit second full-time-budget call. Keep display compatibility and existing special soup win behavior.
- [x] Disable unsafe cross-session LLM/context caching. Deterministic cache schema/version/normalization completion belongs to TS-06, not a TS-03 signoff.
- [x] Run new and existing host/API tests; inspect error/trace boundaries. Do not add future tables or claim missing TS-04 fencing.
- [x] Record issues, fixes and remaining stage dependencies.

### Task 4: Stage gate and continuation

**Files:** Update `docs/ts03-status.md`, `docs/test-runtime.md`, backend/root README as needed and progress ledger.

- [x] Run `scripts/verify-test-isolation.ps1`, TypeScript typecheck, and `git diff --check`. Check unchanged real runtime file manifest, not just test exit code.
- [x] Complete an independent local review of the TS-03 scope; reproduce actionable findings with failing tests, fix and rerun affected/full gates.
- [x] Map A07–A10 to actual evidence and explicit unverified provider/transport limits; never mark production/real-model/CI evidence passed offline.
- [x] Proceed automatically to TS-04 after the local gate, preserving unresolved release blockers in the overall ledger; do not ask for a stage “continue”.

## Plan self-review

The plan maps API/HostResult, explicit output validation, budget/deadline, free-policy, bounded context and lifecycle to separate tests. D4 release-on-cleanup and A21 are shared with TS-05; TS-03 supplies the ownership primitive without claiming full queue/fairness/multi-worker guarantees. TS-04 still owns idempotent turn state/fencing, so a requestId alone is not advertised as safe retry. The independent TS-02 review is running in parallel; implementation touching reviewed migration/db/main/CLI source starts only after its findings are handled. Pure new gateway/schema contracts may proceed independently (TS-03 depends on TS-01).
