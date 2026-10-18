# TS-05 request safety and bounded model admission implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound and fairly admit offline-tested request/model work, isolate rate policies, reject forged proxy/auth/oversized inputs, and never release still-running local model owners.

**Architecture:** Extend the runtime-owned gateway's existing Condition/owner set, not a parallel semaphore or unlimited executor. Add a focused request_guards module; keep limiter and proxy identity in rate_limit. Pending-agent capacity is a primitive now, durable scheduling follows 003/TS-14.

**Tech Stack:** Existing Python/FastAPI/HTTPX/SQLite/stdlib; pytest fake clocks/events and FakeModel, no new paid service/dependency.

**Spec:** docs/superpowers/specs/2026-10-08-ts05-admission-design.md; original global plan TS-05/D4/D23, A18–A21 and C04/C06/C15.

## Global constraints

- Actual local model calls max 2; Agent calls max 1; slots end only after confirmed local exit and cleanup, not HTTP timeout/cancel/turn expiry.
- Online waiting capacity 32, admission wait max 10s subject to original 45s total model deadline. No waiting model thread per ticket or second executor; Agent pending capacity 10, online-first, no Agent SLA.
- Chat remains 30/min + 300/hour; all monotonic windows independent by identity/endpoint/policy, one request recorded once per policy. Boundary timestamps <=now-window expire.
- Application/explicit reverse-proxy template body max 32768 bytes. 413/429/503 carry safe detail/code/requestId; 429 includes integer Retry-After. Question/feedback limits and free failures retained.
- No trusted proxy default; only configured immediate peer/hops can affect identity. Independent admin token required; missing admin config disables capability.
- No actual Agent enablement, production changes/model/private config reads/publication or auto commits. Actual server worker/proxy/free quotas remain external gates.
- Existing dirty TS-01–04 preserved. Reviewed TS-04 sources stay stable until independent review/fix gate completes; disjoint test/plan files may advance.
- Explicit human no-stage-prompts delegation overrides skill handoff/approval menus; consequential unknown items go to autonomous-progress individually, not guessed.

## Review focus

1. A rejected hour window cannot partially consume another policy or lose retained activity when keys hit capacity; denied responses must have a usable Retry-After.
2. Chained/spoofed proxy headers and malformed peer addresses cannot select another identity or bypass independent administrator access.
3. Fragmented/deceptive-length bodies cannot exceed 32KiB or race ASGI disconnect/body observers into losing input or creating games after refusal.
4. A full queue plus two ignoring-cancel/cleanup-failed owners cannot create extra model workers, release early or hang shutdown/wait indefinitely.
5. A waiting/partially cancelled online ticket cannot allow new Agent work to overtake it; admission and model retry share one deadline/actual attempt budget and multi-worker mismatch cannot enable Agent.

### Task 1: Monotonic multi-policy limiter and trusted proxy identity

**Files:** Modify backend/app/rate_limit.py, backend/app/config.py, backend/app/main.py; create backend/tests/test_rate_limit_windows.py, backend/tests/test_proxy_identity.py.

**Interfaces:** RatePolicy(id,limit,window), RateDecision(allowed,retryAfterSeconds); SlidingWindowLimiter(clock=time.monotonic,max_keys=4096).check(identity,endpoint,policies)->RateDecision, snapshot()->dict; compatibility allow(key,limit,window) uses isolated policy identity. client_ip(Request)->str reads only settings.TRUSTED_PROXY_CIDRS and validated peer/header chain. rate_limits(policies) is one dependency; rate_limit(limit,window) remains a one-policy wrapper. Runtime still owns one limiter per app.

- [x] Write tests: 30 admits at t=0 then denial; at 59.999 denied, at 60 admitted; hour policy still retains all minute activity, 300/hour exact boundary. Other endpoint/identity/policy independent; multiwindow rejection changes no other window; same dependency repeated on one request counted once; 40 event-synchronized callers admit exactly 30.
- [x] Write expiry/key-cap tests and proxy tests: untrusted XFF ignored, loopback only trusted when configured, right-to-left multi-hop, invalid/unknown peer, malformed/too-long XFF safe fallback, IPv4/IPv6 normalization.
- [x] Run `.\backend\.venv-ts01\Scripts\python.exe -m pytest backend/tests/test_rate_limit_windows.py backend/tests/test_proxy_identity.py -q --tb=short -o cache_dir=.cache/ts05/pytest-cache`. Expected: FAIL missing independent window/clock/proxy policy behavior.
- [x] Implement interfaces with atomic check-all/append-all, finite key retention and monotonic time; settings validates CIDRs, dependencies return stable 429/Retry-After and route-template identity without logging credentials.
- [x] Run targeted command and existing settings/API/isolation tests. Expected: PASS; preserve exact limits and app-local state. Record results and rulings, no commit.

### Task 2: Body bound, administrator boundary and explicit launch policy

**Files:** Create backend/app/request_guards.py, backend/tests/test_request_guards.py; modify config/main and backend/.env.example; create deploy/templates/turtle-soup-api.conf, deploy/templates/turtle-soup-api.service, scripts/run-backend.py.

