## TS14 review report

**Findings: 1 Critical, 4 Important, 1 Minor.** C1 was reproduced with an in-memory HTTP mock. I1–I4 are source-backed failure paths; I did not execute new database race tests.

This was one read-only review. No source edits, Git writes, installs, additional reviewers, network/provider calls, production access, or original/private corpus reads were performed.

### Snapshot and evidence

The final read-only checks matched the supplied identity:

- Branch: `codex/ts02-storage-foundation`
- HEAD: `c5765b68cb251a7c566e76e2887d335d6ed6b285`
- Index SHA256: `45C635EFDD2844F5A8DAC3CF3B6B7FBB4CAA6A54A2F247F3F8CC902C4CA275F5`
- Source manifest SHA256: `E0F67FE5C05686BF9C3A8465396EFD71D8A7DC0A8FA18C7DC2EA780869A6A781`
- Evidence manifest SHA256: `DFF0595F73E75BE98936F27CEB3B2143C2D8B90B79842AA5E468036CD756A487`
- All **98 source entries and 11 evidence entries matched their actual current hashes**.

I parsed the current reports and inspected their logs; I did **not** rerun these gates:

| Current evidence | Observed result |
|---|---|
| `unit4-final-selected.xml` | 313 passed |
| `unit4-final-full.xml` | 2159 backend cases: 2149 passed, 10 skipped, zero failures/errors |
| Exact `backend.eval.tests.*` classnames | 412 cases, zero failures/errors/skips |
| Full-run frontend / Node / API logs | 231 / 25 / 3 passed; total 2408 offline passes |
| `unit4-final-ui.xml` | 29 passed, zero failures/errors/skips |
| UI log | Isolated build exit 0; normal API/frontend shutdown and cleanup 0 |
| Lint / typecheck logs | Recorded clean eslint / `tsc --noEmit` runs |
| `docs-examples-current.xml` | 65 passed |
| `doc-links.csv` | 40 links across five documents; zero broken |
| `task-report-current.xml` | 43 passed; eight actual `agent_task_report` properties |
| Synthetic report JSON | All eight reports exactly matched the corresponding JUnit properties |

The logs record normal shutdown of API processes **110668** and **114228**. Original-data preservation is supported by the supplied/current evidence logs, not by a reviewer read or rehash of private original data.

`git diff --check` returned exit 0 with existing LF/CRLF warnings. This does not establish whitespace coverage for untracked files.

## Findings

### C1 — Repair prompts cannot reach the configured compatible adapter

**Grade: Critical. Confidence: 10/10. Reproduced locally.**

[agent_prompt.py:129](D:/CODE/turtle-soup/backend/app/agents/agent_prompt.py:129):

> `messages=(SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=raw))`

[repair_agent.py:101](D:/CODE/turtle-soup/backend/app/agents/repair_agent.py:101):

> `selected = self.gateway.invoke(prompt.messages,`

[model_gateway.py:347](D:/CODE/turtle-soup/backend/app/model_gateway.py:347):

> `json={"model": self.model, "messages": messages, ...}`

The repair prompt supplies LangChain message objects. `CompatibleAdapter` puts those objects directly into HTTPX’s JSON body without converting them to wire dictionaries. They are not JSON-serializable. The gateway then converts that exception to `model_unavailable`, rather than obtaining a model-selected action.

The existing online host supplies the compatible representation:

[ai_host.py:782](D:/CODE/turtle-soup/backend/app/ai_host.py:782):

> `{"role": "system", "content": context.system}, {"role": "user", "content": context.user},`

**Observed diagnostic:** using the existing interpreter, real `ModelGateway` and `CompatibleAdapter`, and an in-memory `httpx.MockTransport`:

```text
repair_prompt_types error=model_unavailable mock_requests=0
repair_prompt_types active=0 cleanup_failed=0
host_wire_control action=finish mock_requests=1
host_wire_control active=0 cleanup_failed=0
```

No real HTTP request was made. The only changed variable was the message representation.

