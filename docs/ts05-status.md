# TS-05 request safety and model admission

Status: LOCAL_VERIFIED_WITH_CONCERNS. Independent review and one TDD fix pass complete; not production sign-off.

Implemented: independent monotonic 30/min + 300/hour policies; atomic multiwindow accounting/key cap; configured trusted proxy chain only; 32768 actual-byte bound; independent constant-time site/admin guard; explicit owned single-worker launcher and uninstalled proxy/service templates. Online FIFO tickets max 32 / 10 seconds within the original deadline; actual owners max 2 / Agent max 1, slots retained until successful cleanup, online-first; trusted actual-attempt hook and separate capacity-10 local pending intent per Runtime.

Evidence: 87 stage/permanent review tests (77 original + 10); review-fix integration 137 passed / 2 platform skipped. Final full gate including TS-06 pure exact-key tests: 509 pytest + 7 Vitest + 6 harness + 3 API-only Playwright = 525 passed / 9 skipped, original 239 files/hash unchanged. Owned fixture PID 103912 exited normally, typecheck/diff check exit 0. XML .cache/ts05/review-green.xml and review-full-gate.xml. Synthetic 100 arrivals: peak owners 2, waiters 32, workers 2; admitted 2/refused 66/cancelled 32. Not a real-user/throughput measurement.

Reviewer Bacon returned 2 Important findings, 183 scoped passes / 2 failing probes, closed after terminal report (not counted into parent totals). Capacity Retry-After now waits for nonrequested keys and combines blocking windows; impossible policy sets refuse as configuration errors. Canonical launcher and historical service commands no longer let Uvicorn rewrite peer identity before app policy; actual CLI/middleware behavior tested, no deployment executed. Parent additionally regraded equal site/admin credentials and empty ASGI fragment memory as Important; both reproduced and fixed in the same pass. No second review.

| Acceptance | Local evidence | Preserved boundary |
| --- | --- | --- |
| A18 | 9 window/concurrency/capacity tests, 7 dependency tests, capacity review regressions | Actual free provider RPM/TPM not inferred |
| A19 | 10 proxy tests, 17 guard tests, ASGI/CLI boundary regressions and CORS/refusal tests | Actual trusted hops/TLS/proxy-generated 413 JSON/CORS remains TS-17 gate |
| A20 | Independent constant-time token guard, current protected feedback HTTP refusal, known reused-secret startup rejection | Absent future Trace/metrics/approval endpoints require their own later integration tests; real credential strength not inspected |
| A21 | 26 admission tests plus ownership/adapter/disconnect; actual owners 2/Agent 1, queue 32/10s, pending intent 10, budget hook, explicit worker gate | 003 durable queue/budget recovery and actual server topology remain TS-13/14/17; no cross-process or remote cancellation claim |

Actual proxy topology, server worker count/free account qualification, remote cancellation, real model accuracy, browser gameplay and durable Agent integration remain unverified. Direct arbitrary NaN/infinite shutdown arguments are a held developer-method hardening follow-up; production Runtime uses tested constant 2. Current /health means app liveness, not model readiness. Each of 16 declined-to-judge rulings/costs is preserved in the stage ledger; JSONL lost-update risk still requires TS-10, semantic/scoring corrections TS-06/07.

No production data migration/deployment, public upload, credential/player text inspection, new payment or actual Agent worker occurred. Progress/rulings: docs/superpowers/plans/2026-10-08-ts05-progress.md.
