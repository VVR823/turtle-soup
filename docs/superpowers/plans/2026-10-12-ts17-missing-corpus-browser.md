# TS17 D8: missing trusted corpus browser verification

> Execute inline with TDD. Spec: ../specs/2026-10-12-ts17-local-release-design.md. Existing stage ledger owns progress; ONE whole-stage peer remains pending.

Goal: prove genuine HTTP/browser refusal, not a stubbed ready/error response. This is bounded verification of the existing candidate workflow, not a new production capability.

Ruling: add a reversible control ONLY to explicit TESTING+fake+UI+owned-nonce fixture entry `app.test_server.fixture_app`. Standard `create_app` and non-UI fixture must return404. `POST /testing/corpus-availability`, closed strict JSON `{available:bool}`, exact X-Test-Instance-Id; selects only original independently frozen synthetic corpus or None, never caller data/path/labels. Native rejects unauthorized/malformed requests without changing state. Restore in browser finally; workers=1 prevents parallel test contamination.

Interfaces: existing linkedFeedback/candidateFromBrowser create real feedback/privacy/worker/tools/report/candidate through HTTP. Native positive control restores original corpus and permits the same otherwise-valid approval; missing corpus must preserve review/pointer/history and expose unavailable/material-null/proof-null, not manufacture a pass. Browser screenshot/DOM and actual response prove minimal disabled state; no network response stubs.

- [x] Native2426 EXIT1: genuine7FAIL/2PASS/0ERROR/23.886s, missing route404 rather than200/403/422.
- [x] Minimal fixture-only implementation; native45295 EXIT0/38PASS0SKIP/64.540s. Existing product refusal is characterization, not a new game/approval fix.
- [x] Genuine browser scenario actually passed14.945s: loaded approval POST409, refreshed unavailable/material-null/proof-null, no approval/publication, unchanged game/pointer, finally original corpus restored. Four screenshots observed by main agent; 375px no horizontal overflow.
- [x] Actual51836 owned UI gate EXIT0/33PASS/86.513314s, both normal closures, immutable archived outputs and docs/ts17-missing-corpus-qa.md report. Initial inline observation attachment omitted by list/简版JUnit; raw console count/exactwidth remain unknown until final gate records an owned JSON file. No product bug fix during report-only QA.
- [ ] Final current offline/type/lint/new release artifacts/whole-stage peer remain required; historical3199 is pre-fixture checkpoint, not current completion proof.

QA-only adaptation: zero-cost/user-private boundaries supersede skill global setup/upgrades/telemetry/sync/commits and foreign-server reuse. Use the established owned Edge/Playwright workflow instead of installing a browser daemon. Report only observed scoped behavior; unmeasured category scores remain unknown, never a fabricated whole-app100/100. No outside-workspace artifacts or memory writes.
