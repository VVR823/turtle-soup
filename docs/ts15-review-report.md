# TS15 single-seat local engineering review

Scope: LOCAL candidate review, publication and rollback in `D:/CODE/turtle-soup`. This is the one inherited-model clean-context whole-stage reviewer, not TS16, another reviewer, a launch review or production acceptance. Findings: **0 Critical, 2 Important, 2 Minor**. Severity is advisory for the main's individual ruling. No fixes were applied.

## Scope and integrity

Read the full `.cache/ts15/review-package.md`, TS15 design and four-unit plan, the progress ledger's relevant rulings, original implementation-plan TS15/A54–56/context-independence requirements, acceptance A54–56, and the upgrade test plan including C18. Applied the requesting-code-review reviewer template and gstack review checklist for read-only judgement; the user's explicit single-seat/read-only instructions override their dispatch, fix-first, global-writer and CLI workflows.

The actual review target is dirty/untracked live source. Base = HEAD = `c5765b68cb251a7c566e76e2887d335d6ed6b285`; branch `codex/ts02-storage-foundation`. An empty HEAD-to-HEAD range does not describe this work. Read-only Git identity/status/remote inspection confirmed no remote origin. Index SHA256: `45C635EFDD2844F5A8DAC3CF3B6B7FBB4CAA6A54A2F247F3F8CC902C4CA275F5`.

At entry and again after source review, every actual manifest entry was hashed: **320/320 source entries match, 43/43 evidence entries match, 0 changes**. Manifest file hashes also match:

- Source: `C700F25BE03394D245D471DA8EA29D2E7C9ACAF2746B05C606BA5B01256D1459`.
- Evidence: `7A506F997BC0D9041AA0606F192570B72D6EB1D9552FBE21BF5D2A87135B4ED0`.

HEAD, branch and index remained unchanged at those checks. Compared the historical TS14 final source manifest without regenerating it: `migrations.py` still matches `2402CDB6104851F85BE3D2B0C066B3B9C69BDF4B6B72209619692BF34CE04BB9`. Inspected actual 001/002/003 DDL, checksums, triggers and defaults. There is no invented candidate `row_version` or `review_json`: review CAS uses `runtime_meta`; candidate workflow uses existing SQL `status/reviewed_at/published_release_id`. Application initialization remains 002, migration default remains 001, and Agent defaults remain disabled/one worker.

Only this standalone report was written, via apply_patch. No source, test, plan, spec, ledger, manifest, index or HEAD edits; no tests, gates, services, DB connections, browser runs, installs, fetches, external services, agents or messages. Real dotenv, private corpus and original player runtime contents were not inspected.

## Strengths and coverage

Read the full central candidate store/contracts, publisher, runtime, main, new/private routers, regression and source-identity mechanism, audit event contracts, admin panel/decoder/admin integration, feedback form/turn producer and owned UI fixture modules. Traced the affected portions of AgentStore, TaskContext, feedback privacy/source handling, public DB message projection and game page. Read transitive rule contracts/snapshots/preview/validation/tools and audit route/template/query consumers; searched new enum values through backend/eval/frontend consumers rather than assuming only the declaration mattered. Reviewed native candidate contract/proof/store/corpus/mutation/boundary/publication/rollback/race/size/HTTP/index tests, corpus and owned-worker fixture tests, original publisher/rollback controls, frontend decoder/panel/admin/turn tests, and both browser flow source cases. This is TS15 effect coverage, not a new audit of all accepted TS01–14 modules or unrelated user changes.

Specific strengths:

- Independent admin dependencies, existing003-only `mode=rw` transactions, closed bodies, actual integer versions and real true confirmations avoid site/model authority and implicit feature migration.
- `_immutable` checks the candidate row/body, original run, own completed regression step/result and final FinishRecord. `_review_state` requires actual latest and approval operations, not just plausible approved metadata.
- The report binds the full CandidateDraft digest; the human receipt binds the different ChangeDraft digest. Actual source checks and native assertions preserve that distinction.
- Publication calls `publish_in_transaction` on the candidate transaction's connection; release/pointer/candidate/review/two receipts/necessary audits share the commit. Fault tests inspect whole snapshots, including failures after release creation.
- Exact intent replay precedes fresh-source/pointer authorization, checks the saved rule operation/release for publication, and returns an historical minimal acknowledgement. Cross-verb/body/subject nonce reuse conflicts. It does not treat an old pointer version as current.
- Original Agent outcome/steps/budgets and immutable candidate JSON survive human workflow changes. Terminal historical detail has no fresh proof; source withdrawal hides material/review. Rollback moves a verified pointer and preserves later writes and pinned sessions.
- The website now supplies a real explicit turn-linked feedback path. UI fixture setup freezes synthetic sources/labels but does not seed a candidate, passing report or approval; the conditional synthetic worker actually creates them.
- Token-keyed sessions, epoch/Abort fences, one mutation lock, separate approve/publish clicks, initially unchecked semantic controls and exact-intent retry address substantial private UI races. Fact qualifiers and all report rows are rendered without silent trimming.

