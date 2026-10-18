# TS14 Dynamic Repair Agent Implementation Plan

> Main native execution with executing-plans and test-driven-development; ONE clean inherited stage reviewer/ONE C-I fix/all Declined. User continuous authorization overrides new confirmation, commits, new worktrees and per-task reviewers. DESIGN ONLY until TS13 sole reviewer/fix/final gates are actually complete.

**Goal:** Implement actual model-selected actions with durable budgets/replay, independent heartbeat, shared admission and safe admin start/status/cancel, without paid fallback or fabricated real trajectories.

**Architecture:** Existing ModelGateway gets a closed server response contract; existing003 steps hold immutable decision/stop records, not a fourth table. RepairAgent drives bounded validated decisions/tools, one app worker independently renews lease and preserves original deadline. Default remains disabled; real evidence is an explicit held subset.

**Tech Stack:** Existing Python/Pydantic/SQLite/FastAPI/HTTPX/thread Events/native pytest/owned Edge fixtures; zero new dependency/install/model call.

**Spec:** docs/superpowers/specs/2026-10-10-ts14-agent-loop-design.md; original TS14/A50–53/D2/D4/D6/D8.

## Global Constraints

- Fixed10 model attempts/8 tool attempts/original180 seconds; max1 invalid episode correction and max1 same canonical tool retry, all failed/uncertain reservations remain consumed.
- Local gateway max2 owners/agent max1, online priority, no slot release until confirmed thread/transport cleanup; no remote termination/exactly-once claims.
- Worker lease60/heartbeat10 seconds; existing standalone30 preserved through closed SERVER-only30|60 configuration. No model/HTTP lease/budget/suite/role/traffic selection.
- Explicit Runtime/context/owned gateway; no default dotenv/model/database initialize or auto003. Immutable001002003 checksums/default1/application002, original239 preserved.
- No private user/env/corpus reads, actual provider calls, production data/deploy/publish/upload/commit/push/global skill writers. Default ENABLE_AGENT=false and one-API-worker guard unchanged.
- Review scope one whole TS14 peer after all four units; frozen TS13 source remains untouched until that separate review ends.

## Review Focus

1. Last valid stored decision at10-used must still finish; no fresh attempt on resume (Unit2 test).
2. Revoked source can still record terminal needs_human/admin status without reauthorizing model access or fabricating source (Unit1 test).
3. Gateway creation/shutdown race while worker closes: terminal-only close persistence cannot become a general late-write bypass (Unit3 test).
4. Different invalid raw output must not reset the same correction episode; independent logical later decisions must not lose their permitted single correction (Units1/2 test).
5. Online work arriving between advisory queue snapshot and claim still owns atomic gateway priority; no hidden extra owner/free refund/provider-count claim (Unit3 test).

## Unit1 — closed decision protocol and durable intent/stop primitives

Files: modify backend/app/model_gateway.py, agents/contracts.py, agents/store.py, audit_events.py; create agents/decision_contracts.py; tests test_agent_protocol.py, test_agent_decisions.py, test_agent_stop.py. Keep all SQL migrations unchanged. Extend fixed regression source registry only after native source-fingerprint tests for new executable files, not to imply old reports remain current.

Interfaces consumed: parse_agent_action(value), ExecutionIdentity, StepReservation, AgentCheckpoint/RetryCount, current _guard/_cas_lease/_complete, gateway owner/cancel/close, strict audit details. Produced: closed response_contract host_judgment(default)|repair_action; DecisionIntent/DecisionResult/StopIntent/StopResult/AgentStatus; reserve_decision(identity, *, prompt_digest, input_digest, correction_of=None), complete_decision(identity,result), stop(run_id, *, lease_token,state,reason), cancel(run_id, *, expected_row_version), read_status(run_id). StepRecord's INTERNAL stored-action parser admits decision/stop; public parse_agent_action does not.

