# TS-04 independent review package

Review is read-only; source/index/branch/runtime production data/network unchanged. No subagents, commits, resets, worktrees, real model calls or dotenv reads. Tests may write only guarded isolated temporary artifacts. The parent will work on disjoint TS-05 planning while the reviewed code is stable.

Base and HEAD: c5765b68cb251a7c566e76e2887d335d6ed6b285; TS-01/02/03/04 changes are intentionally uncommitted. A HEAD..HEAD diff is not evidence of no change. Read the new files directly and review only the TS-04 additions in shared files, not all legacy stage changes.

## Implemented scope

- backend/app/game_store.py: create_game_once, reserve_turn, finish_turn, expire_reserved_turns, get_turn_response, evaluate_once/get_evaluation, trusted cancellation commit gate, legacy writer guard. Uses only existing migration 001 tables and short BEGIN IMMEDIATE transactions.
- backend/app/game_service.py: model outside transaction, typed failure, manual-reveal reminder, deterministic evaluation callback, trace after a successful stored business result.
- backend/app/request_lifecycle.py: capacity-1 ASGI receive pump, per-request cancellation Event, no shared-client cancellation.
- backend/app/db.py: TS-04 rowVersion field, two legacy-writer guards, approved storage interface re-exports. Prior migration/catalog code is TS-02; do not re-audit it wholesale.
- backend/app/main.py: TS-04 chat/create/turn query/evaluate orchestration, canonical JSON for byte-stable replay, ended-session status/evaluation recovery, safe GameConflict/NotFound handlers with request IDs, run_request integration.
- backend/app/schemas.py: TS-04 ChatReplyResponse turnId/state additions only.
- backend/app/ai_host.py: TS-04 gateway cancelled signal only; semantic rule/scoring changes are TS-06/07, not this scope.
- backend/app/model_gateway.py: TS-04 request Event propagation/checks and bounded cancellation observation while waiting. Existing owned cleanup adapter/deadline mechanics are TS-03.
- Tests: test_game_transactions.py, test_turn_failure_recovery.py, test_game_request_recovery.py, test_evaluation_state_gate.py, test_request_disconnect.py. Existing legacy/isolation/typed host tests must continue passing.

## Binding requirements and rulings

Plan: docs/superpowers/plans/2026-10-07-ts04-atomic-game.md; ledger with Ruling lines: .../2026-10-07-ts04-progress.md; original spec D:/CODE/turtle-soup-audit/TurtleSoup_秋招升级实施计划_2026-10-06.md sections 6/7/8.3/8.6 and TS-04; A11–A17. Read-only migration 001 schema supplies all tables; no future 002/003 needed.

Rulings: focused storage module with db.* re-exports; blocked-model/no-write-lock integration tested in Task 3; optional trusted cancellation signal checked at the commit decision. A disconnect after commit can mean lost success, not retroactive failed/uncharge. Owner lifecycle remains independent of turn state.

## Review focus (verbatim)

1. First response lost after commit must replay the exact saved response, including failures and original remaining count, rather than run the model again.
2. Last available question under two event-synchronized callers must have at most one charged pair; reminders must not consume that opportunity.
3. Lease expiry followed by new work must fence the old worker even if it later produces a valid answer or win.
4. Failure after the first message/turn/count write must roll back the whole commit, not leave half a pair or a promised success.
5. Revealing during model work or after a win must not change terminal state; historical/failed turns cannot be used to fabricate a new evaluation basis.

Also check actual ASGI receive/cancellation sequencing, same-ID after terminal/reveal, capability scoping, request/response corruption handling, exception safety, callback under write-lock, and whether legacy writer guards have a bypass. Spec silence is not permission for behavior a reasonable player would find broken. Distinguish future queue/auth/cache/semantic/scoring/audit responsibilities from in-scope atomicity or privacy bugs; list every considered/declined behavior with reason, don't silently drop it.

## Verification and platform limits

Parent ran 54 TS-04 tests; full offline gate 382 backend + 7 Vitest + 6 harness + 3 API-only Playwright = 398 passed / 9 skipped, unchanged real runtime 239-file hash, typecheck 0. Nine skips: 7 real-model opt-in and two platform capabilities; pytest cache ACL warning remains. No real-provider/production/UI evidence implied.

Windows default sandbox hangs even empty asyncio.run(asyncio.sleep(0)) in socket fallback. Approved outside-sandbox offline tests still keep the repo NetworkGuard and file guards. Use backend/.venv-ts01/Scripts/python.exe -m pytest with -o cache_dir=.cache/ts04/reviewer-cache, small targeted scope, --tb=short. Tests may read only synthetic fixtures; no production player text/config/network. Observation timeouts are not failure or reason to spawn another reviewer.

Return specific reproducible findings, severity by actual user effect, file:line and test evidence; strengths + verdict + Declined to judge list. No source edits.
