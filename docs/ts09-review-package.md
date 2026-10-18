# TS09 single-seat read-only review package

## Scope and authority

Review TS09 current uncommitted implementation against docs/superpowers/specs/2026-10-08-ts09-request-audit-design.md and docs/superpowers/plans/2026-10-08-ts09-request-audit.md. This is one fresh-context inherited-model native seat; no fanout, second opinion, fixes, commit, checkout/branch/index changes, production requests, real models, installations, private dotenv/player reads, or uploads. Own probes/reports only under .cache/ts09/reviewer-probes, synthetic directories, existing data/network guards. Never disable guards/alter ACL. Previous TS01–08 reviews already accepted, do not redo them except dependencies needed to judge this extension. Main is sole later implementer; source stays frozen until terminal review. Do not invent independent testing by repeating the parent's claimed counts.

Base and Head both c5765b68cb251a7c566e76e2887d335d6ed6b285, branch codex/ts02-storage-foundation, dirty authoritative checkout. BASE..HEAD is NOT delivery; inspect actual files/working diff/untracked files. Frozen file/HEAD/index SHA manifest .cache/ts09/source-freeze.json. No suitable remote/PR, no shipping authorization.

## What changed

Immutable001+independent002/required2/newempty2/CLI default1/preflightDB+WALcopy; private strict event contracts/sealed ContextVar/request-local safe gateway usage; original short transaction business events; separate bounded attempt SQL/fallback/RAM/gap/recovery; outer ASGI integration; independent admin time/cursor/LIMIT/mirror-validated reads. Public gaming DTO/authority/retries remain unchanged. Feedback writes remain legacy until TS10; 002 feedback table alone is not new publication.

Primary: backend/app/{migrations.py,db.py,audit_events.py,audit_context.py,audit_store.py,audit_middleware.py,model_gateway.py,game_store.py,runtime.py,main.py,trace_logger.py,scripts/migrate_data.py,routers/audit.py}. Dependencies: game_service/game_responses/request_lifecycle/request_contract/request_guards/host cache/context/evidence/schemas/config/baselines/model admission. Stage tests test_audit_* plus extended original test_typed_trace/test_request_disconnect/test_turn_failure_recovery and five explicit2 boot fixtures captured in freeze. Docs request-audit/migrations/test-runtime/testing/ts09-status and root/backend README.

## Binding Review Focus (verbatim)

1. A core turn already committed but HTTP audit/fallback fails: originalresult mustreturn and sameUUIDreplay mayadd attempts but cannotdoublecharge; refused transactional business audit cannot partiallywrite.
2. A slow modelworker finishes after disconnect/finalizedattempt while anotherrequest runs: no metadata/token/source contaminates the newevent or rewrites the oldevent.
3. Startup or isolated CLI meets an existing001/malformed002: verification remains read-only beforeWAL,001unchanged,002failure rollsbackonlythatphase, oldsourcefiles retained.
4. Repeated fallbackrecover encounters duplicates/conflictingID/partialtail/fullcapacity andthenfilecleanupfails: no duplicateevent, no lostunrecoveredrecord, permanentgap remains visible and secretsstayoffstderr.
5. Admin pagination filters/events cross an equal-timestamp cursor or wrong/site-only credential; no skipped/duplicate page, unboundedtime range, privateordinaryDTO or disguisedzero unknownusage.

Judge reasonable-user impact even where spec is silent. Include each considered behavior set aside with reason in a Declined to judge list. Re-grade by effect, not by omission from spec. Output concrete file:line / reproduction / why / fix for Critical, Important, Minor, then verdict. Distinguish observation, executed probes, inference, external gaps. Parent will rule on every declined behavior and do ONE important-fix TDD pass; no rereview.

## Test map and actual evidence

Focus1: test_audit_transactions (five full-row rollback cases, required table, replay uniqueness, expiry/limit/cancel, aftercommit metadata), test_audit_http external_attempt_failure_after_commit_preserves_response_and_count / unexpected_store_failure / safe503, original pair+commit failures preserved with real in_transaction wrapper property.

Focus2: test_audit_context copied-thread isolation/seal, test_audit_usage late gateway, original test_request_disconnect extended with immutable persisted event before/after late owner, http replay actualsource/cache/modelCalls/unknownusage.

Focus3: test_audit_migrations27 including permanent001 checksum e703a6f4ce5f102d0da973118dee3f08486b2e1f0c94a16ff5449acafe23f69b / SQLdigest abb9cd5e98f7625e3a123186167c049afb9a714b94184f67c2c67e8246006137, sixphase002failures, sourceSHM/WAL hash/copy race/CLI. Old migrate defaults001 and schema integrity tests retained.

Focus4: test_audit_fallback30: duplicate/conflict/actual commitfail/cleanupfail/badpartialtail/default1000/default1MiB/filefail boundedmemory/max8actualjobs/busy/awaittimeout/cancel/close actualresidual/startuprecover; gap SQL persistence when sidecar fails, emergency restart, WAL connection failure closes actualconn. Source filesystem durability/multiprocess not claimed tested.

Focus5: test_audit_admin36 + query_plan1: auth503/401/site-only, 50/100/finite/time31days/canonicalcursor/equalstamp, statusgap/recoveryNoPath/pending202/publiccatalog, mirrored row503, productionqueryEXPLAIN5000/timeindex/LIMIT4.

Actual parent latest gate42850 EXIT0 =974backend/9skip+182Vitest+25Node+3API=1184passed/9skip; .cache/ts09/pre-review-full-gate.xml983/0/0/9. API69660normalEOFshutdown,239sameoriginalmanifestSHA d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a. UI75328EXIT0=25/0 .cache/ts09/pre-review-ui.xml, sterile ECvD9k/nonce4ffbb67b-d952-4cb5-82e7-8649bfb15c8b/API68388/frontendCLOSED0/bothcleanup0. Rootlint/typecheck/diff0. Targeted98/0 .cache/ts09/audit-final-selected.xml. Earlier RED/GREEN/fixture mistakes and gatefailure honestlyledgered, not replaced. Parent final counts are not your independent evidence.

## Rulings / known limits

Read every Ruling in stage ledger. Full safe AuditEvent JSON in details_json mirrors root columns; session-only engine/normalization unversioned, actualtypedturnversions preserved. charged+replayed describes originaldecision, no newcharge. Postcommit callbacks only private metadata. Fallback memory explicitlyunpersisted, 500mswait keepsactual8slot, startup/recover bounded admission,2sclose actualresidual/no nativecancel. Stops at firstDBoutage, commits before cleanup, permanentgap monotone sidecar+runtime_meta; totalFS/process failure cannot preserve everything. Appnotstarted503 has no Store guarantee; historicalcoverage notbackfilled. Single-instance fallback only, OS powerloss/multiplewriters/largecoldstart/p95/realprovider/cost/realusers/productionmigration/deploy/upload notvalidated. TS08twoMinors andTS07free-win Minor deferredTS17/ledger, not TS09 fix claims.

Probes can use `node scripts/test-backend.mjs <owned synthetic probe> -q -o cache_dir=.cache/ts09/reviewer-pytest-cache --junitxml=.cache/ts09/reviewer-probes/probes.xml`, inherited offline guards. If environment blocks, report exact limitation, do not improvise unsafe paths/realconfig. Native Windows shell, no Bun daemon/global gstack preamble, telemetry/sync/upgrade/install. Prefer bounded actual tests/reasoning, not redundant full earlierstage reviews. End terminal report saved .cache/ts09/reviewer-probes/terminal-review.md and final concise verdict.
