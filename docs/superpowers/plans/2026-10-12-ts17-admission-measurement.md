# TS17 D25 synthetic admission measurement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans, approved inline/TDD. Same ONE whole-stage reviewer after all TS17 local units.

**Goal:** Produce repeatable, auditable measurements for 100 simultaneous model-slot applicants, observed admission/queue/rejection and actual owner/driver cleanup, without a production throughput claim.
**Architecture:** A barrier releases exactly100 test-driver threads into the actual ModelGateway. Two benchmark-only blocking adapters hold owners until an observed2-active/32-queued/66-rejected plateau, then an Event releases and all outcomes are recorded. Caller timing includes deliberate fixture holding and cannot be equated to model latency.
**Tech Stack:** Python stdlib concurrent.futures/threading/SQLite-free installed backend runtime/pytest; no network or dependencies.
**Spec:** docs/superpowers/specs/2026-10-12-ts17-local-release-design.md D25; original section D25/TS17.

## Global Constraints

- Fixed100 applicants/max_active2/actual queue policy32; no product limiter changes.
- LOCAL synthetic transport; no real data/env/provider/paid calls/Git/production action.
- One raw record per applicant, failure never produces partial-success quantiles; diagnostic text excluded.
- Preserve existing TS16 200/1000/5000 measured evidence; no repeat or substitution.
- Before-upgrade matching benchmark/provider latency/RSS/HTTP100-users evidence UNKNOWN, no invented comparison or SLA.

## Review Focus

- Dropped/duplicated records must fail completeness, not produce healthy capacity claims.
- Deliberately held adapters must prove peak2/queue32/66busy before release, not sampled guess.
- Terminal outcome count must independently match actual adapter starts/closes34 and waiting0/active0.
- Transport/batch errors must close drivers/adapters and return fixed failed/no quantiles/no private text.
- CLI refuses args/database paths before running; imports stay inert.

### Task1: actual bounded100-entry batch

Files: create `backend/app/scripts/benchmark_admission.py`; create `backend/tests/test_admission_benchmark.py`.
Interfaces: `measure_admission() -> dict` no inputs; report schemaVersion1/evidenceKind declared_synthetic_benchmark/measurementScope model_gateway_admission_controlled_hold. Existing ModelGateway.snapshot/invoke/close untouched. `python -m app.scripts.benchmark_admission` prints one JSON and exits0 only complete, rejects any arguments.

- [ ] Native actual100 batch assertions: all ordinals0..99; initialAccepted2/queued32/rejected66; completed34/rejected66/failures0; peaks2/32;34 actual adapter starts/closes; cleanupconfirmed (gateway closed/active0/waiting0 plus driver shutdown), all raw elapsedMs finite nonnegative and conditional nearest-rank P50/P95 independently from raw records.
- [ ] Native forced caller-failure test through existing gateway method seam must produce statusfailed/fixedcode/noquantiles/cleanuptrue/no canary.
- [ ] Native child CLI argument refusal must run no benchmark; valid CLI actual JSON+exit verifies importable entrypoint and full raw records, not mocked script text.
- [ ] Run `node scripts/test-backend.mjs backend/tests/test_admission_benchmark.py --junitxml=.cache/ts17/admission-red.xml -o cache_dir=.cache/ts17/pytest-admission`, preserve genuine RED.
- [ ] Implement minimal benchmark-only adapter/Barrier101/test-driver pool100/Event release/bounded8s callers/5s plateau/finally release-abort-close-shutdown. Collect actual snapshots/records, no predetermined success values substituted for observation.
- [ ] Run selected native plus existing model admission/gateway boundaries, preserve fresh GREEN; standalone CLI actual report in .cache/ts17/admission-measured.json, then record current evidence. Whole-project suite remains final stage gate.

Self-review: current ModelGateway exposes active/waiting/closed publicly, actual31/32 controls exist, limiter uses at most2 owners and queue32. The100 threads are temporary benchmark drivers, not production allocation. Rule hit/miss+audit/trace disk growth are independently testable next D25 unit, not omitted or claimed by this report. User autonomy overrides commit/handoff prompts.