**Impact:** the configured compatible-provider path cannot execute even its first repair decision. Scripted/injected transports conceal this integration defect. It is LOCAL, not an explanation for the external real-provider HOLD.

**Minimal fix:** normalize the supported message representation at a trusted adapter boundary, preserving the host contract and existing injected-adapter behavior.

**Suggested test:** send the actual output of `build_decision_messages` through the actual `CompatibleAdapter` with `MockTransport`; assert one mock request and one valid selected action. Keep a host-wire positive control. Current [test_agent_conditional_loop.py:27](D:/CODE/turtle-soup/backend/tests/test_agent_conditional_loop.py:27) reads `messages[1].content`, demonstrating why that fake does not exercise compatible JSON serialization.

### I1 — Ordinary writes can pass the closing gate before blocking on SQLite

**Grade: Important. Confidence: 9/10. Source-backed; exact interleaving unexecuted.**

[store.py:136](D:/CODE/turtle-soup/backend/app/agents/store.py:136):

> `if self.runtime.closed:`

[store.py:147](D:/CODE/turtle-soup/backend/app/agents/store.py:147):

> `conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")`

[store.py:150](D:/CODE/turtle-soup/backend/app/agents/store.py:150):

> `conn.commit()`

The closed check precedes acquiring the SQLite transaction, whose connection permits a ten-second lock wait. There is no closing recheck after `BEGIN`, and `_guard` does not test runtime closure.

Meanwhile [runtime.py:60](D:/CODE/turtle-soup/backend/app/runtime.py:60) sets:

> `self.closed = True`

**Failure path:** an ordinary decision/tool/candidate completion enters `_transaction` while open, blocks on another SQLite writer, and resumes after shutdown marks the runtime closed. If the run’s token, source and deadline remain valid, its ordinary mutation can commit after closure.

The dedicated terminal transaction is correctly separated at [store.py:249](D:/CODE/turtle-soup/backend/app/agents/store.py:249), but this earlier admission race lets ordinary writes bypass the intended distinction without calling that exception path.

**Impact:** closure is not a reliable fence against late results or candidate writes.

**Minimal fix:** revalidate closure after transaction acquisition and synchronize ordinary write/commit admission with runtime closing. Preserve the narrowly scoped terminal-only exception; do not add a general `allow_closed` escape hatch.

**Suggested test:** hold an owned SQLite write lock, start ordinary completion while the runtime is open, close the runtime, then release the lock. Assert no ordinary result/candidate mutation and allow only the prescribed terminal stop. Existing [test_agent_stop.py:76](D:/CODE/turtle-soup/backend/tests/test_agent_stop.py:76) closes before starting the tested operations, so it does not cover this window.

### I2 — Heartbeat failure cancels the loop but does not fence in-progress tool writes

**Grade: Important. Confidence: 9/10. Source-backed; tool/heartbeat interleaving unexecuted.**

[worker.py:93](D:/CODE/turtle-soup/backend/app/agents/worker.py:93):

> `cancelled.set()`

[tools.py:66](D:/CODE/turtle-soup/backend/app/agents/tools.py:66):

> `self.store.complete_tool(identity, result)`

[store.py:407](D:/CODE/turtle-soup/backend/app/agents/store.py:407):

> `if (run.state != "running" or run.leaseToken != identity.leaseToken ...):`

Heartbeat failure sets cancellation and stops renewal, but does not revoke the still-valid write authority. Tool execution and store completion do not observe that cancellation event.

**Failure path:** a tool is computing outside its transaction; heartbeat fails before lease expiry; cancellation is set; computation returns while source, token and deadline are still valid. `complete_tool` can persist success. Candidate/result writes have the same missing heartbeat-loss fence.

The loop notices cancellation on its next iteration, after this write.

**Impact:** A52/D8’s failed-heartbeat rule—stop further work and deny old result writes—is not enforced for non-model work.

**Minimal fix:** make heartbeat-loss cancellation an irrevocable server-owned authority fence observed at work and commit boundaries, including candidate/finish writes. Retain terminal stopping and spent budgets; do not create a second resource owner or refund attempts.