- [x] Write native tests: valid five actions+finish round-trip through real gateway/owned fixed adapter, HostJudgment default still strict; duplicate/extras/NaN/oversize/copy forgery/unknown contract/callback/module/action=model_decision reject. Observations mark actual injected traffic, no provider receipt invented.
- [x] Write actualSQLite tests: reserving ninth->tenth leaves0, eleventh no new row/counter/call; actual intent+counter+audit atomic rollback; authorized replay immutable, oldplanned uncertain/no refund, new attempt consumes one. Parent correction same run/episode, changed invalid body cannot reset once; unrelated episode gets its one correction. Complete decision digest/owner/context checks and same-token heartbeat race.
- [x] Native stop tests: withdrawn context/deadline can stop with existing owner, stale owner cannot; admin stale version409, terminal clearslease but keeps counters; reason stored immutable internal step+typed audit, no unknown checkpoint keys. Status after withdrawal is minimal/no raw source. Closing only permits stop, refuses all new decisions/tools/results; bad record safe failure.
- [x] Run `node scripts/test-backend.mjs backend/tests/test_agent_protocol.py backend/tests/test_agent_decisions.py backend/tests/test_agent_stop.py -q --tb=short` through existing offline approved wrapper/cache XML. Expected real missing interfaces or behavioral failures, not collection/fixture errors. Then minimal exact signatures above, real RED→GREEN and adjacent host/gateway/store/audit suite. Report every failed/NOTEXECUTED command accurately; no checkpoint until terminal.

## Unit2 — actual bounded decision loop and prompt reconstruction

Files: create backend/app/agents/repair_agent.py, agent_prompt.py; tests test_repair_agent_loop.py, test_agent_recovery.py, test_agent_prompt.py; test-only scripted/action-aware fixtures under backend/testing, no gold-reading model in product.

Consumes Unit1 storage/gateway contract, TS13 ToolExecutor and guarded finish/candidates. Produces RepairAgent(store,executor,gateway), drive(run_id,lease_token,cancelled)->AgentStatus; bounded build_decision_messages(run,steps)->messages/inputDigest/promptDigest. Server identities are generated from current contiguous seq, not model arguments. Fixed registered prompt asset/context input<=8000chars/output<=32KiB.

- [x] Native tests different owned fake model-selected orders/stops/conditional branches, malformed correction once then needs_human, tool failure retryonce/new reservation, unknown/foreign authority stops with no tool execution. Persist actual selected action/result and stop; no hard-coded product tool order. No CoT/raw errors/gold/holdout in prompt/output.
- [x] Replay tests across planned intent, computed tool before result, candidate saved: old uncertain attempt retained, new operation/seq consumes budget under same logical retry cap; completed steps replay/no new attempt. Actual prior validated outcomes feed prompt, failure not a fake answer. 9-model/7-tool-used restart leavesone, original deadlineexpired zero new gateway calls. Last stored valid finish at10-used completes instead of incorrectly exhausting first.
- [x] Native cancellation/lease/context/source races during blocking adapter, heartbeat increments current row accepted, takeover rejects late decision/tool/candidate/finish. Unknown cleanup prevents later model work/tasks. Candidate finish references own stored candidate/report and only awaitsreview.
- [x] Run `node scripts/test-backend.mjs backend/tests/test_repair_agent_loop.py backend/tests/test_agent_recovery.py backend/tests/test_agent_prompt.py -q --tb=short` RED then minimal implementation. Actual default whole plus adjacent Unit1/TS13 after green; no real-model test/quality claim. If independent real corpus unavailable, preserve missing_corpus outcome, not a fake passing candidate.

## Unit3 — one durable coordinator, heartbeat and shutdown

Files: create backend/app/agents/worker.py; modify runtime.py/main.py/config.py only where needed for opt-in lifespan; extend AgentStore closed lease_seconds=30|60 with existing default30; tests test_agent_worker.py, test_agent_heartbeat.py, test_agent_shutdown.py, test_agent_admission.py.

Consumes RepairAgent.drive and Unit1 stop/status, shared Runtime.get_model_gateway and SQLite durable queued/running rows. Produces AgentWorker(runtime,store,agent), start(), stop_admission(), close(wait_seconds=2)->WorkerShutdown; runtime.agent_worker/agent_shutdown. Worker claims at mostone run, no RAM second source, model own threads stay governed by shared gateway. Event heartbeat separate from blocking drive.

