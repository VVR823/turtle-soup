# TS15 Candidate Review and Publication Implementation Plan

> Native main execution using executing-plans/TDD; ONE inherited clean whole-stage peer, ONE native C-I fix, all Declined individually ruled, Minor ledger. User explicit continuous delegation overrides new phasequestions/commits/worktrees/extraagents. DESIGN ONLY until actual TS14 solepeer closure; all boxes unchecked are pending work, not evidence.

**Goal:** Make the existing private admin feedback flow usable for scoped task navigation, explicit human semantic review, atomic candidate publication and history-preserving rollback.

**Architecture:** Existing003 candidatebody/steps remain immutable; runtime_meta stores closed reviewCAS+append-onlyoperation receipts. CandidateReviewStore provides current/private material and server-only sameconn authority over existingRulePublisher. Trustedoptionalrepair_corpus wires existingFrozenDataset/FixedRegression to loop+review; ordinarygamepath unchanged.

**Tech Stack:** ExistingPython/Pydantic/SQLite/FastAPI/Next/TypeScript/pytest/Vitest/ownedEdge; no newdependency/provider call.

**Spec:** docs/superpowers/specs/2026-10-10-ts15-candidate-review-design.md; originalTS15/A54–56/C18/D3/D7/D11/D24.

## Global constraints

- Preserve immutable001002003/checksums/defaultmigration001/application002; candidateAPI existing003-only mode=rw, no auto initialization/migration. DefaultENABLE_AGENTfalse/singleAPIworker; old budget10/8/180/lease60/HB10/standalone30/local2/agent1 unchanged.
- CanonicalUUID/digests, strictrealinteger versions0..9223372036854775807/no extras/duplicates/NaN/Infinity, mutationbody32KiB; frontend refuses unsafe integers rather thanrounds. Notesnonblank1–1000Unicode codepoints, two explicithumantrue confirmations only forapprove.
- Listsdefault50/max100/scopedcursor/default7days/max31days, no fullhistory N+1. Detail<=512KiB UTF-8/no truncatedfacts/failures. Existingfixedcorpusonecatalog/1–100cases/server-onlyFrozenDatasetdev|regression, noholdout/automatic discovery/cloudjudge.
- No private user/env/corpus reads, actual provider/productiondata/deploy/upload/publish/commit/push/globalwriters. Native fixtures/publication are isolateddeclaredsynthetic, not realhuman/modelquality/productionevidence.
- CandidateJSONstatuspending/FinishRecord/runoutcome unchanged; workflowstatus separate. Freshsource/code/base/corpus checks for mutations; historicalpinnedmaterial only ifcurrentprivacy/source intact, no execution permission fromread.
- One whole-stage peer after actual nativewhole/UI/build/lint/type/link/hash/freeze; everyfinding/Declined regrade, ONE C-I nativeRED→GREENfix/currentregression, Minorledger; no perunitreviewers/secondopinion/CLIagent.

## Review Focus

1. Publish then lostresponse/anotherpublish/rollback: exactsameintent replays originalminimalack without repeating work or treating oldpointer ascurrent; changedcandidate/verb/body under samekey409 (Unit2).
2. ReportCandidateDraft digest differs from publicationChangeDraft digest: verifybothactualsources, never authorize mismatchedbody by comparingwronghash (Unit1).
3. Approval race with privacy/source/base/corpus/code withdrawal and faultafterreleasebeforecandidateupdate: no secondtransaction/partialpointer/forgedfreshproof (Units1/2).
4. Admin token/page changes while list/detail/approve/publish resolves: oldprivatecontent/uncheckedconfirmations/nonce mustnot crosssession orbecomeanotherapproval (Unit3).
5. Published/historicallysuperseded candidate afteroriginal180sexpiry: readonlypinnedhistory remains visible ifprivacy/sourcevalid, originalAgentStatusstillvalid; history isnot newapprovalauthority (Units1/2/3).

## Unit1 — source-bound private detail and actual review receipt

Files: create backend/app/candidate_review_contracts.py, candidate_review.py; modify runtime.py/main.py onlyfortrustedrepair_corpus, existingFixedRegression construction; audit_events.py for closed candidate review/publication details and enumconsumers; agents/regression.py explicitnewexecutiondeps AFTER native omissionRED. Tests create test_candidate_review_contracts.py, test_candidate_review_proofs.py, test_candidate_review_store.py, test_candidate_review_corpus.py; extend existingTaskContext/candidate/AgentStatus boundary fixtures only as needed. Do not change SQLmigration or toolcapability.

