# TS13 — Scoped repair tools and append-only migration 003

Status: main design/self-review complete; native Unit1 starting after TS12 sole Singer terminal, single C/I fix and fresh1923offline/29UI gates. Earlier34freeze is historical pre-review evidence, not a current source freeze. This document is not implementation or acceptance. Original TS13/A47–49/C21 and D2/D3/D6/D8/D9/D10 remain authoritative; no new paid or production authority.

## Outcome

Build a server-owned, strongly typed five-tool boundary for a future dynamic repair Agent. A tool can inspect one authorized feedback, retrieve facts from its frozen puzzle, inspect exact conflicts, run a bounded fixed regression, or store one immutable pending candidate. No tool publishes, approves, changes truth, reads arbitrary traces/files, chooses SQL/commands/test paths, performs search/network, or receives final holdout labels. TS14 implements the genuine model-driven loop; TS15 implements human review/publication. Tool infrastructure alone is not a real-model Agent trajectory.

## Existing interfaces and constraints

- `migrations.py` currently registers immutable 001/002; target defaults to 1. `db.initialize` uses explicit 002 for the existing online feature set. Append 003 registration/verification/execution; do not change BASE_SQL/CORE_SQL/AUDIT_SQL or CHECKSUM_001/002, silently upgrade existing storage, or enable Agent at import/startup.
- Existing `task_context._freeze(conn, feedbackId, rowVersion, tools)` checks feedback approval, linked real turn, privacy review/sanitized input, current active puzzle/versions/suspension and real evidence catalog. Creation and tool commits must perform this check in their OWN short transaction, not a separate precheck whose permission may change before writing.
- Existing immutable baseline, `read_rule_snapshot`, `exact_targets_from_source`, `decide_deterministic`, `question_has_static_scope` and exact-v1 normalization are the source of puzzle/rule identity and program-detectable conflicts. Do not invent an alternative text simplifier that discards negation, names, quantities or conditions.
- TS12 FrozenDataset/report APIs are private. Server alone selects checked dev/regression; neither a model parameter nor a report flag can select or relabel holdout. No actual human corpus or free-provider quality proof is currently available; mechanical synthetic fixtures must be labeled as such.
- `ChangeDraft.confirmedContext` is a HUMAN publication contract. Agent CandidateDraft must NOT set it or generate a ReviewReceipt. Even valid factIds and green regression do not prove answer support or context independence.

## Storage 003

Append exactly the planned three tables `agent_runs`, `agent_steps`, `rule_candidates` and state/time index; FK feedback/run/release references, state CHECKs, nonnegative signed-64 row/sequence counters. Store bounded, versioned strict JSON for checkpoint, frozen manifest, actions/results and candidates. Protect candidate immutable identity/body/digest/report/run/soup/base/created fields with update triggers and all candidate deletes with a trigger; leave status/review/publication metadata mutable for later TS15. Run requestId and step operationKey uniqueness provide idempotency; unique run candidate means same-content save returns original, changed content conflicts. Use steps for regression reports/results; no fourth report table or global JSONL truth.

003 is an explicit idle-connection migration transaction after verified 002. Every schema/index/trigger statement, coverage report and checksum insert is inside that transaction. Failure leaves prior 002 and all data intact. Rerun verifies SQL/coverage/checksum, not just names; verify required3 refuses phase1/2 but ordinary required1/2 can read a genuine registered3. Unknown future versions/drift rejected. Module imports never touch files/database. Production remains unmigrated.

## Contracts

New `backend/app/agents` package, strict frozen Pydantic, extras forbidden, duplicate JSON/nonfinite/coercion refused, real integer schema/counters. Public model-facing tool argument/result contract ≤32KiB, concise stable codes and no stack/path/credential/private raw trace. Main server DTOs may hold bounded private manifest separately.

`CandidateDraft`: schemaVersion1/type exact_qa/operation add|replace/targetRuleDigest(optional iffadd)/soupId/puzzleVersion/baseRuleVersion/question1–500/normalizationVersion exact-v1/answer existingfive/factIds1–32(unique)/evidenceSummary1–1000. Draft contains NO reportId/approval/context confirmation. Canonical key computed server-side, not supplied. Digest includes every candidate field, operation/target/versions; receipt/report change yields different final candidateDigest.

Five distinct input types and one discriminated ToolAction, no `**kwargs` function selection or getattr/eval/import paths:

