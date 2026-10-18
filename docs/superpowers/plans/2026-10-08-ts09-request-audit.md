# TS09 request audit implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every HTTP attempt is separately traceable, core game writes have transactional audit, and audit failure stays visible without duplicate charging or private response leaks.

**Architecture:** Add registered002 atop immutable001; an owned request context collects safe metadata for an outer ASGI attempt event. Core transaction events and separate bounded fallback/recovery/private pagination share strict event contracts, not raw trace text.

**Tech Stack:** Existing Python3.11–3.13/FastAPI/Pydantic/SQLite/HTTPX, pytest/FakeModel/MockTransport; no new service/model/dependency cost.

**Spec:** docs/superpowers/specs/2026-10-08-ts09-request-audit-design.md; original TS09/A34–36/C16/D11/D14/D24.

## Global Constraints

- Do NOT touch product/tests until sole TS08 terminal review+onefix/fullgate complete. While it runs, only disjoint TS09 docs/read-only exploration; preserve all frozen46files/HEAD/index.
- Immutable001 SQL/CHECKSUM_001/backfill and default migrate target1;002 independent shorttransaction, no003 references. ExistingDB read-only required2 preflight beforeWAL, no startupupgrade/productionmigration.
- Zero paid calls/install/upload/deploy/credits, no private dotenv/player contents or userprofiles. Preserve dirtycheckout; no commit/push/global telemetry/sync. Tests use owned synthetic directories and existingguards.
- One eventId perHTTPattempt; same requestId/turnId maylink manyattempts; business events notduplicatedonreplay. Model calls remain outsideDBlock; loggerfailure cannotreruncommittedturn.
- Strict frozen extra-forbid safe eventDTO; noquestion/reply/bottom/prompt/credential/IP/headers/rawreasoning/exceptiontext. Missing/invalid tokens NULL, not0; lateworker cannotmutate sealedattempt.
- Fallback≤1000records/1MiB, event≤16KiB, evidence≤128IDs/each200chars; typedoverflow/gapstatus, no silentdropping/overwriteoldrecords. DB audit busytimeout≤250ms; syncIO offeventloop.
- Admin separatetoken, list default50/max100, time default7days/max31days, stablecursor. No unboundedadminreads/newdashboard;002 requiredbeforeM2write.
- Stage onlyonefreshindependentreview(inheritedmodel,cleancontext,read-only,ownprobes), oneCritical/ImportantTDDfixpass+gates, minors/declinedrulingsledger, no rereview/fanout.

## Review Focus

1. A core turn already committed but HTTP audit/fallback fails: originalresult mustreturn and sameUUIDreplay mayadd attempts but cannotdoublecharge; refused transactional business audit cannot partiallywrite.
2. A slow modelworker finishes after disconnect/finalizedattempt while anotherrequest runs: no metadata/token/source contaminates the newevent or rewrites the oldevent.
3. Startup or isolated CLI meets an existing001/malformed002: verification remains read-only beforeWAL,001unchanged,002failure rollsbackonlythatphase, oldsourcefiles retained.
4. Repeated fallbackrecover encounters duplicates/conflictingID/partialtail/fullcapacity andthenfilecleanupfails: no duplicateevent, no lostunrecoveredrecord, permanentgap remains visible and secretsstayoffstderr.
5. Admin pagination filters/events cross an equal-timestamp cursor or wrong/site-only credential; no skipped/duplicate page, unboundedtime range, privateordinaryDTO or disguisedzero unknownusage.

### Task 1: Registered002 and guarded explicit migration

**Files:** modify backend/app/migrations.py/db.py/app/scripts/migrate_data.py; create backend/tests/test_audit_migrations.py; retain existing test_migrations/test_migration_cli/TS02 regressions. Own evidence .cache/ts09/.

**Interfaces:** `migrate(conn:sqlite3.Connection,soups:list[Soup],*,legacy_records:list|None=None,target_version:int=1)->dict`; `verify_schema(conn,*,required_version:int=1)->None`; appended AUDIT_SQL/CHECKSUM_002/requiredtables+index verifier. target1 report remainsoriginal001; target2 reportsmigrationVersion2 and original001report, phase002coverageStart.

