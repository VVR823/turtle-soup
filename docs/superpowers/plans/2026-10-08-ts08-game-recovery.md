# TS08 game recovery implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh/navigation/network recovery retain a verifiable game and original operation ID without duplicate charge, misleading failure claims or false site unlocking.

**Architecture:** Framework-independent controller owns a single state snapshot and operation journal; strict public DTO decoding and HTTP error classification feed it. React page subscribes to current route controller. Site/catalog components reuse strict public directory loading. Permanent owned UI runner joins sterile frontend and guarded synthetic backend.

**Tech Stack:** Existing React19/Next16/TypeScript, Vitest5/jsdom, Playwright1.63, guarded FastAPI/FakeModel, SQLite001; no new paid dependency or model call.

**Spec:** docs/superpowers/specs/2026-10-08-ts08-game-recovery-design.md; original TS08/A30–33/C13–15, remaining A28 browser recovery.

## Global Constraints

- Source implementation starts ONLY after TS07 independent terminal review and its single fix/fullgate. While it runs, write only disjoint TS08design/plan/ledger.
- Preserve dirty checkout, previous reviewedstages/userchanges,001/p1/r1/scoring. No model, private dotenv/data contents, installs, production, publishing, commits/push or ACLchange/cachedeletion.
- Persist UUID and exact request payload before POST. Transient/unknown errors retain original journal and savedgame, never implicitlycreate; typedfailed/expired alone prove noncharge. 404/410 require explicit restart,401 reauthentication,429 Retry-After,503/network/protocol resumable.
- Current route generation/dispose gates BOTH UI and storagewrites. Immediatebusy gate prevents same-tick doubleclick or ask/reveal overlap. No global multi-tab locking claim.
- New reveal/ended refresh replay exact saved TS07 metric meanings. Keep original normal difficulty/egg/unlimited/win controls; public state noHostResult/evidence/privatekeys.
- Pending poll at most3queries, spacing>=1000ms;429 stops/respectsdelay, no infinite automatic retry. Manual sync allowed afterretrywindow.
- Default offline tests genuineguards and unchangedruntimeSHA; permanentUI own18080/18081+instanceIDfreshprofile only, abortotherorigins, no reusedserver/browserdownload. Standalone/OSmatrix/Safari/modelquality remain external gates.
- Main already fully read installed app/client/layout/Vitest/Playwright/CLI Next guides for TS07; refresh any additional specific installed APIs before changing Next source. Test APIs signatures verified from installedtypes/docs, no guessed frameworkhook.

## Review Focus

1. Same-tick doubleclick and StrictMode setup-cleanup-setup must reuse a persistedcreateID and cannot submit an empty-session question or overwrite a newer pending operation.
2. Servercommitted question whoseresponse islost, thenrefresh/network503, mustquery originalUUID; retry404only after validatingoriginalsession and withsamebody, never claim uncharged without typedproof.
3. Switchsoup/level/navigate or abort while slowcreate/restore/question runs: oldresponse cannotchange currenttitle/session/history or last_session/journal.
4. Existing ended/legacy evaluation and solved-without-evaluation restore mustretain actualstatus/score/answer, notopen a new playinggame orerase savedpointer.
5. Siteconfig/list/unlock503, malformedJSON, unavailablestorage and unlockedhidden feedback choices must show the real error/state, notsuccess/emptylist or silentnewrequestID.

### Task 1: Strict public contracts and durable journal

**Files:** create src/lib/game-contract.ts/game-contract.test.ts, game-journal.ts/game-journal.test.ts; modify api.ts/api.test.ts; create src/lib/catalog.ts/catalog.test.ts for shared publicdirectory transport.