### Mandatory Review Focus (verbatim from the plan)

1. Publish then lostresponse/anotherpublish/rollback: exactsameintent replays originalminimalack without repeating work or treating oldpointer ascurrent; changedcandidate/verb/body under samekey409 (Unit2).
2. ReportCandidateDraft digest differs from publicationChangeDraft digest: verifybothactualsources, never authorize mismatchedbody by comparingwronghash (Unit1).
3. Approval race with privacy/source/base/corpus/code withdrawal and faultafterreleasebeforecandidateupdate: no secondtransaction/partialpointer/forgedfreshproof (Units1/2).
4. Admin token/page changes while list/detail/approve/publish resolves: oldprivatecontent/uncheckedconfirmations/nonce mustnot crosssession orbecomeanotherapproval (Unit3).
5. Published/historicallysuperseded candidate afteroriginal180sexpiry: readonlypinnedhistory remains visible ifprivacy/sourcevalid, originalAgentStatusstillvalid; history isnot newapprovalauthority (Units1/2/3).

Focus judgement: 1/2/5 have coherent source implementations and relevant archived native assertions; 4 has source fences plus controlled late-token/list/detail/approve/publish tests and browser flow integration. For 1, the exact publication replay after another independently successful publication was traced through source; the inspected dedicated native replay case specifically combines rollback, expiry and privacy withdrawal. Focus 3's DB withdrawal/write/fault/shutdown paths are covered, but non-DB corpus/code changes during a mutation have the Important gap below.

## Evidence inspected, execution and limits

**Tests executed by this reviewer: zero.** Inspected archived logs and parsed their XML records; no result below is a new run or an assertion of genuine human/model quality.

| Artifact | Actual inspected result | Limit |
| --- | --- | --- |
| `unit3-final-full.log/xml` | 2,414 Python records, 2,404 pass/10 skip/0 failure/error; exactly 412 records under `backend.eval.*`; 281 frontend, 25 Node and 3 API pass; total 2,713 offline passes | Eval is included, not added twice. Seven skips require real-model opt-in; three are Windows socket/symlink constraints. |
| `unit4-final-selected.log/xml` | 296 pass/0 failure/error/skip; log 186.56s | 16 native test modules including original publisher/rollback compatibility. |
| `privacy-draft-ui.log/xml` | 31 pass/0 failure/error/skip: 2 candidate flows + 29 existing browser cases; build exit marker 0 | Owned Edge/synthetic API. Actual approval lost-reply replay, separate publication, new/pinned old sessions, rollback and withdrawal/rejection assertions inspected. |
| `docs-example-native.log/xml`, `docs-example-frontend.log` | 76 native and 16 frontend example passes | Reproduction examples, not human acceptance. |
| `privacy-draft-type.log`, `privacy-draft-lint.log` | Commands recorded, no diagnostic output | Archived command logs; this reviewer did not rerun or independently observe their process exit. |
| Earlier browser/public-pair/privacy-draft failure logs | Earlier browser run has 23 passes and failed cases; public-pair native log has 2 failures/3 passes; draft log has 1 failure | Retained failures were not relabelled as successful flows. Current source and newer successful artifacts inspected separately. |

The full offline log records API118536's normal shutdown and original **239 files**, same before/after SHA `d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a`, `RuntimeDataUnchanged=true`, `TestExitCode=0`. UI log records API111452/frontend normal close and cleanup0. Those original runtime claims were inspected in the archive, not recomputed by reading private runtime files in this seat. The package/ledger reports 45 links/0 broken and diff-check0; no separate machine-readable link/diff artifact in the inspected evidence manifest establishes a new reviewer check, so those are author-reported checks.