**Suggested test:** block an actual tool computation, force heartbeat failure while the lease is still valid, observe cancellation, then release computation. Assert the reserved tool remains planned, no candidate appears, and only terminal stopping is permitted.

Current [test_agent_shutdown.py:41](D:/CODE/turtle-soup/backend/tests/test_agent_shutdown.py:41) covers heartbeat failure during a blocked model call. [test_agent_loop_races.py:102](D:/CODE/turtle-soup/backend/tests/test_agent_loop_races.py:102) covers blocked tools under heartbeat success, cancellation, revocation, takeover and shutdown—not heartbeat failure.

### I3 — Permanently stale queued runs never receive their required terminal handoff

**Grade: Important. Confidence: 9/10. Source-backed; queued-revocation worker test unexecuted.**

[worker.py:116](D:/CODE/turtle-soup/backend/app/agents/worker.py:116):

> `run = self.store.claim(pending.id, expected_row_version=pending.rowVersion)`

[worker.py:118](D:/CODE/turtle-soup/backend/app/agents/worker.py:118):

> `except AgentError as error:`

The exception branch only records `_last_error`.

[store.py:178](D:/CODE/turtle-soup/backend/app/agents/store.py:178):

> `current = _freeze(conn, frozen.feedbackId, frozen.sourceFeedbackVersion, frozen.allowedTools)`

That operation rejects revoked or changed source context before claim. The queued run has no lease, so the existing running-owner `stop` method cannot terminalize it.

**Failure path:** an admin starts a valid task while online work delays claim; permission or source version changes before claim. Every poll rejects the same task, leaving it queued indefinitely with no deadline and no terminal reason.

[store.py:216](D:/CODE/turtle-soup/backend/app/agents/store.py:216):

> `SELECT count(*) FROM agent_runs WHERE state='queued'`

Ten such tasks permanently fill the durable queue until an administrator manually cancels them.

**Impact:** automatic source-change handoff is incomplete; stale tasks retain queue capacity and can reject subsequent valid starts.

**Minimal fix:** add a narrow server-owned CAS transition for permanently stale queued context. It must use the stored record without reauthorizing source access, assigning a lease, starting a deadline, or consuming attempts. Keep transient storage failures retryable.

**Suggested test:** queue while online work is busy, revoke permission or change the bound source, release online work, and run the worker. Assert `needs_human` with a stable reason, zero attempts and an unstarted deadline; a following valid task must still proceed. Include a concurrent cancel/claim CAS control.

Current [test_agent_http.py:122](D:/CODE/turtle-soup/backend/tests/test_agent_http.py:122) verifies safe status and manual cancellation after revocation, not this worker transition.

### I4 — Source authorization is not rechecked immediately before the actual model attempt

**Grade: Important. Confidence: 9/10. Source-backed; pre-invoke revocation test unexecuted.**

[repair_agent.py:96](D:/CODE/turtle-soup/backend/app/agents/repair_agent.py:96):

> `reservation = self.store.reserve_decision(...)`

[repair_agent.py:104](D:/CODE/turtle-soup/backend/app/agents/repair_agent.py:104):

> `max_attempts=1, cancelled=cancelled, traffic_class="agent", response_contract="repair_action")`

No `before_attempt` hook is supplied.

The gateway creates its adapter before entering the actual attempt:

[model_gateway.py:190](D:/CODE/turtle-soup/backend/app/model_gateway.py:190):

> `owner.adapter = self._factory()`

Its available trusted hook runs immediately before adapter invocation:

[model_gateway.py:196](D:/CODE/turtle-soup/backend/app/model_gateway.py:196):

> `before_attempt(attempt + 1, deadline)`

**Failure path:** reservation succeeds, adapter construction stalls, and permission or source version is revoked before construction returns. If the independent heartbeat has not yet observed the change, the adapter receives the frozen prompt. Later result validation rejects the result, but cannot undo sending withdrawn material.

**Impact:** the result-write guard does not satisfy the separate D6 requirement to stop a subsequent model entry after revocation.

