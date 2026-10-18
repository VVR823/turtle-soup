# TS17 D18: explicit missing post-publication source

> Inline execution with TDD under the approved TS17 design. ONE whole-stage reviewer later; no per-task peer. Original D18 count/source deliverable is retained, not declared completed by this metadata change.

Goal: make missing post-publication regression evidence explicit in private metrics, including exports. Do not steal failed tasks or pre-publication preview tests as this metric, do not create a false zero, and do not infer quality from completed synthetic tests.

Ruling: source integration remains HOLD pending a defined trustworthy post-publication execution/report/release binding and appropriate labels/provider authority; TS17 spec explicitly permits unknown/HOLD. Adding arbitrary scalar/event ingestion now would invent authority rather than establish evidence. Cost: actual post-publication count remains unavailable and original full A57 remains incomplete.

Ruling: required metadata changes the CLOSED private wire contract, so MetricsPage/Export become schemaVersion2. Metrics query/cursor, database001–004/checksums/default migrations, game protocols and audit events remain unchanged. Old private responses/clients fail closed; no silent fallback/mixed deployment. Cost: old admin JS requires synchronized release, not a production deployment authorization.

Interfaces: MetricsSummary.postPublicationRegression exactly `{state:'unknown',failedRuns:null,observedRuns:null,reason:'source_not_integrated'}`. Backend/frontend closed decoding reject absent/extra/coerced/count-zero/known-source claims. Existing coverage remains explicitly scoped to instrumented events; UI must not imply all required statistics are present. Full exports retain the same object even when `complete:true` means the group snapshot is complete.

Files: backend/app/metrics_contracts.py; src/lib/metrics-contract.ts; src/components/MetricsPanel.tsx; shared tests/frontend/metrics-fixtures.ts. Tests: new backend/tests/test_metrics_missing_source.py, existing backend metrics HTTP expectation2, new frontend contract/component cases; owned tests/ui/admin-metrics.spec.ts later gets real unknown/export assertions. No data read/write/migration or model calls added to collector.

- [x] Native RED: current actual GET/export must show schema2 and exact null unknown object; direct summary should not invent counts. Negative nested scalar/state/private/source inputs rejected. Initial metrics-source-red.xml: 3FAIL6PASS; supplemental revalidation-red-2.xml: 2FAIL12PASS with exact schemaVersion2 rejection.
- [x] Frontend RED: decode v2 null object/export; reject v1 and numeric/false-source variants; component shows unknown/source-not-integrated, not zero. Expectations constructed independently of production functions. Initial metrics-source-frontend-red.log: 3FAIL67PASS.
- [x] Minimal backend/frontend/schema fixture update. Change only private metrics response-version assertions, not cursor/baseline schema1. Selected backend203PASS; actual current whole99060 EXIT0/3231offlinePASS14existingSKIP (2760Python includesEval+365front+103Node+3API), typecheck/lint eachEXIT0. Existing pytestrootcache permission and Nodeenv warnings retained.
- [x] Add actual browser assertions to existing stats workflow/download. Owned Edge57659 actualEXIT0/33PASS0SKIP/88.514996s; real v2/null metadata on page/paging/27groupcomplete export, visible unknown desktop/mobile. Actual D8 wx JSON exists. Current wholeoffline also complete; fresh artifacts/ONE peer still pending. Evidence/report: docs/ts17-metrics-source-qa.md, new archive metrics-source-verified-20261012; no collector completion claim.

Global boundaries: zero new installation/provider calls, no Git/prod/public/global skill side effects. Preserve prior239hash/HEAD/index and unrelated changes. No full-project claim from selected tests and no claim that this implements the missing collector.

## Current evidence / recovery

Minimal correction after first implementation: old inherited real_schema validator still required1, so a default-constructed v2 page looked valid but export's defensive revalidation refused it. Supplemental native test first reproduced it; validator now checks exact int against the model's declared response version, not loose membership or coercion. Cursor1 and DB schemas are untouched. First failed selected attempt (metrics-source-green.log/xml: 12FAIL142PASS) is retained.

Test correction: component DOM assertion used unsupported toBeVisible Chai extension; existing Vitest does not register it. Switched only this assertion to actual textContent, no dependency/install. Failed first attempt (metrics-source-frontend-green.log: 1FAIL69PASS) retained. Supplemental RED initially also used Python model_validate on JSON tuple arrays; use real model_validate_json then model_dump revalidation, with both failed logs retained, not attributed to production.

Actual fixed selected native36161 terminalEXIT0: 203PASS/0SKIP/57.76s (metrics-source-fixed-green.log/xml); frontend selected EXIT0: 70PASS/2.38s (metrics-source-frontend-fixed-green.log). All original metrics suites included (contracts/HTTP/queries/baselines/query plan/migrations/benchmark/UI volume); selected evidence is not the whole-project gate. Current browser assertions added for v2 + exact unknown/null metadata on page/paging/complete download + desktop/mobile visible unknown; actual browser execution pending.

Goal actual blocked at this heartbeat check, not paused; no supported resume API and no new request to pause. Ordinary usage actually allowed (5h86%, week73%, cards0 at check time); continue unaffected authorized local work, do not claim goalACTIVE or ask user to click. Existing hourly automation actualACTIVE/currentchat. ONE TS17 whole-stage peer, final full current gate and fresh release artifacts remain pending; original missing collector/real-source integration remains HOLD.