- [x] Controlled clocks/Events tests queued waiting doesnotstart180; claim sets deadline once;60s worker lease/10s heartbeat with standalone30 compatibility. Blocked model receives independent heartbeat; no renewal afterterminal/cancel/deadline, failedheartbeat triggers cancellation and current token remains authority. No 60/180second wall sleeps.
- [x] Atomic online-priority/occupied2-owner/agent1 tests, race between advisory snapshot and claim, uncertain cleanup hold prevents nextmodel/queuedtask, boundedqueue10. Counter observations distinguish local reserved/admitted/unknown provider acceptance, no free refund or falsezero.
- [x] Lifespan tests disableddefault no worker/model/migration; enabled requires003+single API worker. Runtime first-gateway shutdown race preserved, stop-only closed writes cannot complete tool/decision. Bounded2s joins report incomplete/cleanup failed honestly, don't close another app gateway or kill running thread; same durable row recovers conservatively afterward.
- [x] Run four native files RED→minimal worker/lifecycle→GREEN and full current offline proof. No source edit while gates live, no production enable/envread/install. Independent heartbeat is infrastructure, not parallel model ability.

## Unit4 — admin endpoints, complete fixture evidence and one-stage gate

Files: create backend/app/routers/agent_runs.py and internal admin contract module if needed; register only scoped routes in main.py; tests test_agent_http.py, test_agent_task_reports.py. Docs agent-loop-reference.md, agent-loop-explanation.md, ts14-status.md and progress ledger. No candidate approve/publish route beforeTS15.

Consumes Unit3 owned worker/store/executor, existing strict route/admin/site/rate guards; produces POST /api/feedback/admin/agent-runs({feedbackId,requestId,expectedFeedbackVersion}), GET /api/feedback/admin/agent-runs/{runId}, POST /api/feedback/admin/agent-runs/{runId}/cancel({expectedRowVersion}). Start same payload idempotent202/runId, changedpayload409. Legacy missingtrace/privacy mismatch controlled refusal/no fake run; status minimal bounded valid stopped summary, admin auth configured/nonempty, no player/raw manifest leak. Defaultdisabled and required003 gate, no auto migration.

- [x] Native HTTP genuine admin auth/config/schema/limits/extras/cross-identity/input32KiB/idempotency/version/cancellation/disabledbefore003/production-default compatibility; status after revokedpermission safe. Existing game/API/synthetictraffic not assigned by caller.
- [x] Eight declared synthetic scenario task reports retain ALLplanned IDs/states/attempts/failed/handoff/unknowns; tests only mechanical, no falselyhuman references/provider success. Actual A50 one eligiblefree-model trajectory and A53 eight realhuman references remain HOLD with requirements/reason, never passfrommock.
- [x] Current exact selected and full offline/XML/EdgeUI/build/lint/type/diff/doclinks/original239SHA/normalownedclose; freeze changed files+dependencies/HEAD/index. ThenONE inherited clean TS14 peer with explicit bounds; main nextstage design only on disjoint files.
- [x] Regrade every C/I/M and Declined, ONE C-I native RED→GREEN fix and fresh whole/UI/hash. Minorledger only; close actual peer. Synchronize local engineering vs held external acceptance, continueTS15 without phase question/second reviewer.

Final LOCAL evidence: sole Poincare C1/I4/M1, all17Declined rulings; seven native boundary failures reproduced and fixed in ONEpass, introduced deadline-reason regression also corrected. Current338selected/14newcontrols/2422offline10skip/Eval412/29Edge/build/lint/type/79docs-example/7pages96links/239completeSHA unchanged. API114884/96892 and owned frontend closed normally; peer close returnedcompleted. M1 auditroute classification留TS17；actual provider/human/privatecorpus/production HOLD，trusted applicationcorpus wiring LOCAL obligation movesTS15. Full original report/rulings docs/ts14-review-report.md and ts14-review-resolution.md; old freeze remains historical, no secondreview or Git/production action.

## Preflight/self-review rulings

Internal decision/stop actions cannot become public model actions; old ToolAction .tool checks must reject them rather than AttributeError. Stop reasons live in immutable steps, not invented SQL columns/checkpoint fields. Default30 standalone/worker60 aligns original audit without silently invalidating TS13 controls. All future code mutation waits for TS13 terminal closure; actual human/provider subsets remain held. User accepted native+one-stage-peer continuously, not per-task review/commit/install rituals. The spec above is architecture decision, not evidence code/tests already exist.