**Minimal fix:** use the existing trusted pre-attempt boundary to revalidate the already-reserved identity, live source, lease, original deadline and cancellation. Do not reserve again or refund the first intent. A refusal must become controlled handoff.

**Suggested test:** block adapter construction after reservation but before `invoke`, revoke source authorization, then release construction. Assert zero adapter invocations, the original reservation retained, and terminal `needs_human`. Include same-owner heartbeat success as a control.

This finding concerns a call **not yet dispatched**, not retracting an already-authorized in-flight cloud request.

### M1 — New agent HTTP routes are missing from the closed audit route registry

**Grade: Minor. Confidence: 10/10. Source-backed; HTTP audit assertion unexecuted.**

[audit_events.py:13](D:/CODE/turtle-soup/backend/app/audit_events.py:13):

> `ROUTE_TEMPLATES = frozenset({`

The registry omits all three routes introduced in [agent_runs.py:31](D:/CODE/turtle-soup/backend/app/routers/agent_runs.py:31), line 43 and line 49.

[audit_context.py:124](D:/CODE/turtle-soup/backend/app/audit_context.py:124):

> `routeTemplate=route_template if route_template in ROUTE_TEMPLATES else "unmatched"`

**Failure path:** start, status and cancel HTTP observations—including rejected attempts—are classified as `unmatched`.

**Impact:** HTTP audit consumers cannot reliably distinguish these operations. Typed business events still exist; this is not a claim that all audit evidence disappears or that rate limiting is bypassed.

**Minimal fix:** register the three closed templates, including the safe pre-routing recognition needed for rejected requests.

**Suggested test:** assert persisted HTTP-attempt templates for successful and rejected start/status/cancel requests, with varying UUIDs and oversized-body rejection. Preserve exclusion of raw IDs, credentials and bodies.

## Strengths and the five requested focus behaviors

The substantive review checklist led to checks of transaction boundaries and consumers outside the nominal TS14 files.

- **Atomic accounting and correction identity are well structured.** [store.py:429](D:/CODE/turtle-soup/backend/app/agents/store.py:429) enters the transaction before guarding/reserving; [store.py:453](D:/CODE/turtle-soup/backend/app/agents/store.py:453) keys correction allowance with `decisionEpisode=parent.operationKey`, rather than raw invalid output. The test at [test_agent_decisions.py:87](D:/CODE/turtle-soup/backend/tests/test_agent_decisions.py:87) rejects reset attempts and gives an unrelated later episode its own correction.
- **Stored decisions are dispatched before the new-call budget gate.** [repair_agent.py:71](D:/CODE/turtle-soup/backend/app/agents/repair_agent.py:71) handles an existing action before [line 89](D:/CODE/turtle-soup/backend/app/agents/repair_agent.py:89) checks model exhaustion. The tenth stored finish and remaining-tool cases have explicit tests at [test_repair_agent_loop.py:109](D:/CODE/turtle-soup/backend/tests/test_repair_agent_loop.py:109) and line 122.
- **Revocation-compatible terminal persistence is narrowly separated.** [store.py:342](D:/CODE/turtle-soup/backend/app/agents/store.py:342) uses `_terminal_stop_transaction`; [line 351](D:/CODE/turtle-soup/backend/app/agents/store.py:351) still rejects a changed owner token. This avoids fabricating a newly authorized source to stop an already-running task.
- **Gateway creation and shutdown share a real lock.** [runtime.py:57](D:/CODE/turtle-soup/backend/app/runtime.py:57) marks closure under the same lock used by [get_model_gateway at line 122](D:/CODE/turtle-soup/backend/app/runtime.py:122). This addresses gateway creation ownership; I1 identifies a different SQLite write boundary.
- **Admission is authoritative inside the gateway.** [model_gateway.py:89](D:/CODE/turtle-soup/backend/app/model_gateway.py:89) checks `not free`, `_waiting_online`, and existing agent ownership under its condition. [test_agent_admission.py:25](D:/CODE/turtle-soup/backend/tests/test_agent_admission.py:25) explicitly tests online arrival after the advisory snapshot, without refunding the agent reservation.
- **Missing corpus remains incomplete.** [runtime.py:113](D:/CODE/turtle-soup/backend/app/runtime.py:113) constructs `FixedRegression(self)` without silently discovering corpus material. The inspected regression/report/save consumers do not treat that absence as a passing candidate.
- **Evidence provenance is unusually explicit.** All eight reports are synthetic; real provider state is `not_called`, human references `not_collected`, and provider-accepted counts remain null. The 9/7 recovery distinguishes prior reservations from **one new adapter invocation**. Tool failure retains two failed attempts; unknown cleanup retains active ownership rather than inventing cleanup success.

