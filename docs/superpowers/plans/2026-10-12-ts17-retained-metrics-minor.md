# TS17 retained metrics error translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans, approved inline/TDD. Same ONE TS17 whole-stage reviewer only.

**Goal:** Keep native SQLite interruption/busy classification across baseline SnapshotError wrapping, without treating corrupt snapshots as transient or changing baselines.
**Architecture:** query_metrics handles SnapshotError before generic exception; unwrap only explicit nested SnapshotError causes, pass terminal native SQLite error to the existing code-only handler. No message parsing or exception-text exposure.
**Tech Stack:** Python/stdlib SQLite/installed pytest, synthetic fixture database.
**Spec:** docs/superpowers/specs/2026-10-12-ts17-local-release-design.md; docs/ts16-review-report.md M1.

## Global Constraints

- Existing three-second total deadline/500ms decreasing timeout/query_only/rollback/close preserved.
- No migrations/checksum/default startup/provider/production edits; local tmp fixture only.
- Selected native evidence not final whole-suite or production proof; no new reviewer per unit.

## Review Focus

- Wrapped interruption in active pointer SELECT must remain metrics_busy503 (native progress callback).
- Wrapped interruption in rule release SELECT must remain metrics_busy503.
- Wrapped interruption in puzzle payload SELECT must remain metrics_busy503.
- Native permanent SQL error in each same SELECT must remain metrics_unavailable503/no raw SQL/private text.
- Reader connection actually closed on each failure; existing corruption/deadline/lock/cleanup regressions retained.

### Task1: wrapped native failure classification

Files: create `backend/tests/test_metrics_baseline_failures.py`; modify `backend/app/metrics.py` only.
Interfaces: existing `query_metrics(runtime, query: MetricsQuery): MetricsPage`, `baselines.SnapshotError.__cause__`, `MetricsError(code,status)` unchanged.

- [ ] Write actual SQLite connection subclass executing the three exact baseline SELECTs with progress_handler(lambda:1,1), not mocked exception/code. Literal expected INTERRUPT9/busy503 and native close proof. For permanent controls execute an unknown fixture table at the same boundary, verify native ERROR1/unavailable503 and no raw diagnostics.
- [ ] `npm run test:backend -- backend/tests/test_metrics_baseline_failures.py --junitxml=.cache/ts17/minor-metrics-red.xml` genuine RED; preserve log/XML.
- [ ] Add narrow `except baselines.SnapshotError as error` before sqlite3 handler; walk only explicit SnapshotError causes with cycle bound, raise native SQLite terminal cause to shared existing code handler, otherwise unavailable. Do not alter baseline validators or use message matching.
- [ ] Rerun native GREEN plus existing metrics queries/http/contracts/deadline/locks; fresh full project at whole-stage boundary, no success claim before evidence.

Self-review: current baselines catch sqlite3.Error with explicit cause; migrations.verify_schema calls active_manifest without swallowing it; query_metrics genericexcept currently loses cause. Root path verified, simple targeted translation justified. User autonomy supersedes phase handoff/commit; no external questions needed.