All 18 current PNG entries were integrity-checked; **one** full evidence screenshot was visually inspected (`candidate-unchecked-complete-evidence.png`), not all 18. It shows blank submitted feedback background, pending candidate/original awaiting_review, old/new target, facts, complete 7-case report and unchecked semantic controls. The other screenshots were not visually judged. No real browser missing-corpus flow is claimed: that branch has native/HTTP and controlled React evidence only. No measured line/branch coverage percentage is available or inferred from test counts.

One permitted **pure in-memory nonmutating contract probe** was executed with Node/installed TypeScript: transpiled only the decoder and declared synthetic wire fixture in memory, then called `decodeCandidateDetail` on two altered plain objects. No test runner, app, DB, provider, browser or files were created. Actual outputs: `stale-review-retained: accepted=true, availability=stale, hasReview=true`; `ready-with-failed-report: accepted=true, availability=ready, reportStatus=failed`. This supports M1 only; the Important findings and M2 are source judgements with suggested, unexecuted regressions.

## Findings

### Critical — none

No Critical finding substantiated in the inspected TS15 paths. This is not an assertion that unexecuted/external paths are defect-free.

### I1 — Candidate review omits the original preceding conversation needed for context review

**Important; confidence 9/10.** Actual locations: [candidate_review.py:341](/D:/CODE/turtle-soup/backend/app/candidate_review.py:341), [candidate_review_contracts.py:25](/D:/CODE/turtle-soup/backend/app/candidate_review_contracts.py:25), [feedback_contract.py:28](/D:/CODE/turtle-soup/backend/app/feedback_contract.py:28), [AgentReviewPanel.tsx:259](/D:/CODE/turtle-soup/src/components/AgentReviewPanel.tsx:259).

Motivating code:

```python
material = CandidateReviewMaterial(sanitizedInput=context.sanitizedInput,
    programDiagnostic=context.programDiagnostic, draft=candidate.draft,
    factScope=context.factScope, highlightedFactIds=candidate.draft.factIds,
    oldTarget=old_target, report=report)
```

`SanitizedInput` contains only `question`, `hostAnswer`, `expectedClaim`, optional `reason`; `TaskContext` and `CandidateReviewMaterial` contain no preceding conversation field. The panel renders that input and then offers `不依赖玩家当前上下文`. `_freeze` validates the linked turn/result but never captures or reads its preceding messages. The normal host, in contrast, uses actual session history. A feedback reason is an optional player claim, not the actual original conversation; the inspected browser flow explicitly clears it.

**User effect:** the promised same-screen original question/context review is incomplete. A reviewer can confirm context independence without seeing the conversation that produced the feedback, especially when the manually sanitized question differs from the original turn. Original plan section 8.5 explicitly requires checking the original context; A54 requires original question/context in the review screen. Current static-scope checks and fixed regression help but do not supply that human evidence. I am not claiming that the existing synthetic replacement is semantically wrong or that all context-dependent drafts evade program guards.

**Minimal fix:** add a bounded, source-bound admin review projection of the actual pre-feedback-turn context/original question, with explicit privacy scope and unavailable handling. Keep it distinct from user-authored reason/model summary; do not automatically send additional raw session content to the model. If a reliable permitted projection cannot be supplied, expose that absence and withhold the affirmative context-review path for affected candidates. Bind the reviewed projection/digest so later messages cannot silently become the original context. This can use the existing turn/message and JSON metadata infrastructure; no invented SQL column or immutable migration change is requested.

**Suggested native reproducer (not run):** extend existing TaskContext/candidate detail fixtures with a completed earlier question/host pair before the feedback turn and a valid actual candidate/report; assert the detail contains exactly the source-bound preceding context and original question, excluding later turns/other sessions. Use the existing two-history context fixtures to confirm that player reason alone cannot stand in for that evidence. Add a panel assertion that the context/absence is displayed before the independence checkbox. Source presently has no field through which these assertions could pass.

### I2 — Corpus/code withdrawal after proof preparation is not fenced at mutation commit

