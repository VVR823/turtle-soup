# TS-04 Atomic game requests implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repeated or concurrent requests cannot create duplicate games, overcharge a turn, split a question/answer pair or overwrite terminal state.

**Architecture:** Reuse 001 creation_requests/turns/evaluations and session row_version. A short BEGIN IMMEDIATE transaction reserves one session turn with a random lease token and 90-second expiry; model work runs outside all write transactions. Another short transaction validates lease/state/version and atomically commits response, pair, charge and win state. A small game_service module orchestrates this; main remains HTTP/auth/validation glue. TS-07 supplies corrected scoring inside the same evaluation snapshot gate.

**Tech Stack:** Existing SQLite/Python/FastAPI/Pydantic/HostResult/FakeModel, no new dependencies or services.

**Spec:** `D:/CODE/turtle-soup-audit/TurtleSoup_秋招升级实施计划_2026-10-06.md`, sections 5.1 TS-04, 6 invariants, 7, 8.3–8.6; A11–A17 and C04–C09.

## Global constraints

- Preserve existing endpoints/camelCase and original player history; 0 new paid cost; no actual model calls, production migration/deploy/publication or automatic Git commits.
- Same creation requestId plus same payload creates one session; changed payload →409. Raw business input after validated trimming is hashed; omitted/invalid level still uses the strictest limit but distinct submitted payloads remain distinct.
- Same session/requestId/question replays stored terminal response without a new model call/charge. Different question under same ID →409. In progress same request →202; another active request in the same session →409.
- One active turn/session; reserve validates playing status, pinned versions and remaining count under one lock. Lease 90 seconds; expiry recovery never repeats a model call.
- Final commit rechecks lease token, expected session row_version, state, expiry and terminal status. A stale result cannot create messages, change counts or win state.
- Success commits one pair linked to one turn and one charge; reminder/error charge 0; system_error is not a valid fact. Failed/expired/cancelled business state and still-running model ownership are different lifecycles.
- Evaluation conflicts with reserved turns (409), preserves solved state, and stores one response/basis snapshot. Repeated reveal returns that snapshot; no model work inside its write transaction.
- Current anonymous session/request IDs are capability-like secrets, not account RBAC or cross-device identity. No public logs/export of these IDs; no new user account system.
- Core changes wait for the TS-03 independent review fix gate. Disjoint plans/tests may be prepared in parallel; do not rewrite reviewed source concurrently.
- Continuous execution is user-authorized; unresolved external/permission/ground-truth matters are logged per item while independent work continues.

## Review focus

1. First response lost after commit must replay the exact saved response, including failures and original remaining count, rather than run the model again.
2. Last available question under two event-synchronized callers must have at most one charged pair; reminders must not consume that opportunity.
3. Lease expiry followed by new work must fence the old worker even if it later produces a valid answer or win.
4. Failure after the first message/turn/count write must roll back the whole commit, not leave half a pair or a promised success.
5. Revealing during model work or after a win must not change terminal state; historical/failed turns cannot be used to fabricate a new evaluation basis.

---

### Task 1: Idempotent creation and short transactional reservation

**Files:** Modify `backend/app/db.py`; create `backend/app/game_service.py`, `backend/tests/test_game_transactions.py`.

**Interfaces:** `db.create_game_once(soup_id: str, level: str|None, request_id: str) -> dict` returns the safe creation response stored in creation_requests. `db.reserve_turn(session_id: str, request_id: str, question: str, *, soup_id: str|None=None, now: float|None=None) -> TurnReservation|TurnReplay`; immutable TurnReservation carries turnId/sessionId/requestId/question/leaseToken/expectedRowVersion/puzzleVersion/ruleVersion/engineVersion; TurnReplay carries state/httpStatus/safeResponse. `GameConflict(code)` is translated into a stable safe 409 by main, not raw SQL text.

- [x] Write tests for concurrent identical create (one session/creation row/same response), changed payload conflict, strictest-level behavior, different independent request IDs, active-turn uniqueness, same-ID in-progress replay, changed question conflict and unknown/terminal/incompatible session.
- [x] Run targeted tests; observe missing behavior failures.
- [x] Implement parameter-bound BEGIN IMMEDIATE operations and canonical payload hashes using existing baselines helpers; creation response is derived from the transaction's pinned active soup, not a stale in-memory title. Reserve increments session row_version, records its token/version and releases DB locks before returning.
- [x] Test that a separate connection can acquire a write transaction while a FakeModel is blocked after reservation.
- [x] Run targeted creation/reservation tests and record actual results; no commit.

### Task 2: Fenced whole-turn commit and expiry

**Files:** Modify `backend/app/db.py`, `backend/app/game_service.py`; expand `backend/tests/test_game_transactions.py`; create `backend/tests/test_turn_failure_recovery.py`.