Consumes: CandidateRecord/RegressionReport/RunRecord/FinishRecord, existingAgentStore existing003tx/checkedidentity, task_context._freeze, actualfactcatalog/ExactTarget/validate_candidate; FrozenDatasetverify/load_repair_corpus and FixedRegression._suite_identity. Produces closed CandidateApprove/Reject/Publish/Rollback, CandidateReviewDetail/OperationResult/AgentRunPage/ReviewState, CandidateReviewStore(runtime).detail/approve/reject/list_runs with signatures in spec; server conversion publication_draft(candidate, confirmations)->ChangeDraft, actualhumanReviewReceipt and immutableintent receipts.

- [x] RED native missinginterfaces; literal contractlimits/bodyextra/duplicate/nonfinite/booleanversion, trueconfirmations/nonblanknote0/1001fail, exactsynthetic candidate/proof/draft schemas. Test test_candidate_and_publication_digests_are_distinct_and_both_bound: assert report.draftDigest == digest(candidate.draft), receipt.draftDigest == digest(publicationDraft), valuesdifferent; changinganswer/evidenceSummary/op/target/facts invalidatesbinding/approval.
- [x] RED detail realowncomplete fixedregression/pendingcandidate with honest synthetic fixtures: allsourcefacts/qualifiers/userclaim/modelsummary/actualdiagnostic/cases preserved, oldnewuniquetarget; foreign/missing/incomplete/corruptreport/body/finish/result/source invalid cannotbecome ready. Test privacywithdrawal minimalonly; hotcode/changedcorpus/base only historyread/noapprove; deadlineelapsed readable; detailbytes>512KiB controlledrefusal/no silenttruncate. All claimed red failures are actual assertions/interfaces, not setupbrokenfixtures.
- [x] Implement short existing-only003 transactions, private detail snapshot/historicalprojection, virtualpendingreviewVersion0 onlycoherentSQL, firstreviewmetaCASrow1, approvestoredproof+receipt+candidateSQL+typed audit+operation together; rejectstale pending|approved/currentCAS finalrejected/no pointerchange. Idempotent exactsameoperationreplaysminimalack beforefreshsourcechecks, changedaction/body/candidate409; checkreceiptcanonicalschema/actualintentbody/result/fullbindings/no overwrites. Test test_approved_metadata_without_actual_approval_operation_is_not_authority: missing/foreign/changedapprovalOperationKey/flags/note/receipt/subject/resultversion failsclosed/no publication; onlyactualboundapprovedoperation and receipt enablefreshpublisher. No genuine report fabricated to unblocktests.
- [x] Trusted create_app(...,repair_corpus=None)/Runtime plumbing beforemodels; strictFrozenDatasetonecatalog1–100 dev|regression/not holdout, worker+reviewuse sameactual corpus. Missing/altered/foreign/synthetic-for-real failsclosed. No corpusdefault remains safe/no modelimportallocation on disabled/read paths; source registry guards newactualdeps genuineRED beforeadding.
- [x] GREEN native files+existingTS14/TS13/tool/publisher/host/audit controls, whole offlineXML/isolation239hash. Record actualnativeinterface vs semanticRED vs alreadygreen controls, don't callunitcomplete beforefullterminal. No reviewer yet.

## Unit2 — one-transaction publication, current-pointer rollback and replay

Files: candidate_review.py/contracts, rule_publication.py internalfactoring; audit_events.py enumdetails/allconsumers needed; tests create test_candidate_review_publication.py, test_candidate_review_rollback.py, test_candidate_review_races.py; existing test_rule_publication.py/rollback/suspension/host/cache/AgentStatus regressions maintained.

Consumes Unit1 actualapprovedReviewState+CandidateOperationResult and serverChangeDraft; existing RulePublisher(authorizer), PublicationRequest/RollbackRequest/RulePublicationResult. Produces RulePublisher.publish_in_transaction(conn, request), rollback_in_transaction(conn, request) and preserved publicwrappers, CandidateReviewStore.publish/rollback. SamecallerownedBEGIN IMMEDIATE/current003; authorizer cannot suppliedbyHTTP/LLM/defaulttesting.