**Important; confidence 8/10.** Actual locations: [candidate_review.py:489](/D:/CODE/turtle-soup/backend/app/candidate_review.py:489), [candidate_review.py:412](/D:/CODE/turtle-soup/backend/app/candidate_review.py:412), [candidate_review.py:349](/D:/CODE/turtle-soup/backend/app/candidate_review.py:349), [agents/store.py:188](/D:/CODE/turtle-soup/backend/app/agents/store.py:188).

Motivating code:

```python
detail = self._detail(conn, candidate_id)
if action == "approved" and (detail.availability != "ready"
    or detail.proofDigest != request.expectedProofDigest):
    raise CandidateReviewError("candidate_proof_stale", 409)
```

After that single validation, approve writes its state/receipt/audit; publish similarly validates at 412–416, then publishes and writes its candidate ledger. The shared final transaction fence is:

```python
with self.runtime.lock:
    if self.runtime.closed:
        raise AgentError("agent_unavailable", 503)
    if write:
        self._check_execution()
    conn.commit()
```

`_check_execution` is an Agent execution-scope cancellation/lease check, not a candidate corpus/code freshness check. `Runtime.repair_corpus` remains replaceable; existing withdrawal tests assign it `None`. Registered file bytes are checked while constructing `FixedRegression` in `_detail`, with no equivalent final recheck. SQLite's writer lock serializes feedback/base/row withdrawal but cannot serialize a runtime corpus assignment or a registered source-file change.

**User effect:** withdraw/replace the corpus, or change registered code, after `_detail` returned ready but before commit: an approval can still be saved as fresh, and an already approved candidate can still create an effective release/pointer transition. Later reads becoming unavailable/historical do not undo that publication. Existing tests cover changes before detail and serialized DB withdrawals, not this interval. This is a Focus 3 freshness race; it does not imply partial SQL transactions or model publication authority.

**Minimal fix:** fence fresh approve/publish against the same corpus/code identity at the final commit boundary, or make the trusted runtime identity immutable for an admitted mutation and serialize its withdrawal with that admission/commit. A final check should roll back all SQL work on detected change, including a release already inserted; preserve historical replay and stale rejection paths. Source edits also require a defined close/drain or equivalent source-identity fence, rather than assuming the DB lock protects files. Do not add a second transaction or re-sign the old immutable report.

**Suggested native reproducer (not run):** reuse the existing actual candidate/publication and audit hook fixtures. After the real approval or candidate-publication audit insertion, set the owned runtime corpus to `None` (and in a separate case substitute the existing synthetic changed-byte `Path.read_bytes` hook), then allow return/commit. Assert refusal and the whole DB snapshot unchanged, including release/pointer/receipts/audits. The source currently checks only runtime closure at that point. Retain existing exact-replay-after-withdrawal tests to ensure the new fence is not applied to an historical acknowledgement.

### M1 — Private detail decoder accepts incompatible availability/report projections

**Minor; confidence 10/10 (pure probe confirmed).** Actual locations: [agent-review-contract.ts:153](/D:/CODE/turtle-soup/src/lib/agent-review-contract.ts:153), [AgentReviewPanel.tsx:276](/D:/CODE/turtle-soup/src/components/AgentReviewPanel.tsx:276), [AgentReviewPanel.tsx:281](/D:/CODE/turtle-soup/src/components/AgentReviewPanel.tsx:281).

Motivating checks only require:

```typescript
['ready', 'historical'].includes(result.availability) !== (material !== null)
// review binding is checked when present; material/report.status is not
// required to be complete for an actionable ready projection.
```

The panel independently renders `detail.review && ...` and permits ready pending approval. The two probe objects are accepted: stale/approved with material/proof null but review retained; ready/pending with a coherently failed counterexample report. The backend currently suppresses stale review and refuses non-complete report proof, so this is not a demonstrated server authority bypass.

**User effect:** a malformed/regressed response can display review material where the UI claims source withdrawal, or offer semantic approval controls while displaying failed mechanical evidence. This falls short of the planned fail-closed literal frontend contract.

**Minimal fix:** reject non-null review for stale/unavailable detail and require complete report evidence for material accepted as ready/actionable. Preserve legitimate historical reads and minimal rejection states.

**Suggested native reproducer:** add two literal decoder cases using the existing synthetic fixture, exactly as the pure probe above, expecting `AgentReviewContractError`; optionally assert no withheld review/approval button in the panel. No new service or provider fixture is needed.

### M2 — A hidden-tab polling tick permanently stops automatic task observation