**Interfaces:**
- `decodeCreation(input:unknown,expectedRequestId:string):CreationResponse`; `decodeSession(input:unknown,expectedSessionId:string,expectedSoupId:string):SessionSnapshot`; `decodeTurn(input:unknown,expected:{sessionId,requestId}):TurnResponse`; `decodeEvaluation(input:unknown):EvaluationResult` calls TS07 helper plus fullstring/array validation. Export types include requiredidentity/state/kind/freeflag and optionalpublic message turnId/isFreeReminder. Noprivatehostsourcefields.
- `readPending(target:GameTarget):PendingOperation|null`, `writePending(op:PendingOperation):void`, `clearPending(expected:PendingOperation):boolean`, `sameOperation(a,b):boolean`; version1 encoding and StorageError oncorrupt/writefailure. `newRequestId():string` uses browser crypto.randomUUID. PendingReveal no businessUUID; same session is identity. `getLastSession` oldcompatiblelevel validated asstring, malformedJSON never silentlyrewritten.
- `readSavedSession():LastSession|null` is the strictcontrollerreader and throws GameStorageError oncorrupt/inaccessiblestorage; legacy api.getLastSession retains its oldsafe-null compatibility but mustNOTdrivecontrollerautomaticcreate. Task2 consumes thisstrictreader, notthecompatibilityfallback.
- `ApiHttpError extends Error` has status:number,code:string|null,requestId:string|null,retryAfterSeconds:number|null; `apiJson(path:string,init:RequestInit={}):Promise<unknown>` require2xx+validJSON,401 remainsApiAuthError; `apiResponseJson` lowerlevel `{status,ok,body,headers}` supports503typedturn. Preserve existing apiFetch signature.
- `loadPublicCatalog({query?:string,signal?:AbortSignal,token?:string}={}):Promise<PublicSoup[]>` constructs encodedunlockedquery, optionaltoken forunlockwithoutpersisting, strictlyvalidatesarray/required publicid/title/surface/tags/difficulty and optionallimits/flags; noprivatebottom innewtype.

- [x] Write decoder tests `rejects_wrong_identity`, `reserved_has_no_answer`, `failed_requires_system_error_free`, `rejects_invalid_counts_roles_arrays`, `legacy_evaluation_stays_legacy`, `current_score_mismatch_rejected`. Exactcases 0..100integer,nonnegativecount,nullunlimited,wrongsession/requestUUID,primitive/malformedbody; assertthrow, notcoerce.
- [x] Write journal tests `create_id_before_send_roundtrip`, `ask_payload_immutable_same_uuid`, `route_key_cannot_collide`, `stale_clear_preserves_new_pending`, `storage_write_failure_is_visible`, `corrupt_record_is_not_overwritten`, `legacy_pointer_keeps_route`; assert storagethrows => nofakeIDcompletion. Write API/catalog tests 401/404/410/409/429/503/nonJSON/network,RetryAfterceilseconds,validempty vsinvalidlist,hiddenunlockedquery.
- [x] Run `node node_modules/vitest/vitest.mjs run --reporter=junit --outputFile=.cache/ts08/contracts-red.xml`; Expected productRED missingcontracts/journal/strictdecode. Correct harness-only defects separately, don'tcountsetupfailureasproductbug.
- [x] Implement namedfocusedinterfaces, stableerrors/minimaljournal andcatalog. Run samecommand with contracts-green.xml then guardedwholegate. Expectedgreenplus unchangedruntimeSHA; recordresult and Task1complete beforeTask2.

### Task 2: One game controller and actual page integration

**Files:** create game-controller.ts/game-controller.test.ts/use-game-controller.ts; modify gamepage,typesMessage optionalpublicmetadata; create src/app/game/[id]/game-recovery.test.tsx; retain TS07 evaluation-view tests with explicitupdatedrequiredtransportfixtures, no assertion weakening.

**Interfaces:** `GameTarget={soupId:string,level:string}` and `GameState={phase:'initializing'|'playing'|'asking'|'syncing'|'revealing'|'ended'|'error',session:SessionSnapshot|null,pending:PendingOperation|null,error:GameIssue|null}`. `GameIssue` classifiesauth/missing/incompatible/rate/service/network/protocol/storage/conflict withmessage/retryAfter,notfalsechargepromises. `GameController(target,deps)` exposes getSnapshot/subscribe/initialize/ask/reveal/synchronize/restart/dispose exactspecmethods; depsrequest allows abortsignal anddecodedresponse,storagefunctions Task1,now/newId andsleeptesthooks. `useGameController(target)` creates routeownedcontroller, subscribeswith useSyncExternalStore andeffect initialization/disposal; no render-time network/storagemutations.