- [x] RED native actualcandidate+completecorpus approvedscenario -> serverpublish changesexactlyone release/pointer/candidateworkflow/reviewledger/operation/audit together. Representativeliteral assertions:

```python
assert candidate_after.status == "published"
assert pointer_after.row_version == pointer_before.row_version + 1
assert release_rows()[0] == original_release
assert agent_status_after.state == "awaiting_review"
assert original_completed_steps_after == original_completed_steps_before
```

Test two barrier-controlled distinctpublisheroperations/currentexpectedpointer one winner+one409/no dupe; staleexpectedversion/receipt/permission/target/code/corpus deniesallwrites. Site/Agent/fabricatedcallerreceipt cannotinvokeauthority.
- [x] RED faultrelease/pointer/candidate/metadata/candidateoperation/ruleoperation/audit/commit: whole snapshot identicalbefore/after. RED exactsameoperation replay afterpublish/anotheractivepointer/rollback/permissionwithdrawal returnssamehistoricalminimalack withoutfreshexecution; changedbody/candidate/action409. Existing002wrapper idempotence/rollback and defaultauthorizer guards retainliteraloldbehavior.
- [x] Implement internalfactoring without commit/nestedconnection; same003 candidate transaction verifiesliveactualapproval/authority, serverconstructsrequest/callbackuses SAMEconn, existingrulemutation then candidate status/reviewCAS/audit/operation; any failure rollbacksall. Freshpublication currentpointer checks mandatory; prioroperationreads areNOTauthorization. Do not mutate FrozenDatasetlabels/oldcandidatebody/FinishRecord.
- [x] RED rollbacktargetrelease/currentpointer/suspendedtarget/blockedsource/selftarget; literalnewsession afterpublishanswercorrect/pinnedoldsessionunchanged/cachekeyversionschange, rollbacknextnewsessiontargetanswer/restoredcache semantics; no newturn/history/candidate/release deleted. GREEN allUnit1/2 +publisher/rollback/suspension/cache/host/scoring/AgentStatus, currentwholeofflineproof beforeunitcheckbox.

## Unit3 — strict private HTTP and human-usable admin flow

Files create routers/admin_candidates.py, src/lib/agent-review-contract.ts and tests, src/components/AgentReviewPanel.tsx and tests; modify routers/agent_runs.py boundedindex, main.py registration, audit_events.py ALLnewtemplate/enum mapping, src/app/admin/feedback/page.tsx focused integration. Test create test_candidate_review_http.py/test_agent_run_index.py, existing request/rate/trace/privacytests; src/app/admin/feedback/agent-review.test.tsx; ownedUI fixture backend/app/testing.py/test_server.py onlystrictTESTING shape; tests/ui/admin-agent-review.spec.ts. No dependencies/liveBrowser/siteuse.

Consumes Unit1/2 typed Store, existingprivacyreview/CAS, TS14start/status/cancel and admin auth/rate/StrictJSONRoute/bodylimit/audit. Produces spec6 private index/detail/approve/reject/publish/rollback paths; GET30/min/mutations20/min/003only evenAgentdisabled. AgentReviewPanel(token,feedbacks,onFeedbackChanged) and strict decodeAgentRunPage/decodeCandidateDetail/decodeCandidateOperation/decodeAgentStatus APIs; no component invents sourceversion/permission/receipt.