| Requested focus | Judgment |
|---|---|
| Last stored valid decision at 10-used finishes without a new attempt | Explicit implementation and mechanical test coverage observed |
| Revoked running source can persist terminal status without restored access | Explicit implementation and mechanical coverage observed; queued case remains I3 |
| Gateway creation/shutdown ownership and terminal-only close persistence | Gateway lock and dedicated stop path observed; ordinary SQLite wait race remains I1 |
| Same invalid episode cannot reset; later independent episode retains correction | Explicit durable episode key and both assertions observed |
| Online arrival between snapshot and admission owns priority | Explicit atomic gateway checks and controlled race test observed |

These are bounded mechanical judgments, not real-provider or production acceptance.

## Scope and plan completion

| Area | Classification |
|---|---|
| Unit 1: durable decisions/stops and accounting | Substantially implemented; LOCAL lifecycle fencing remains incomplete through I1/I2 |
| Unit 2: bounded model-selected loop | Implemented under injected/scripted transports; LOCAL configured-adapter integration fails through C1, with I4 authorization gap |
| Unit 3: coordinator, heartbeat, lease and priority | Core machinery implemented; LOCAL heartbeat-write and queued-handoff behavior remains incomplete through I2/I3 |
| Unit 4: private HTTP, reports and documentation | Interfaces and current evidence present; M1 audit consumer omission remains |
| A51/A52 LOCAL engineering acceptance | Not closed by current passing gates because C1/I1–I4 are uncovered defects |
| A50 real eligible free-provider safe trajectory | EXTERNAL/explicit HOLD; not proven by mock success |
| A53 eight real independent human-reference tasks | EXTERNAL/explicit HOLD; eight synthetic reports are not substitutes |
| Actual independently reviewed corpus | EXTERNAL/explicit HOLD |
| Application corpus wiring | **LOCAL NOT DELIVERED / explicitly held**, independently of corpus availability |
| Production migration, activation and publication | Not performed or accepted |

I did not identify new autonomous approval, publication, migration-004, or paid-fallback authority in this implementation. Earlier TS01–13 dirty work was treated as dependency/history, not as unapproved TS14 changes.

## Reviewed material and commands

Directory links below identify the absolute roots; filenames enumerate the inspected files.

**Production source and integration dependencies**

- [backend/app](D:/CODE/turtle-soup/backend/app): `__init__.py`, `ai_host.py`, `audit_context.py`, `audit_events.py`, `audit_store.py`, `baselines.py`, `config.py`, `db.py`, `feedback_contract.py`, `feedback_store.py`, `host_cache.py`, `host_context.py`, `host_evidence.py`, `host_rules.py`, `main.py`, `migrations.py`, `model_admission.py`, `model_gateway.py`, `paths.py`, `prompts.py`, `question_normalization.py`, `rag.py`, `rate_limit.py`, `rate_policy.py`, `request_contract.py`, `request_guards.py`, `request_lifecycle.py`, `rule_contract.py`, `runtime.py`, `schemas.py`, `scoring.py`, `task_context.py`, `testing.py`; additionally `audit_middleware.py`.
- [backend/app/agents](D:/CODE/turtle-soup/backend/app/agents): all 14 files—`__init__.py`, `admin_contracts.py`, `agent_prompt.py`, `contracts.py`, `decision_contracts.py`, `preview.py`, `regression.py`, `repair_agent.py`, `source_identity.py`, `store.py`, `tool_contracts.py`, `tools.py`, `validation.py`, `worker.py`.
- [agent_runs.py](D:/CODE/turtle-soup/backend/app/routers/agent_runs.py); [migrate_data.py](D:/CODE/turtle-soup/backend/app/scripts/migrate_data.py).
- [backend/eval](D:/CODE/turtle-soup/backend/eval): `__init__.py`, `catalog.py`, `contracts.py`, `grouping.py`, `inventory.py`, `legacy.py`, `manifest.py`, `proofs.py`.
- [agent_fixtures.py](D:/CODE/turtle-soup/backend/testing/agent_fixtures.py): synthetic fixture construction/report behavior, not a production dependency.

