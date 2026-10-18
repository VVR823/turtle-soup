# TS17 agent HTTP audit characterization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans, current authorized inline execution; same ONE whole-stage reviewer.

**Goal:** Verify retained TS14 M1 against actual current persisted HTTP records without duplicating an already present registry change.
**Architecture:** Current registry contains start/status/cancel shapes; middleware already matches closed regex before router execution. Add native characterization to existing isolated Agent HTTP fixture, no product change unless evidence actually fails.
**Tech Stack:** installed pytest/FastAPI TestClient/owned SQLite/Fake blocked model adapter, no provider calls.
**Spec:** docs/superpowers/specs/2026-10-12-ts17-local-release-design.md; docs/ts14-review-report.md M1.

## Global Constraints

- No production/config/private data/network/Git write; existing own Event adapter released in fixture finally.
- Passing existing behavior is characterization, not fabricated new RED→GREEN or new implementation.
- ONE TS17 stage peer at end; current selected tests not full stage acceptance.

## Review Focus

- Actual successful start202/status200/cancel200 must persist three templates, not unmatched.
- CORS OPTIONS bypassing routing must persist closed template on all three shapes.
- Oversized-body rejection413 before routing must retain same shapes.
- Unauthorized401 records must not leak raw private path/header/query text.
- Audit observations must not change lifecycle/counts/permissions; cancelled task and zero model attempts retained.

### Task1: persisted HTTP audit boundary

Files: add tests in `backend/tests/test_agent_http.py`; existing `api` fixture, `start(api)` helpers and `raw_rows("audit_events")` actual SQL only synthetic.
Interfaces: runtime_context(active); AuditEvent.model_validate_json(row.details_json); Literal routeTemplate/statusCode/outcome.

- [ ] Add actualstart/status/cancel native test with literal ordered template/status pairs and cancelled/zero-attempt state.
- [ ] Add nine cases: three closed paths × CORS/oversized/unauthorized; check exact persisted status/template and no canary in typed event serialization.
- [ ] `node scripts/test-backend.mjs backend/tests/test_agent_http.py backend/tests/test_audit_http.py backend/tests/test_candidate_review_http.py --junitxml=.cache/ts17/minor-agent-audit.xml -o cache_dir=.cache/ts17/pytest-minor-agent-audit` verify actualgreen and record characterization (not RED).

Self-review: actual registry inspected already contains three paths; TS15 existing native test covers list/candidate routes but not retained status/cancel pre-routing branch. This closes a bounded missing proof, not speculative rewrite. Phase handoff/Git commit omitted per user autonomy.
