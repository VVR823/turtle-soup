# TS14 review rulings — LOCAL engineering closure

Sole reviewer Poincare 01a12495-2c42-7d12-8e4a-0b4f5109c166 completed the existing review after quota recovery. Full original report is [ts14-review-report.md](ts14-review-report.md). One Critical, four Important, one Minor; only C1 was reproduced by the reviewer. Main must produce independent boundary tests before claiming I1–I4 fixed. One native C/I pass, no second reviewer. Prior 2408 offline/29 UI evidence is pre-review, not final acceptance.

## Findings

| ID | Main ruling | Status / required evidence |
| --- | --- | --- |
| C1 | Critical: actual repair prompt objects are not JSON wire payloads; configured adapter path is broken | Native actual-prompt + CompatibleAdapter/MockTransport RED then minimal trusted-boundary conversion, host compatibility control; pending |
| I1 | Important: admission before SQLite lock is not an authoritative closing fence | Owned writer-lock interleaving plus commit/closure synchronization and dedicated terminal-only positive control; pending |
| I2 | Important: heartbeat-loss Event alone does not fence tool/candidate result authority | Actual blocked computation, live lease, heartbeat failure then release; retain spent/planned intent and terminal-only stopping; pending |
| I3 | Important: permanently stale queued records retain capacity and never hand off | Native worker/CAS revocation/version-change and concurrent cancel/claim controls, no new lease/deadline/attempt; pending |
| I4 | Important: live source guard is missing before the real dispatch boundary | Block adapter construction after reservation, withdraw source, release; zero invoke, spent intent, safe handoff; pending |
| M1 | Minor: agent HTTP attempts lose closed route classification, business audit persists | Retain as TS17 audit-observability backlog; not a second TS14 product fix or claim of total audit loss. Cover successful and pre-routing rejected requests when implemented |

## Every Declined item individually ruled

| ID | Main ruling and next action |
| --- | --- |
| D1 | External HOLD: provider/account eligibility and actual zero-cost policy not inspected; no paid probes or inferred entitlement |
| D2 | External HOLD: A50 real trajectory not collected; C1 mock evidence proves only local adapter integration |
| D3 | External HOLD: A53 eight human conclusions not collected; eight synthetic reports cannot substitute |
| D4 | External HOLD: actual private corpus contents/independence not inspected or invented |
| D5 | LOCAL NOT DONE: application corpus wiring is engineering work, not proof of corpus availability. Deliver trusted explicit shared corpus injection with native TS15 workflow tests; missing real corpus stays HOLD, no automatic discovery or synthetic production proof |
| D6 | External HOLD: production migration/recovery needs separate production authority and real evidence; immutable migrations preserved |
| D7 | External HOLD: default-off/local work is not production activation or operational acceptance |
| D8 | Outside current autonomous scope: no shipping, PR, push, upload or public publication |
| D9 | Next approved stage TS15: implement private human review/publication UI and guards after actual TS14 local closure |
| D10 | Human boundary: format and mechanical tests do not prove semantic truth; pending candidates never automatically gain approval |
| D11 | Outside model-JSON threat model: trusted Python/OS compromise not claimed sandboxed; closed tool/server authority still enforced |
| D12 | Production performance HOLD: no throughput/SLA claim from bounded local admission; local fault/priority regressions remain required |
| D13 | Unverified platform subset: record ten skips and Windows/Edge-only evidence honestly; no invented OS/browser matrix |
| D14 | Reviewer did not rehash private assets: main must execute byte-only original239 preservation gate, never expose contents |
| D15 | Historical TS01–13 acceptance not reopened; existing Minor backlog preserved; dependency integration failures may still belong to TS14 |
| D16 | LOCAL pending native evidence: main will execute I1–I4 event/lock reproductions in the one C/I pass. M1 remains backlog, not falsely called tested |
| D17 | LOCAL pending final gates: reviewer inspected frozen maintainer reports only. Main must run fresh selected/full/UI/build/static/data gates after fixes, not reuse pre-review success |

## Native one-pass evidence (current, not final whole-stage gates)

- C1: review-c1-red.xml actual one failure, configured adapter produced model_unavailable before dispatch. Trusted compatible HTTP boundary now converts typed system/human messages, leaving original host dictionaries and injected typed messages unchanged. review-c1-green.xml actual56 passed.
- I1: review-i1-red.xml actual TWO DIDNOTRAISE failures at owned SQLite writer wait and after actual mutation/before commit. Recheck closure after BEGIN and serialize final check/commit with Runtime.lock; no lock held across BEGIN/computation, terminal-only transaction unchanged. review-i1-green.xml actual151 passed/2 platform skips.
- I2: review-i2-red.xml actual blocked-tool result incorrectly completed after failed heartbeat while lease still valid. Server-only ContextVar scope binds owned run/token/cancellation, guards work and ordinary write/commit, heartbeat revocation uses the same final-commit lock. First adjacent run88 passed/one real regression: original deadline was misclassified model_unavailable; current safe reason recheck fixed this within the same pass. review-i2-current.xml actual89 passed. Additional candidate and finish cancellation-before-commit controls are synthetic persistence checks, not corpus/human approval proof.
- I4: review-i4-red.xml actual revoke case emitted an HTTP mock request after withdrawal; successful heartbeat control passed. Existing gateway before_attempt now rechecks the original guarded identity and exact planned reservation, not another budget reservation. review-i4-green.xml actual82 passed, retained spent attempt and zero dispatch on revocation.
- I3: review-i3-red.xml actual TWO failure paths: ten stale queued tasks remained unhandled after revoke or source version change. Server-only queued CAS handoff rechecks permanent staleness without restoring permission, starts no lease/deadline/attempt, preserves terminal audit atomicity; worker only routes stable stale-context refusals here. review-i3-green.xml actual123 passed.
- review-controls-current.xml actual14 passed: the seven genuine boundary failures above plus seven positive/regression controls. First extra-controls run13 passed/one fixture constructor error (missing FinishAction.action); corrected fixture, NOT counted as a product defect. Added controls cover candidate/finish rollback, fresh/claimed/cancelled queued authority and audit-failure rollback/retry. No new provider or human evidence.

Finding rows marked pending above describe the required tests at receipt time; all C/I native fixes now have current boundary evidence and the fresh final gates below. M1 and each external HOLD remain unchanged.

## Final local gates and closure

Actual review-final-selected338 passed; review-final-full2173 backend cases/2163 passed/10 skipped, exactEval412 without failures/errors/skips; frontend231/Node25/API3 =>2422 offline passes/10 skips. API114884 normal shutdown. Actual review-final-ui29 Edge passes/0 skip, isolated build exit0, API96892 and owned frontend normal shutdown/cleanup0. Lint/typecheck both exit0; current documentation commands79 passed. Seven pages96 local links checked, including four intentional directory links; the first file-only checker falsely rejected those directories and was corrected, not a broken-doc fix. Original239 files after UI retain full SHA d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a. HEAD/index unchanged, no Git/production/provider actions.

Sole reviewer close_agent returned previous_status completed after all findings/17Declined rulings, one C/I pass and fresh gates. TS14 LOCAL engineering acceptance closed with M1 deferred to TS17; no real-provider, human-reference, actual corpus/wiring or production acceptance. TS15 design remains implementation-pending; application corpus wiring is explicitly a LOCAL TS15 obligation, not covered by this closure. Preserve original review-time manifests unchanged; post-fix evidence uses new filenames and does not pretend the reviewer inspected the later fix snapshot.
