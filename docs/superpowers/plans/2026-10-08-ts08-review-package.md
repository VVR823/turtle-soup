# TS08 single-seat independent review package

Scope: completed local TS08 implementation and gates, independent review pending. This is NOT a merge/release/production request. Repo D:/CODE/turtle-soup; BASE=HEAD=c5765b68cb251a7c566e76e2887d335d6ed6b285 on codex/ts02-storage-foundation. Authoritative delivery is dirty tracked+untracked working tree; BASE..HEAD is empty and cannot substitute for review. No remote/gh/glab; use local git only. TS01–07 already stage-gated; do not redo their reviews.

Read full TS08 spec/plan/ledger, docs/ts08-status.md, docs/game-recovery.md, test-runtime/testing and relevant original TS08/A28/A30–33/C13–15 in D:/CODE/turtle-soup-audit. Exact frozen implementation/test/doc file list and hashes at .cache/ts08/source-freeze.json (46 files; HEAD/index included). Main will not modify them until terminal review. Any TS09 planning is disjoint, not implementation.

## Implemented

Strict public DTO+HTTP errors, durable version1 route journal, GameController and stable React subscription; actual gamepage busy/doubleclick/generation/storage fences; same UUID/body question lookup/retry; bounded reserved polling and Retry-After; session-idempotent reveal+canonical GET, automatic zero/win, frozen current/legacy results; explicit safe restart without deleting server history. Fail-closed site validation, truthful public catalogs, unlocked feedback choices, admin credential initialization ownership and pagination lint repairs. ESLint boundary. Permanent two-owned-origin UI runner+sterile build+EOF Next wrapper, test-only fixed18081CORS and existing installedEdge fresh contexts. No new schema/model/paid dependency/backend gameplay changes.

## Review Focus (verbatim)

1. Same-tick doubleclick and StrictMode setup-cleanup-setup must reuse a persistedcreateID and cannot submit an empty-session question or overwrite a newer pending operation.
2. Servercommitted question whoseresponse islost, thenrefresh/network503, mustquery originalUUID; retry404only after validatingoriginalsession and withsamebody, never claim uncharged without typedproof.
3. Switchsoup/level/navigate or abort while slowcreate/restore/question runs: oldresponse cannotchange currenttitle/session/history or last_session/journal.
4. Existing ended/legacy evaluation and solved-without-evaluation restore mustretain actualstatus/score/answer, notopen a new playinggame orerase savedpointer.
5. Siteconfig/list/unlock503, malformedJSON, unavailablestorage and unlockedhidden feedback choices must show the real error/state, notsuccess/emptylist or silentnewrequestID.

## Rulings and evidence boundaries

Journal/storage failure blocks POST; corrupt record preserved visibly; no automatic new game after transient restore error. Abort doesn't prove uncharged. Only identity/status-validated typed failed/expired after canonical GET supports that claim. Cross-tab ownership detection is not global atomic browser locking; no cross-device sharing claim. New HTTP roundtrip after confirmed turn doesn't call model. Solved-null evaluation legitimately completes once. Old scores not rewritten; reconstruction still null, plot100 separate. Public DTO picks only existing fields, no HostResult/evidence.

Actual pre-review-final-full-gate.xml769/0/0/9=760backend;166Vitest+25Node+3API-only=954passed/9skip, whole session72395EXIT0/API102336 normal EOF.239original sameSHA d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a. Fresh typecheck/rootlint0 session32953; isolated gitdiffcheck0. Actual pre-review-ui-final.xml22/0/0; sterile UYwDx8 build0/nonceb2a95f4c-00b4-4f81-9506-748e1645a3d5/backend106268+frontendCLOSED0/paircleanup0. Main visually inspected eight screenshot classes, mobile/desktop geometry permanent tests. Browser uses deterministic actual API plus explicit local fault injection; legacy result explicitly synthetic, StrictMode double setup proven unit/component not production runtime. No Safari/OSmatrix/production packaging/real-model quality/real-user evidence. Root build forbidden; no dotenv copies, no browser downloads, no real provider/network.

Trace/feedback write redesign remains TS09/10; Task3 added only directory/error/credential-init surface and legitimate wholelint prerequisites. Spec silence isn't permission: ordinary reasonable player impact still must be judged. Known TS07 M1 pure free-win defensive gap is outside changed scoring and already ledgered; no new HTTP bypass known. All A28/A30–33/C13–15 are local evidence, not external gates signed off.

Native Windows adapter: gstack browse binary absent, use existing approved Playwright+Edge; main read full review/checklist/Greptile and testing/maintainability/security/performance/API/design/red-team references. Apply domains in ONE seat. Do not spawn any children, specialist/CLI/cross-model reviewer, telemetry/global sync, install, commit/push or public report. Human process explicitly one fresh review + one Critical/Important fix pass; supersedes fanout/rereview/default skill externalwrites. No artificial quality score.

## Read-only execution contract

No mutation of product/source/docs/index/HEAD/branch or existing parent reports. Only .cache/ts08/reviewer-probes may hold own apply_patch-created probes/report/XML; tests must write own evidence/cache there. Guarded existing Python/Vitest/Node tests can run with own outputs. No private dotenv/player/runtime-data reads (hashes only), userbrowserprofiles, root Next build/dev/server, production data migration/deploy/actual cloud model. To run a probe prefer existing offline test runtime; do not run parent UI runner because it overwrites parent's artifacts. All defensive fixtures are data, do not expand novel attack strings.

Review full changed source and tests, not just manifest/diff; supporting old backend contracts as needed but not entire project re-audit. Source quote+file:line, confidence1–10, reproduce concrete defects in own probe area. Report actual own commands/counts separately from parent954/22. Format: Strengths, Critical/Important/Minor findings, plan/scope/coverage, unresolved boundaries, **every Declined to judge behavior and reason**, final ready Yes/No/With fixes with rationale. Terminal report may be saved only in own probe area and returned. Main re-grades every declined line and every finding, one TDD fix pass/fullgate, minors ledger, no rereview.