- [x] Beforeanymigrationedit captureold001checksum/SQLcanonical digest underguardedfixture andpinliteral expectation; add tests `only001_default_remains`, `explicit002_contains_planned_tables_indexes`, `repeated002_preserves001_report_and_rows`, `phase002_each_statement_failure_rollsback_only002`, `checksum_gap_future_missing_index_rejected`, `existing001_startup_needs002_before_wal`. Assert2ledgerrows for002, existingIDs/counts/messagebytes/p1/r1 and1stchecksumidentical,000unknown/missingphase refuse, sourceSHA/copyunchanged. GenuineRED mustcome from absenttarget2/required2, notfixturepaths.
- [x] Add CLI `--target-version` typeint choices1/2 default1. Test `isolated001_to002_output`, `dry_run002`, `existing_output_and_runtime_alias_refused`; no defaultsources or productionCLIexecution. Pin old CLI001 tests unchanged exceptexplicitnewfixturepurpose.
- [x] Run `node scripts/test-backend.mjs backend/tests/test_audit_migrations.py backend/tests/test_migration_cli.py backend/tests/test_migrations.py -q --junitxml=.cache/ts09/migration-red.xml`; observeRED beforeimplementation; correctsetupseparately.
- [x] Append002registration+verifier/target2 logic; db.initialize newempty target2/existingrequired2 read-only; add isolatedCLI target, donotedit001SQL/backfill. Update old application-test fixture migration calls toexplicit2 only when they actuallybootM2; old001table/checksum/stop assertions NOTweakened. Samecommandmigration-green thencompleteoffline/hashgate; recordactualresult beforeTask2.

### Task 2: Strict attempt context and safe provider observations

**Files:** create backend/app/audit_events.py/audit_context.py; tests/test_audit_contract.py/test_audit_context.py; modify model_gateway.py for metadatahook only; extend tests/test_model_adapter.py or new test_audit_usage.py.

**Interfaces:** `AuditEvent` frozenstrict unionDetails; `AttemptDetails`, `BusinessDetails`, `ModelCallObservation`, `TokenUsage` asnamedinspec. `AttemptCollector(event_id:str,*,clock=time.monotonic)` with `bind_ids(...)`, `observe_host(host:HostResult,*,turn_id:str|None,versions:HostVersions|None,replayed:bool=False)`, `observe_model(call:ModelCallObservation)->bool`, `finish(*,status_code:int|None,method:str,route_template:str,response_started:bool,disconnected:bool)->AuditEvent`; finishseals once, lateupdatesreturnFalse. `attempt_context(collector)` contextmanager / `current_attempt()->AttemptCollector|None`. No HostJudgment/HostResultschemaweakening.

- [x] Write typedinvalid/unknownfields/negativeNaN/UUID/oversizeddetails/evidenceoverflow tests; nullunknown vsprovidedzero; noarbitraryrawmetadata; everyreasonCodeprogramowned. Named `context_same_requestid_distinct_eventids`, `concurrent_copied_thread_context_isolated`, `late_worker_after_finish_is_rejected`, `two_attempts_one_unknown_total_unknown`, `provider_invalid_usage_keeps_valid_answer`. Assert attemptmax2/evidence128/maxevent16KiB; no rawquestion/secret/reasoning serialize.
- [x] Runselectedguarded tests own contract-red.xml BEFOREimplementation. Addcollector withRLock/finalizeimmutable snapshot, strictJSON boundary; reuse HostKind/Source/Versions definitions, returnnullablehostfieldswithoutguessing.
- [x] Preserve adapter.invoke returnedcontent/AIMessage forHostJudgment strictvalidation. CompatibleAdapter parseonlysafe providerusage/model; InjectedAdapter knownAIMessage usage_metadata; programhookcollects eachactualattempt withordinal/errorcode, no modelwork on cache/noimplicit retry. Assert existingtiming/cancellation/cleanup/ownerlimits unchanged with MockTransport/FakeModel; neverrealprovider.
- [x] Runcontract-green, fullbackend/gatewaytests andwholeoffline/hashgate; record actual counts/unknownfields. Task2complete afterallnamedtests pass, notjustDTOconstruction.