Corpus verification was followed through `FixedRegression` → `backend/eval/manifest.py` and `backend/eval/contracts.py`. No nonexistent `agents/corpus.py` was assumed.

**Tests**

Full TS14 test control flow/assertions were read in [backend/tests](D:/CODE/turtle-soup/backend/tests):

`test_agent_admission.py`, `test_agent_audit.py`, `test_agent_conditional_loop.py`, `test_agent_decisions.py`, `test_agent_heartbeat.py`, `test_agent_http.py`, `test_agent_loop_races.py`, `test_agent_migrations.py`, `test_agent_prompt.py`, `test_agent_protocol.py`, `test_agent_recovery.py`, `test_agent_shutdown.py`, `test_agent_stop.py`, `test_agent_store.py`, `test_agent_task_reports.py`, `test_agent_tool_retry.py`, `test_agent_worker.py`, `test_repair_agent_loop.py`.

Adjacent dependency tests were inspected for behavior/assertions rather than exhaustive fixture-literal review:

`test_candidate_preview.py`, `test_candidate_reports.py`, `test_candidate_validation.py`, `test_fixed_regression.py`, `test_repair_contracts.py`, `test_repair_corpus.py`, `test_repair_tools.py`, `test_tool_results.py`, `test_ts13_review_regressions.py`.

Additional reads: full `test_model_adapter.py`; targeted transport/admission/lifecycle portions of `test_model_gateway.py`, `test_model_admission.py`, `test_settings_isolation.py`, and `test_ts05_review_regressions.py`. Imported fixture modules were not automatically counted as fully reviewed.

**Documents**

Read the required full TS14 design, plan, status, reference, explanation and how-to; `README.md`; TS13 design/plan and tool reference/explanation/status/review-resolution for dependency context.

Read the TS14/A50–53 and D2/D4/D6/D8 portions of these intent documents, not as execution evidence:

- [实施计划](D:/CODE/turtle-soup-audit/TurtleSoup_秋招升级实施计划_2026-10-06.md)
- [验收清单](D:/CODE/turtle-soup-audit/TurtleSoup_秋招升级验收清单_2026-10-06.md)
- [测试计划](D:/CODE/turtle-soup-audit/TurtleSoup_升级测试计划_2026-10-06.md)

Used the substantive gstack review checklist and requesting-code-review template. Mutating, external and delegated workflows were not executed.

**Commands actually performed**

- Read-only `rg` / `rg --files`, PowerShell `Get-Content` and line-numbered reads.
- `Import-Csv`, `Get-FileHash -Algorithm SHA256`, XML parsing and JSON-property comparisons.
- `git status --short`, `git branch --show-current`, `git rev-parse HEAD`, `git diff --check`.
- Read [scripts/test-backend.mjs](D:/CODE/turtle-soup/scripts/test-backend.mjs); did not invoke pytest or the full gates.
- One existing-interpreter `backend/.venv-ts01/Scripts/python.exe -B -c ...` diagnostic using `httpx.MockTransport`, two message-representation controls, and bounded gateway cleanup. It created no report, database, cache directory or source file.

The current logs record `npm run test:offline`, its backend/frontend/harness/API constituent runs, the isolated UI build/run, lint and typecheck. Those are inspected maintainer executions, not reviewer reruns.

## Coverage limits and recommendations