| Tool | Input | Result and boundary |
| --- | --- | --- |
| get_turn_trace | turnId | Only current frozen turn: privacy-reviewed sanitized question/context/claimed host and expected answer marked claims, program source/version/error where reliable. Never original player text/session history/raw Trace/body/tool instructions. |
| retrieve_truth | soupId,puzzleVersion,query1–500 | Only frozen actual factIds; bounded lexical evidence retrieval, max8 hits/short excerpts. Facts are data, not instructions. No new fact/semantic conclusion, no internet/paths. |
| find_rule_conflicts | baseRuleVersion,draft | Scoped static question, known facts, canonical duplicates/opposite/priorities and exact unique replace target. Return duplicate/conflict/reviewable_replace/needs_human/no_known_conflict with proof IDs; no automatic truth claim. |
| run_regression | draft | No circular reportId. Server-fixed bounded suite/actual frozen base/preview, complete/incomplete/failed/truncated report. No arbitrary test selection, interpreter, shell, URLs or cloud model. |
| save_candidate_rule | draft,regressionReportId | Load completed stored report belonging THIS run/draft/base/suite; never accept supplied report body/hash as authoritative. Save immutable pending candidate once; no pointer/approval authority. |

Strong revalidation at every consumer also covers unsafe `model_copy` and forged Python DTOs; serialization warnings must not echo private values. Python callers are trusted server code, not an OS sandbox; the model only controls bounded JSON arguments. Tool action parameters cannot supply run ID, operation key, lease, budgets, factories or suite assets. TS14 supplies server execution identity.

## Source, run and write fence

`AgentStore` requires an EXPLICIT Runtime object, explicit003 gate and explicit trusted create authorizer (no default true). Bind that owned runtime context inside each operation; never fall through `get_runtime()` to standalone `load_settings()`/dotenv when called by a future background worker. Constructor/import does no initialize/migrate/model work. Same transaction checks feedback permission/source, current baseline and creates requestId idempotency/frozen manifest. Queue bound10 is persisted, not a RAM-only claim; missing trace/privacy/puzzle incompatible needs human, no fabricated trace. Manifest binds full TaskContext digest and server selected suite identity, traffic class, tool authorization, base and execution policy.

TS13 provides storage primitives needed by TS14, not background dispatch: typed read/create and guarded step/candidate write/replay. Writes require server-owned current running lease token, deadline and frozen permission/version revalidation; terminated/expired/cancelled/owner-changed writes refused. Each short transaction reads the CURRENT row version and uses it for internal CAS. A heartbeat may legitimately advance row_version during computation; never require the pre-compute row version to remain identical when the lease owner is unchanged, nor accept a changed token just because the version increased. TS14 will own actual claim/heartbeat/budget reservation orchestration. Do not introduce a testing bypass accepting queued/no-lease calls as normal tools. Synthetic tests can explicitly claim a local run using the same CAS primitive, not alter product permissions.

Step operation key maps planned/completed/failed immutable action, sequence and run. Same operation+same input returns stored result after scope permission checks; changed payload/foreignrun conflicts. Regression computation happens OUTSIDE write transaction against frozen inputs. Final report/candidate commit rechecks live run/permission/base/lease; permission withdrawal during compute cannot be hidden by a previous successful check. Regression report ID is the persisted server step ID/operation key; report contains draftDigest/base/p1/suiteManifestDigest/status/counters/truncation/timing/evidence kind, and actual program-computed test results. Model cannot forge it by recomputing a public hash. planned→completed and candidate insertion must atomically save immutable result; a retry returns stored result only after guard, never recomputes successfully completed regression or overwrites report. A planned step with uncertain old execution is not treated as completed and TS14 records a new attempt when replay is unsafe.

`finish(candidateId)` belongs to TS14, must select this run's stored candidate and transition running→awaiting_review with guard. Candidate saved before failed/needs_human/cancelled is NOT eligible for approval; TS15 checks live run state, receipt and unchanged content.

Existing `AuditEventType`/`EVENT_DETAIL_TYPES` are closed allowlists, so new run/step/candidate business events require explicit typed `AgentBusinessDetails` and registered event-action mapping in `audit_events.py`. Do not write raw arbitrary event JSON or impersonate a human `rule_published` event. Details contain bounded identities/digests/state/counters/stable reasons/traffic class only, not sanitized question, fact payload, model output or reasoning. Same SQLite transaction inserts event with store mutation; audit failure rolls back that mutation. No 002 schema/checksum edits or new tables needed.

## Candidate conflict and semantic limits