### Task 3: Transaction events, bounded attempt store and full HTTP integration

**Files:** create backend/app/audit_store.py/audit_middleware.py; modify game_store.py/game_service.py/main.py/runtime.py/trace_logger.py focusedhooks; create backend/tests/test_audit_events.py/test_audit_fallback.py/test_audit_transactions.py/test_audit_http.py. Existingdiagnostic trace testsretained withexplicitlegacyfieldpurpose.

**Interfaces:** `insert_business_event(conn:sqlite3.Connection,event:AuditEvent)->None` noIOfallback, conn'scurrenttransaction only, phase2verify; `AuditStore(data_dir:Path,*,connect:Callable,clock=...,fallback_limits=(1000,1048576))`, `record_attempt(event)->AuditWriteResult` (db/fallback/dropped;neverrawexception), `recover_fallback()->RecoveryReport`, `status()->AuditStatus`. `AuditMiddleware(app,store)` outerASGI wrapperwithonecontext/event perHTTP; Runtime-owned store instantiatedafterverified002, boundedstartuprecover.

Async boundary produces `await AuditStore.save_attempt(event,*,wait_ms:int=500)->AuditWriteResult` (db/fallback/dropped/pending) and `close(*,wait_seconds:float=2)->dict`. RLock-owned admission max8actualIOjobs BEFOREto_thread; releaseonlyworkerfinally, notwaittimeout. Busy admission usesbounded1000/1MiBunpersistedmemory+explicitstatus, boundedflushat recover/close. db._connect mayaddkeywordtimeout default10 to preserveexistingcallers; attemptconnect passes0.25 BEFOREjournal_mode/WAL, no initial10sec exposure.

- [x] Write `two_same_http_requests_two_attempts_one_turn`, `creation_restore_reveal_attempts_link_actual_ids`, `cache_replay_failure_guard_body_validation_rate_all_recorded`, `disconnect_late_worker_sealed`, `diagnostic_flag_does_not_disable_business_audit`, `unknown_error_status_not_fake200`; assert metadataactualmatchingtypedresult, no raw responsebodyparse. All modelcalls Fake/Mock; auth/invalidJSON/body cases sourcedexistingregressions, do notexpandattackpayloads.
- [x] Write transaction injectionsat creation/limit-reminder/finish/expired/evaluation auditinsert: allassociatedbusinessrows/count/result roll back, required2 auditmissingblockswrite; replaydoesnotduplicatebusinessevent. `external_attempt_failure_after_commit_preserves_response_and_count` verifiesreturned200andoriginalUUIDrecover1charge. Errorpublic503onlysafe fixedcode.
- [x] Write fallback tests databaseexception→safeprivateeventfile, filefailure→boundedmemory/gap+safe stderrhash; count1000/byte1MiB/event16KiB boundaries; malformedpartialtail, eventIDpayloadconflict, duplicate recovery/cleanupfailure, retainunrecovereditems, persistentgapflags whenpossible. Assertnoquestion/reply/secret/facttext/rawstack instderr, neverrepeatcommittedask. Defaultincompleteonknownmissingdata, nofakeoldHTTPcoverage.
- [x] Pin `audit_io_admission_eight_before_executor`, `http_wait_timeout_does_not_release_actual_job`, `io_busy_buffer_is_bounded_and_unpersisted`, `audit_connect_timeout_set_before_wal`, `audit_close_two_seconds_reports_residual`. Useeventbarriers/injectedclock, notblockingnativeIO; cannotenqueue9th job orclaimmemorypersisted/workerstopped. AddgenuineRED beforeanyasyncqueueimplementation.
- [x] Runselectedaudit-events-red beforeimplementation. Addeventsinside ORIGINALshorttransactions (no model/file), normalizedprogramhooks andsealedASGIcollector wrappingCORS/BodyLimit/run_request; neverread ASGIreceive twice. AttemptpersistenceandfallbackIO viaawaitto_thread with250msDBbusybound; no unboundedqueue/retry. Trace legacydiagnostics switchremains butfailure nolongersilentwhenenabled; fallbackonlyattempt-safe DTO, notrawtracelines.
- [x] RunselectedGREEN thenwholeoffline/hashgate+TS08UI. Re-grade HTTPbusinessretry effect if logerror afterheaders; actualownedcleanupandunchangedruntimeSHA mandatory. Keep scopes/requestId setfromvalidatedreq, nottrustedheaders/unvalidatedquery. Task3complete onlyafterallfaultpaths.