**Interfaces:** `db.finish_turn(reservation: TurnReservation, result: HostResult, *, now: float|None=None) -> TurnReplay`; `db.get_turn_response(session_id: str, request_id: str, *, now: float|None=None) -> TurnReplay|None`; `db.expire_reserved_turns(session_id: str, *, now: float|None=None) -> int`. Core state/result/safe response is recorded only in existing 001 tables, never future audit tables. Expected version is held by the owner; expired recovery bumps session version so stale tokens cannot commit.

- [x] Write last-question concurrency and repeated-ID tests: one pair/two linked messages/one count, unchanged response replay, same text with new ID treated as a distinct intentional request.
- [x] Write reminder/error/win tests: explicit result kind controls charge; win stores solved atomically; failed output does not enter confirmed-answer scoring/context; failure retry same ID returns original failure, not a new model attempt.
- [x] Write fake-clock expiry and late-result tests: reclaim reservation once, no implicit model retry, reject old token/version/expired lease and stale win; current local gateway owner can remain active independently.
- [x] Write fault-injected tests after user-message insert, host-message insert, count/session update, response/turn update and commit boundary; original dump/count/state is unchanged on rollback.
- [x] Observe failures, implement minimal fenced commit/expiry, run targeted gate. Retire or strictly restrict legacy single-message/status writers so they cannot bypass the atomic API; adapt isolation fixtures to the paired-turn contract without dropping data guards.
- [x] Record exact failure locations/recovery outcomes and any limits; do not infer crash safety from success tests alone.

### Task 3: HTTP orchestration, response recovery and evaluation state gate

**Files:** Modify `backend/app/main.py`, `backend/app/schemas.py`; expand game_service; create `backend/tests/test_game_request_recovery.py`, `backend/tests/test_evaluation_state_gate.py`.

**Interfaces:** `game_service.ask(req: ChatRequest) -> TurnReplay` orchestrates reserve → frozen soup/history → host outside transaction → finish. Main uses stored safe HTTP status/body for replay. New GET `/api/session/{session_id}/turns/{request_id}` checks the session capability and validated ID, returns in-progress or stored terminal result, never enumerates another session. `db.evaluate_once(session_id: str, evaluator) -> dict` checks no reservation, computes the existing deterministic evaluator under the protected snapshot gate and stores one basis/response; TS-07 later changes scoring, not the transaction interface.

- [x] Write actual local API tests for lost response then retry/query, stable failed response replay, redundant soupId conflict, 202 in-progress, 409 other active question and 404 cross-session request lookup.
- [x] Write reveal-during-blocked-FakeModel test (409), win remains solved on reveal, repeated reveal byte-equivalent safe snapshot, ended game cannot append a new successful turn.
- [x] Cover explicit client cancellation/disconnect: use a request-owned cancellation signal and persistent failed turn, do not claim a still-running transport has stopped or allow its late result to charge. Assess TS-03 reviewer observations before choosing the smallest ASGI integration; keep the endpoint contract unchanged.
- [x] Observe failures; connect main to game_service and remove split save_message/count writes. Every answer/reminder/error obtains a real turn ID; transport failures preserve known status and requestId in a safe response.
- [x] Re-run existing normal-question/difficulty/hidden-soup/legacy compatibility/isolation tests. No frontend behavior rewrite before TS-08's Next-specific guides and stable backend contract.
- [x] Record transaction vs model-owner lifecycle behavior and legacy limitations explicitly.

### Task 4: Stage gate and automatic continuation

**Files:** Update `docs/ts04-status.md`, stage ledger, API/runtime reference and autonomous-progress.

- [x] Run full offline/data-isolation gate, TypeScript typecheck, git diff --check; verify actual runtime hash unchanged.
- [x] Run independent read-only TS-04 review; reproduce important findings with failing tests, fix once and rerun full gate.
- [x] Map A11–A17 to actual evidence, leave real deployment/OS-matrix/provider/production backup gates unverified.
- [x] Continue to TS-05 automatically; no user-stage prompts, automatic purchase, deploy or public upload.

## Pre-flight/self-review

- TS-02 already created all 001 tables needed here; no migration 002/003 dependency or new service is required.
- HostResult from TS-03 controls business charge; do not reintroduce emoji/free-text parsing in persistence. HostVersions in result must agree with reservation versions, not model assertions.
- Session row_version plus unique active-turn index and lease token fence completion; a Future timeout alone does not close a turn or release model ownership.
- Stored terminal response needs its HTTP status persisted as an explicit envelope in response_json (e.g. schemaVersion/httpStatus/body), not guessed from prose on replay. Historical legacy turns lack this envelope: expose a clear legacy-result-unavailable state, never synthesize a successful replay.
- Evaluation reuses existing deterministic function temporarily; this is state/atomicity only, not proof the old coverage/reconstruction scoring is correct. TS-07 remains a release requirement.
- Source/queue/transport deadline limitations surfaced by TS-03 review are resolved there or carried here explicitly; none are silently marked complete.