**Interfaces:** BodyLimitMiddleware(app, max_bytes=32768) rejects before route; validation is on actual received bytes as well as Content-Length. require_site_token/require_admin_token own safe comparison, no body-supplied authority. Settings.TRUSTED_PROXY_CIDRS tuple, API_WORKER_COUNT int>=1, ENABLE_AGENT bool=False; enabled Agent plus count!=1 fails. Owned launcher uses exactly configured single-worker baseline and rejects incompatible Agent count, never spawns during tests without isolated configuration.

- [x] Write raw ASGI/TestClient tests for 32768 accepted boundary, 32769 rejected, fragmented oversized/no Content-Length, declared too big, misleading short length, safe CORS and no DB/model/feedback side effects after 413.
- [x] Write no/wrong admin 401, missing config 503, site token not admin, correct independent token permitted; future admin views must consume same guard without fake endpoints.
- [x] Write launcher/config dry validation tests: unknown/invalid worker counts and multiworker+Agent rejected; launch command uses declared count, no silent parallel admission claim. Template checks are implementation metadata, actual Nginx/server verification remains deferred.
- [x] Run `.\backend\.venv-ts01\Scripts\python.exe -m pytest backend/tests/test_request_guards.py -q --tb=short -o cache_dir=.cache/ts05/pytest-cache`. Expected: FAIL missing bounds/guards; implement modules/settings/examples/templates, preserve request_lifecycle ownership and existing site behavior; rerun targeted plus normal/request/disconnect tests. Expected: PASS.
- [x] Ledger actual topology/template limitations; do not execute deploy scripts or read live credentials/config.

### Task 3: Online-first bounded gateway admission and pending-agent primitive

**Files:** Modify backend/app/model_gateway.py, backend/app/runtime.py, backend/app/ai_host.py as needed; create backend/app/model_admission.py only for focused pending-agent types, backend/tests/test_model_admission.py.

**Interfaces:** ModelGateway.invoke(messages,deadline,max_attempts=2,cancelled=None,traffic_class='online',before_attempt=None)->HostJudgment. traffic_class restricted online/agent, program-owned; before_attempt(attempt:int,deadline:float)->None is a trusted future durable-budget hook, never provider input. Gateway snapshot adds waiting_online/active_online/active_agent without input/IDs. PendingAgentQueue(capacity=10).enqueue(operation_key,payload_digest)->bool, cancel(operation_key)->bool, snapshot()->dict is idempotent bounded local primitive, not future durable storage.

- [x] Write event/fake-clock tests: two occupied actual owners; 32 queued online accepted, 33rd immediate busy with no factory/worker creation; max wait min(10s, remaining original deadline), cancellation removes one ticket; FIFO order on cleanup; timeout/cleanup failure retains slots. Snapshot counts explain refusal without private input.
- [x] Write online-before-Agent and one-Agent-owner tests; Agent busy starts no model, pending capacity 10, duplicate same key/digest idempotent/different digest conflict, cancellation frees exactly one queued key. Agent admission while online waits is refused, continuous online load can defer it.
- [x] Write every actual attempt invokes trusted before_attempt once, retries share original deadline, a refused/cancelled/queued request consumes no attempt; hook failure starts no transport attempt and retains proper owner cleanup.
- [x] Run `.\backend\.venv-ts01\Scripts\python.exe -m pytest backend/tests/test_model_admission.py -q --tb=short -o cache_dir=.cache/ts05/pytest-cache`. Expected: FAIL no queue/classes/budget interface. Extend the existing owner Condition (no competing semaphore), do not create workers until admission. Rerun new + TS-03 ownership/TS-04 cancellation/gateway/API tests. Expected: PASS.
- [x] Add synthetic 100 arrivals bounded-admission experiment, report peak owners/waiters/admitted/refused/cancelled, not real users/throughput/quality. Existing framework worker pool remains bounded; no new waiting-thread executor.

### Task 4: Full gate, independent stage review, continuation

**Files:** docs/ts05-status.md, docs/test-runtime.md, this plan and progress ledger.

- [x] Run scripts/verify-test-isolation.ps1, npm run typecheck, git diff --check; real runtime hash unchanged. Expected: exit 0, no hidden skipped failures.
- [x] One independent read-only stage review with the Review Focus and rulings. Reproduce Important/Critical findings RED→GREEN in one fix pass, run full gate; no repeated reviewer loop.
- [x] Map A18–A21 to actual evidence; explicitly preserve actual free quota/topology/remote-provider/OS/production/Agent003 limits. Do not sign off future durable queue merely from local primitive.
- [x] Continue TS-06 automatically; user need not provide a stage instruction, no paid fallback/deploy/public upload.

## Self-review and dependency pre-flight

Task 1→2: client identity uses validated Settings CIDRs, admin decisions precede guarded protected data access. Task 2→3: single-worker Agent gate cannot be interpreted as measured live topology. Task 3→TS-14: traffic_class/before_attempt/pending capacity are program-owned; durable budget intent/checkpoint and queue remain 003 work. Online deadline begins before admission, unchanged during retry. A18–A21/C04/C06/C15 tests named, failure/state/owner lifecycles separated; independent TS-04 review holds shared source stable before TS-05 integration.