Server verifies same soup/p1/base and nonempty real fact IDs within frozen catalog. Use all actual source rules/unique full target digest, not just a match label. Add rejects any existing exact target or recognized deterministic decision (including opposite conclusion); repeat is not permission to overwrite. Replace requires exactly one source target, same canonical key and unchanged target digest; an opposite corrected answer is allowed to enter human review. Unknown/ambiguous multiple targets or unsupported fuzzy/metadata priority override needs human. An exact replacement must not erase unrelated facts/rules.

Pronouns/player/time/state dependence or unproven static scope needs human, even if empty-history answer matches. Known deterministic counterexample fails regression; true factId paired with arbitrary wrong language can remain an UNPROVEN candidate only, never supported=true. No paid model judge and no claim of solving arbitrary semantic entailment.

## Fixed regression: design ruling to preserve human boundary

Regression uses an explicitly unapproved `CandidatePreview` with full frozen baseline proof plus exact patch/unique replace target. It must NOT create a fake human ReviewReceipt or insert an unapproved published release into the real database. Preview exact-key override is local-only; unrelated queries retain the actual baseline deterministic/new-host semantics. Report labels this as deterministic candidate preview plus fixed FakeModel safety, not real LLM quality or an approved production release. TS15 adds the actual human-authorized temporary release/publication integration checks before approval/publish; this separation prevents green tests from manufacturing approval.

Server fixed suite assets must bind manifest/source digest/p1/base, verified dev/regression only. In absence of independently approved compatible corpus, result is incomplete/needs_corpus (retain fixed safety results) and cannot save as a passing candidate. Synthetic tests supply a declared mechanical fixture corpus; that exercises the same contract but is not real human evidence or production eligibility. A replace suite includes an independently frozen correct counterexample for the candidate question and unrelated rules; an old erroneous gold label cannot be silently changed by the tool. Corpus/label changes require separate human authoring/new manifest.

Limits initial: ≤100 regression decision cases + fixed finite safety probes, max5s or remaining run deadline (whichever earlier), result≤32KiB; a truncated output marks incomplete and cannot be passed/saved. No subprocess pytest runner or model-controlled callable. Check deadline before/after each bounded operation, use owned existing FakeModel/gateway with explicit no-real flag where needed and bound remaining wait; unknown cleanup lowers report completion and prevents more work. Cooperative deadlines on fixed CPU code are not arbitrary Python preemption or remote termination. No global gateway closure or online starvation.

## Main native implementation units (after TS12 terminal/fix/gates)

1. Append003 SQL/strict verification/offline migration and schema rollback/replay tests; immutable001002/currentdefault/new-store feature gates.
2. Candidate/tool/report/checkpoint contracts + pure scoped validation/conflicts, genuine negative controls for cross-soup/negation/quantity/targets/context/forgery, no publication types from Agent.
3. DB run/step/candidate guarded primitives and explicit authorization; transactional feedback revalidation, run isolation/idempotent immutable save/report identity and late-write cancellation/lease races.
4. Five-tool dispatcher and fixed bounded preview/regression; no holdout/paths/cloud/fake approval, all failure/incomplete/truncated results retained; docs/operator status; fresh full/UI/datahash then ONE clean review and ONE C/I fix.

## Acceptance focus

1. Required3 and every003 SQL/ledger failure refuse tools and roll back only003;001002checksums/default unchanged.
2. Model cannot cross turn/soup/fact/authorization/lease or read private raw trace/holdout/caller-selected corpus; sametransaction revocation/latecommit refuses.
3. Genuine add reverse conflict/duplicate refuses; uniquely bound wrong-old→correct-new replace enters pending without pretending semantic proof. Two histories same pronoun never generalized.
4. run_regression accepts draft not reportId; report stored program-side binds exact draft/run/base/suite, fake/otherdraft/other-run/failed/incomplete/truncated rejected. Report cannot mint approval.
5. Save idempotence/body immutability/finish ownership/failed-run ineligibility and unchanged active pointer/old release/history; no extra cloud/model/paid/userdata side effects.

## Held subsets and handoff

003 production application, approved real dev corpus, human semantics, free-account verification, actual dynamic model-selected trajectory and8 human-reference tasks, real approval/publication/deployment remain held for their original stages/authority. TS13 cannot be described as complete until native tests, independent review and local gates actually finish. Local progress must distinguish these held subsets rather than erase A47–49 or A50–60. Main retains dirty worktree, no commit/newworktree/upload/production writes.