Security fixtures were reviewed in **summary mode**: rejection classes, ownership guards, counters, rollback and persisted outcomes. I did not expand payloads, create new attack fixtures, or claim exhaustive injection coverage.

The ten skipped backend cases remain unverified here: seven real-model opt-in cases, two Windows symlink-privilege cases and one unavailable Unix-socket case. Edge evidence does not establish a browser/platform matrix or new TS14 review UI coverage.

For the authorized single native C/I pass, address C1 and I1–I4 with their boundary-specific RED tests. Preserve the existing positive controls for same-owner heartbeat, last stored decision, correction episodes, terminal stopping and atomic online priority. Main should individually rule M1 and every item below. No second reviewer is recommended.

## Declined to judge

Each item is individually identified for main’s ruling.

- **D1 — HOLD / not judged:** actual free-provider eligibility, quota and cost safety; provider/account/network checks were prohibited and explicitly held.
- **D2 — HOLD / not judged:** A50’s real model-selected safe trajectory; the HTTP mock diagnostic establishes C1 only, not real-provider quality.
- **D3 — HOLD / not judged:** A53’s eight real independent human conclusions; current reports explicitly contain synthetic tasks and no collected human references.
- **D4 — HOLD / not judged:** correctness, independence and private contents of the actual corpus; original/private corpus reads were prohibited.
- **D5 — LOCAL NOT DONE / delivery judgment deferred:** actual application corpus wiring; explicitly held by the user. Its absence was recorded independently, and missing-corpus refusal was reviewed.
- **D6 — HOLD / not judged:** production migration/recovery behavior against production data; no production execution or data access was authorized.
- **D7 — HOLD / not judged:** production activation and operational readiness; default-off/local evidence does not establish that outcome.
- **D8 — OUTSIDE REQUEST / not judged:** deployment, shipping, PR integration, uploads and public publication; this was expressly a local review.
- **D9 — NEXT STAGE / not judged:** TS15 human approval/publication workflows and review UI; their absence is intentional TS14 separation.
- **D10 — HUMAN BOUNDARY / not judged:** universal natural-language entailment or semantic correctness of every pending candidate; mechanical validity is not semantic approval. Known program-detectable conflicts and report consumers were reviewed.
- **D11 — OUTSIDE TRUST MODEL / not judged:** hostile trusted-Python or OS/process sandbox resistance; model-controlled JSON boundaries and loaded-source identity were reviewed instead.
- **D12 — OUTSIDE LOCAL ACCEPTANCE / not judged:** production throughput, latency SLA and sustained online-starvation measurements; bounded admission mechanics were reviewed, not production load.
- **D13 — UNTESTED PLATFORM SUBSET:** skipped symlink/socket cases and browser/platform combinations beyond the recorded Windows/Edge run.
- **D14 — PROHIBITED INDEPENDENT CHECK:** reviewer rehash of original 239 private data assets; preservation claims were limited to inspected evidence logs.
- **D15 — HISTORICAL STAGE / not reopened:** earlier TS01–13 acceptance and the already-recorded TS13 stale-document Minor; dependencies were reviewed for TS14 integration, not re-adjudicated as new TS14 work.
- **D16 — UNEXECUTED DIAGNOSTICS:** new event-controlled reproductions for I1–I4 and persisted HTTP audit assertions for M1; these remain source-backed findings with explicit test suggestions, not newly observed failing test runs.
- **D17 — NO INDEPENDENT GATE RERUN:** selected/full/UI/lint/typecheck/doc gates; current frozen reports and logs were inspected, not rerun.

## Assessment

**NO — the current snapshot is not ready to close LOCAL TS14 acceptance.**

C1 prevents the configured adapter path from executing repair decisions. I1–I4 leave required lifecycle and authorization boundaries incomplete despite the current passing mechanical gates. Resolve or individually adjudicate those findings in the authorized single fix pass; rule M1 separately.

Real-provider, real-human-reference, actual corpus/wiring and production HOLDs remain unchanged. This is not a production, merge, ship or deployment approval.