- [x] Write events-controlled tests `strictmode_reuses_pending_create`, `double_click_sends_one_operation`, `empty_session_blocks_ask`, `late_create_cannot_write_new_route_pointer`, `late_restore_or_ask_cannot_publish_after_dispose`; assert originalUUIDbeforetransport,onePOST,allwritesvalidgeneration. Addstoragechanged-by-othercontrollercounterexample: stop currentwrites/signalconflict,not takeover.
- [x] Write `resume_transient_never_creates` for401/404/410/429/503/network/protocol, pointer/journal unchanged; `lost_committed_reply_queries_same_id`, `query_404_retry_same_payload_only_with_live_session`, `reserved_poll_budget_three`, `rate_limit_stops_poll`, `verified_failed_nocharge_vs_unknown_retained`, `reveal_excludes_ask`, `ended_restores_frozen_score`, `solved_without_score_evaluates_once`, `lost_reveal_get_restores`. Compare IDs,counts,messageuniqueness,status; notonly snapshots.
- [x] Add actualGamePage tests disabledbeforeinit,StrictMode,routeswitch,explicitrecovererroractions,unknownsubmittext,no“不会扣次数”,sameIDrefresh,old/newendedmetriclabels,restart explicit. Run `node node_modules/vitest/vitest.mjs run --reporter=junit --outputFile=.cache/ts08/controller-red.xml`; ExpectedproductRED.
- [x] Pin same-controller initialize/dispose/initialize StrictMode replay: new generation retires all old asynccallbacks and reusesjournalUUID; stable useSyncExternalStore snapshots/subscribedisposal verified against installedReacttypes. ExpectedRED if booleanreactivationallowsstaleoldresponse or reuseddisposedcontrollerneverinitializes.
- [x] Implement controllerandhook; replace page asynchronousbusinessfunctions withcalls/derivedstate whilepreservingTS07result/normalgameUI. Busy/erroraccessiblestatus and manualsync/retry/restart controls, don'tclear savedpointeronnavigation/reveal. Freebadgefromservermetadataonly. One canonicalGET afterconfirmedturn mayaddalocalroundtrip butnomodelcall; itprevents guessedcounts/duplicateoptimistichistory. Runselected+allfrontendandfulloffline/hashgate; ExpectedgreenandTask2complete.

### Task 3: Fail-closed site, truthful catalogs and lint boundary

**Files:** SiteGate.tsx/SiteGate.test.tsx; Home page/catalog-errors.test.tsx; difficultypage/catalog-errors.test.tsx; FeedbackButton.tsx/FeedbackButton.test.tsx; eslint.config.mjs; scripts/tests/lint-boundary.test.mjs; relevantpackageharnessentry.

**Interfaces:** Task1 `loadPublicCatalog` reuse withAbortController/currentgeneration onallcatalogconsumers. SiteGate stateschecking/locked/verified/unavailable; config `siteLocked:boolean` strict,tokenvalidationcatalogonlysuccessfulbody. Error UIwithretrydoesnotrenderchildren, preservesknownsavedgame. Feedbackselection includesonlyserverreturnedpublic/unlockedlist, nofakeownershipclaim.

- [x] Write componenttestsconfig503/nonJSON/noboolfailclosed,unlock503doesnotsaveoropen,401lock/authclearonly,no staleunlockafterunmount; homepage/difficultyloadfailurevsvalidempty,oldsearchresponsecannotreplacecurrent,hiddenunlockedavailableforfeedback,feedbackfailureallowsretrywithoutclaimempty. Runfrontendwithsite-red.xml; ExpectedproductRED.
- [x] Write lintboundaryNode test usinginstalled ESLint.isPathIgnored on .cache/.pytest_cache/backend/.venv/productionruntime paths andensures src/scripts/tests/confignotignored. Run `node --test scripts/tests/lint-boundary.test.mjs`; ExpectedRED omissions. NoACLchanges/deletion/wideglobprivatecontent.
- [x] Implement targetedcomponents/errorloading/sharedcatalog, preserveauth/history, smallmobilefeedbacksafe-area/contentpaddingfix forobservedoverlap (notredesign). GlobalIgnores exclude allbackendandcaches; explicitfrontendscript/configscope,neverdisableusefulrules tohidebugs. Runrootnpm runlint/typecheck/allfrontend/harness/fulloffline; Expected0 andno traversaloldcache. Recordoriginalordinarylintfindingsandlegitfixesifnewlyrevealed, don'tfalseclaiminitialscopepassing.

### Task 4: Permanent owned UI gate, documentation and independent review