- [x] RED independentadmin/XSite denial/configmissing/002unavailable/no missingDBcreated; strict32KiB/extraauthority/duplicate/nonfinite/strictversion/canonicalids/409CAS/replayrate bucket pathchangingID; schema003read/rejectwhileAgentdisabled withoutgateway. Taskindex default50max100/7–31days/cursorbound/orderedcreated_id/privacy/noN+1/corruptrowcontrolledfailure. Attemptaudittests actualregisteredtemplateneverunmatched/rawID forALLnewpaths, candidate eventtypedconsumer/traffic correctlytest vsreal.
- [x] RED frontend responsecontracts literalownIDs/nonce/action/digests/limits/versionbounds/historical vscurrent pointer and budget; unsafeJSONinteger refusesmutations, unavailable isn'temptylist. Controls note0/1001/blankfalse/1 reject/uncheckedsemantic/privacy not autopermitted; clientcannotsetdraft/facts/suite/model/role/traffic.
- [x] RED token/epoch/navigation/disposal controlledlate list/detail/review/publish responses cannotrestoreoldcontent/checks/note/nonce; duplicateclick oneinflight/sameintentnonce only; timeoutcommittedresult thenmanualrefresh seesactualstatus/activepointer, no automaticnewpublish/409retry. Publishedhistoricaldetail rendersoriginalrunoutcome+candidateworkflow+originalproof separately, not fake completednewAgentrun.
- [x] Implement reviewed sanitizedquestion/context/claims/privacyeditor usingexistingprivacyroute, manualcurrentversionconfirm thenapprovedsafeonlySTART. Separatecandidate semanticapprove and publicationclick; actualfacts/qualifiers/report/oldnew visiblefirst, nocheckbox defaultsfromgreenreport. Rejectstale andcurrentversionrollback withreason/loadedtarget; activevisibleone-run >=3sec boundedpoll stops terminal/401/429/logout/unmount. Retainfeedbacklist/token/UIrecoverybehavior; livegame not Agenttrigger.
- [x] GREEN native/frontend contracts/integration/currentwhole and ownedEdge29existing+newgenuinefullsyntheticadminflows privacy/start/status/approve/reject/publish/newsession/rollback. UI fixtures onlytest-only currentrealstore/evidence; no seededfakeapprovedcandidate masqueradingas realhuman/provider proof. Record completeflow missingcorpus/awaitreview/history labels and normalownedclose/original239SHA/build/lint/type.

## Unit4 — docs/current gates and ONE stage review

Files docs/candidate-review-reference.md, candidate-review-explanation.md, ts15-status.md, README.md; docs/superpowers/plans/2026-10-10-ts15-progress.md and autonomous-progress.md. Noresume fabricatedqualitynumber or productiondeployment/CIclaim.

- [x] Document actualinterfaces/0..int64CAS/nonblank1–1000/corpus/historicalproof limits, pending vsapprovedvs published/Agentfinish distinctions, operatornoteprivacy/no paidjudge. Safeisolatedreproduction examples and currentproof links; currentstatus mechanical vsrealhuman/corpus/provider/productionheld separately. Verify everylocaldoclink/example/no undefinedcommand.
- [x] Current exactselected+wholeofflineXML/Eval denominators/ownedEdgefullnewandoldflows/sterilebuild/lint/type/diff/doclinks/original239SHA/normalownedshutdown. Freezechangedsource+dependencies/HEAD/index/Evidence; THENONEcleaninheritedTS15peer with originalA54–56/spec/plan/5verbatimReviewFocus/read-only/no extraagents and allDeclined. Pre-review snapshot2713/296/31,320source43evidence; SAME Feynman actual final/closed. Those are historical pre-fix, not current post-fix gates.
- [x] Readterminalpeer and individuallyregradeeveryC/I/M + EVERYDeclined usingactualsource/testevidence. NativeONEC-I RED→GREENfixpass and freshwhole/UI/hash; Minorledger only, no secondpeer/extraCLIaudits. Closeactualpeer, markLOCALengineering onlywhen evidencecomplete; do notclose externalhuman/provider/corpusproductiongatefromfixtures. Actual2737offlinePASS10skip/312selected/31Edge/build-static0/original239sameSHA; allrulings in ts15-review-resolution, originalpeercompleted/closed.
- [x] Synchronize docs/ledger/resumepoint and nextTS16 design, nohumanstagequestion. Finishglobalgoal/disableheartbeat ONLYwhen allauthorizedlocal18stages and explicitdeliverables/gates actuallyachieved; anyexternalwithheldsubset remainsaccuratelyrecorded. Handoff: 2026-10-11-ts16-preflight.md is grounded DESIGNONLY entry; formal TS16 spec/plan and all TS16–18 implementation are explicitly next, not already complete. Goal/hourly remain ACTIVE.

## Self-review and sequencing

All originalA54–56/C18 mapped: fullmaterial/manualsemantics+boundreceipts Unit1/3; concurrentpublication/version/authority Unit2/3; reject/newsession/cache/rollback/history Unit2/3. FiveReviewFocus eachhasnative/UItest owner above. Sameconnhelpers have exactinterfaces, internalproofvsChangeDraftdigest split and separateworkflowcounter are unambiguous; no invented SQLcolumn or undeclareddefaultauthorizer. Privacyeditor is required to makeexistingreviewedfeedback->task usable, not unrelatedfeature. Current spec is the decision source, not test evidence; no perunitpeer/commits/install. TS14 sourcefreeze remains untouched during thisdesign.