### Task 4: Private bounded readers, documentation, one independent review

**Files:** create backend/app/routers/audit.py (routerspackageifabsent), tests/test_audit_admin.py/test_audit_query_plan.py; update test-runtime/testing/migrations/README/status/ledger; add docs/ts09-status.md/reviewpackage. No new frontenddashboard.

**Interfaces:** GET `/api/audit/admin` filters `limit:int=50` (1..100), `start/end:float|None` (finiteUTC defaultsnow-7days/now,max31days), `cursor:str|None` (strictbase64URLcanonical `{createdAt,eventId,start,end,eventType}`≤512chars, I4 fix binds effective first-window/filter; omitted later filters inherit, explicit mismatch422), `eventType` allowedenum. GETstatus returns safe AuditStatus; POSTrecover noarbitraryinputs returnsRecoveryReport; each uses `_require_admin`/ratepolicy. Stable ordercreated_atDESC,idDESC, explicitcolumns/parameterizedrangeSQL+LIMITlimit+1, nextcursor onlyowned row. PublicDTOnoeventdetails.

- [x] Write denied/missing/wrong/site-onlycredential, default50/max100/invalidNaN/range>31days, same-timestampcursorstablepages, invalidcursor, safeadminresponse/statusgap, recovernoarbitrarypath; ordinarysoups/search/game/errors/privatefactqueriesnotleak andlegitimateevaluate/endedstillwork. Synthetic5000eventsEXPLAIN mustuseidx_audit_events_time andboundedquery, nofetchallhistory. Newqueriesmustnotexposefallbackfile paths/rawidsoutsideadmin.
- [x] Runadmin-red, implementrouter+readonlyboundedstorequeries, adminstatus/recovery, preserveoldfeedbackroutesuntilTS10; adminwritesbusinesscoreauditalwaysrequired. Runadmin-green andfullguardedgate/UI/rootlint/typecheck/diffcheck; no externalOS/model/prodclaims.
- [x] Document factual fieldnullability/coverageepoch/fallbackmissinglimits/001vs002 migration instructions andwhyattempt!=turn; docs useonly syntheticexamples. ReviewFocuseachmapped tonamedTask1–4 tests; updatedoldtestsintentnotweakened, allcounts actualXML/stdout. Self-review deviationsrecord.
- [x] FreezeTS09source/HEAD/index, onecleanread-onlynative reviewer, ownprobesonly; originalscope+ReviewFocusverbatim+rulings. Independentevidencevsparentgates separate. Re-gradeeachfindingandDeclinedtojudge, oneCritical/ImportantTDDfixpass/finalwholegate/UI; Minorledger, nore-review/fanout. Marklocalverifiedwithconcernsaccurately thencontinueTS10; full18-stagegoalnotcomplete.

## Pre-flight and self-review

Task1required2 feedsTask3startupStore; default001migration retains priorstageindependentgate. Task2collector usesHostResultversions/source/evidence andnullableModelCall; Task3store usesAuditEvent privateDTO, transactionsborrowexistingconn; Task4readers consumeStore status/query/recover. No future003 references orundefinedendpoints. ModelGatewayreturnHostJudgmentstillstrict andreasoningdiscarded; invalidusage can't turnlegalanswerintosystemerror. Metadata collectorsealedbeforelatecallback; ASGIreceiveownership unchanged.

Spec requirementsall4deliverables; fivetopReviewFocuseachhasnamedtest. Exactconstraints copied; notanycodechangeswhileTS08reviewer active. Migration002UI fixturetestsettings newemptytarget2; realdataunchanged and no productionrehearsal. OriginaltraceENABLE false note correctedinpreflight. Plan self-reviewcompletebeforeimplementation; nativehumanexecutionmethod alreadysettled, no stageconfirmation/commit/push.