**Minor; confidence 9/10 (source judgement).** Actual location: [AgentReviewPanel.tsx:105](/D:/CODE/turtle-soup/src/components/AgentReviewPanel.tsx:105).

Motivating code:

```typescript
const timer = setTimeout(() => {
  if (document.visibilityState === 'visible') void loadStatus(status.id);
}, 3000);
// effect dependencies: [status, pollStopped, busy]
```

If the tab is hidden when this timer fires, there is no request, state change, next timer or visibility-change listener. Returning to the tab leaves the same active status and dependencies, so polling never resumes. Manual task-status navigation still works.

**User effect:** an ordinary tab switch can leave the visible task apparently queued/running indefinitely after it actually finishes, without a polling-stop explanation. No approval or budget safety boundary is bypassed.

**Minimal fix:** restart bounded observation when the tab becomes visible, while retaining one request at a time, at least 3-second scheduling, epoch/Abort fences and terminal/401/429/unmount stops.

**Suggested native reproducer (not run):** a component fake-timer test: load active status, hide the document before the 3-second tick, restore visibility and dispatch `visibilitychange`; verify a bounded subsequent status request occurs and terminal response stops further polling. Also retain the late pre-cancel poll control.

## Declined to judge — each item for individual main ruling

These are considered/set-aside behaviours, not silently omitted findings. Validated in-scope behaviour without a defect is described above, rather than being labelled declined.

- D1: Multi-catalog corpus discovery/routing and automatic repair for every soup — explicitly outside the approved one-catalog pilot; did judge wrong/missing/altered corpus handling in the current paths.
- D2: Reopening TS13's pure preview design versus literally constructing a temporary release object — accepted predecessor architecture; inspected its actual candidate/unrelated/context regression integration, but no new second TS13 design review was performed.
- D3: A privileged attacker replacing the entire SQL history and bypassing immutable triggers, or cryptographic attestation against hostile Python/operator code — outside this trusted-server/store threat model; partial foreign/mismatched/corrupt proofs and missing approval operations were judged.
- D4: Automatic PII filtering of freely authored admin review notes — the approved contract explicitly treats notes as private operator text and warns against identities/keys; did judge raw-source/model/lease leakage and bounded serialization.
- D5: Per-person reviewer identity/account roles behind the single independent admin credential — no individual account/identity system is in this stage; actual explicit confirmation, note and operation provenance were judged.
- D6: Adding a worker-disabled standalone Agent status/cancel API — existing TS14 routes intentionally require a worker; TS15 detail and index expose original outcome without model allocation, and this documented distinction was judged.
- D7: Asymptotic large-volume task-index latency/index migration — the relevant ledger ruling explicitly accepts a bounded join without claiming an indexed time-order scan; examined actual schema and no N+1, but TS16 measurement/new-index work is outside this seat.
- D8: Full live browser missing-corpus and exhaustive visual/mobile QA of all new candidate states — no archived real browser missing-corpus flow and only one screenshot visually inspected; source/native/HTTP/React branches were judged, live execution is prohibited here.
- D9: Unrelated dirty legacy modules/deploy scripts or re-auditing accepted TS01–14 issues — preserved user changes and reviewed transitive TS15 effects only; no scope expansion into TS17/18 or dependency installation/audit.

## External HOLD (separate from local defects)

Real independent human labels/semantic review quality and correcting old real corpus labels; genuine free-provider eligibility and real-model trajectories/quality; production 003 migration, release/rollback and backup recovery; remote CI and other OS/runtime matrices remain HOLD. The seven real-model and three platform skips are not passes. Synthetic humanConfirmed/semantic checkbox steps do not close A54's genuine human subset, A50/A53 or provider/production acceptance. No accuracy, user count, provider success rate, human-review success rate or quality score is fabricated here.

## Local readiness assessment

**With fixes; not ready for unconditional TS15 local engineering closure.** The central proof/replay/atomic publication/rollback work is substantial and the current archived mechanical gates are coherent. I1 leaves the promised human context-review screen incomplete; I2 leaves a fresh-authority race for non-DB withdrawal. Main should individually rule both Important findings, both Minor findings and all nine Declined items, then use the authorized ONE native C–I RED→GREEN fix/current gates and close this same seat. This report requests no additional reviewer, run, launch, agent or external acceptance.