**Files:** scripts/ui-e2e-server.mjs/ui-server-policy.mjs/scripts/tests/ui-server-policy.test.mjs; playwright.ui.config.ts; tests/ui/game-initialization.spec.ts/game-recovery.spec.ts/site-gate-and-privacy.spec.ts; docs/ts08-status.md/test-runtime.md/testing.md/README,ledger/reviewpackage. Existing API-onlyPlaywright unchangedandclearlylabeled.

**Interfaces:** ownports18080/18081 beforechildlaunch, randominstanceID, freshguardedtestbackendstdinEOFshutdown, sterilefrontendexistingbuilder andminimalenv, no externallyconfigurableproductionbaseURL; Playwrightnewcontext installedEdgeWindows/browseralreadyavailableotherOS. `npm run test:ui` runsownedhelper, testsuseownconfig verificationenv, no reuseExistingServer. Policy exports `validateUiFixtureIdentity(health,expectedId)` and `assertOwnedOrigins(requestUrl)`; testfirst beforeapplication/harnessimplementation.

**Testing integration:** modify backend/app/test_server.py only afterstage7gate toaccept explicitUI-testopt-in and fixed Settings.for_test CORS_ORIGINS=('http://127.0.0.1:18081',). Add backend/tests/test_ui_fixture_policy.py ensuringordinaryAPI-onlysettingunchanged and arbitraryoriginnotaccepted. Existingrealmodel/file/socketguardsremain. Browser serviceWorkers='block' preventsrequestbypass.

- [x] Write policytests occupiedportdoesnotrequestforeignservice,wronghealthinstance/provider/testingrefused,baseURLoverrideforbidden,childexit/closeownershipboundedcleanup; ExpectedRED beforemoduleexists. Unitmissingbrowser errorclearlyreportsnotverified, no browserdownload.
- [x] Implementharness/policy withownedcleanup andpermanent UItestsactualbackendrefreshended,requestlostaftercommitonecharge,sameIDrefresh/StrictMode/latereplynavigations,429/503invalidJSONsite/listpaths,playingnoanswers/revealexception/hiddenfeedbackchoice. Faultresponsesexplicitlyinjectedonlyatownedtransport; notmodelquality. RunpolicyGREENthen `npm run test:ui`; Expectedallnamedbrowserpathsactualpassing/screenshots, genuinefailureoutputcapturedandrootcaused.
- [x] Runsterileproduction-pagebuild,rootlint/typecheck/diffcheck/fulloffline/runtimeSHA pluspermanentUI. Recordactualcounts/screenshotinspection/childcompletion. MapA28/A30–33/C13–15; markrealSafari/OSmatrix/production/realmodel notverified. Documentation-generate reference/explanation evidence localonly; updateeachcheckboxwhentrue.
- [x] Freeze stage product/source beforeonefreshnativeindependentreviewer (cleancontext,inheritmodel,read-only,ownprobes,nofurtheragents). ReviewFocusverbatim+originalscope+rulings. Re-grade allfindings/declinedbehaviors; oneCritical/ImportantTDDfixpass/fullgate,minorsledger,no rereview. Genuine localcompletion thencontinueTS09automatically; full18-stagegoalnotprematurelycomplete.

## Integration pre-flight and self-review

Task1 DTO/journal/API names feedTask2controller; strict503businessfailed parsedbeforeHTTPexceptions; privatehistorynotused. Task2 sessionstatus/evaluationfeedsTS07display helperandpage; Task3gate/catalog publicshapeconfirmed actualbackendreturn `{soups:[...]}` and`siteLocked` (notearlierad-hoc tokenRequired fixture). Task4 usesTask1–3livefrontendandownexistingtestserver, mustnotbuildatrootdotenv. ExactfixturecopiesconfigCJSandlatestsource, API-onlycountsseparatefromUI.

Speccoverage: allA30–33plusremainingA28refresh/C13–15 assigned. FiveReviewFocuseachpermanentnamedcounterexample. Selfreviewcompleted beforeimplementation; no undefinedexternalpermissionornewbackendAPI. Noimplementationtest/sourcechangeduntilTS07review/fixgate. Use nativeexecution andexistingdirtycheckout underhumanapprovedcontinuousautonomy, notnewimplementationagent orstageapprovalpause.
