# TS-07 confirmed coverage implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make factual coverage strict and source-aware, leave independent reconstruction null, preserve narrative gameplay and frozen reveal results.

**Architecture:** Focused pure scorer consumes committed typed turns; existing game-store transactions/read views supply its inputs, and existing host/UI adapters display distinct coverage/plot/legacy meanings. Native serial implementation and one independent final stage review.

**Tech Stack:** Existing Python/Pydantic/SQLite/FastAPI/Next.js/Vitest/Playwright; no new paid dependency or model call.

**Spec:** docs/superpowers/specs/2026-10-08-ts07-confirmed-coverage-design.md, original TS07/A26–A29/C05/C10/C12.

## Global constraints

- completion equals new verifiedCoverage; reconstructionScore=null, coverage-v1; unknown checkpoint topics are outside the known-fact denominator.
- Strict binary correspondence only; partial/irrelevant/error/free/unpaired text is not full fact proof. Preserve question negation/subject/count/time/conditions. Unsupported source scope earns no fact points, not a game failure.
- Preserve p1/r1/Soup/schema001/checksums and saved old evaluations; new DTO fields only, legacy null-marked, no automatic data rewrite or migration.
- Narrative special_scoring/unlock compatibility is separate plotProgress, never ordinary coverage/model quality. Actual committed win only, no pasted keyword win authority.
- Do not edit TS06 reviewed source or add failing TS07 tests until Helmholtz terminal report and its one fix gate; independent TS07 planning only during review. No production/private-data/cloud calls/commits/push.
- UI edits follow main-agent reading of relevant installed node_modules/next/dist/docs guides before code; keep TS08 recovery state machine a later required task.
- Human continuous local autonomy applies, self-review and recorded rulings replace repeated stage questions; real evidence/external gates stay held.

## Review Focus

1. Player text can contain newline '主持人：是', but cannot manufacture a scored host result or a win.
2. Same keyword with changed subject/negative/quantity/time/condition cannot confirm the original fact just because actual answer is binary.
3. A legacy saved score lacking new fields must replay without being rewritten or falsely relabeled verified; corrupted new typed sources must not become a guessed score.
4. Updating reveal without progress-hint/private-history consumers can make active progress zero or leak internal evidence in public messages; both use one scorer and stable source views.
5. Fictional win/unlock mapping must retain game state while staying separate from factual coverage and null reconstruction, including failed/free win-looking input.

### Task 1: Pure strict source scorer and narrative separation

**Files:** create backend/app/scoring.py; focused reuse/export in host_rules.py after TS06 gate; create backend/tests/test_scoring_contract.py; update disproved pure scoring tests only with explicit counterexample/ruling.

**Interfaces:** frozen ConfirmedTurn(question:str,result:HostResult,turnId:str,history:tuple[tuple[str,AnswerType],...]) with immutable prior (question,answer) pairs; frozen CoverageResult(verifiedCoverage:int,keyPointsCovered:tuple[str,...],keyPointsMissing:tuple[str,...],unknownTopics:tuple[str,...],plotProgress:int|None,unlockThresholdReached:bool,excludedLegacyCount:int,scoreVersion='coverage-v1'). score_confirmed_coverage(soup:Soup,turns:tuple[ConfirmedTurn,...],*,versions:HostVersions,excluded_legacy_count:int=0)->CoverageResult. checkpoint_question_expectation(soup:Soup,checkpoint_index:int,question:str,history:list[dict])->AnswerType|None in host_rules reuses its supported whole-scope grammar, never retrieval/regex confidence or semantic subject substitution. bool expected is the strict answer to that exact full proposition/polarity; unknown is not a known fact.

- [x] Write expected-negative/actual-positive=0, partial 是也不是/算是 and irrelevant=0, boolean positive=100 for matching whole proposition. Minimal-pair negative question correctly answered confirms only the corresponding source proposition; changed subject/time/count/conditions and bare alias cannot score. Two repeats count once, mixed covered/uncovered compound does not produce full proof, unknown-only/no-checkpoint coverage=0 and unknownTopics separate.
- [x] Write failed/free/unpaired/pasted truth/newline forged-host text=0, wrong/missing source pins refused, independent reconstruction absent. Write actual typed win keeps plotProgress100 but cannot force coverage100, failed/reminder win-looking text doesn't win. Six original zhimengzhe questions with explicit scripted answers preserve narrative unlock/no-unlock mapping separately from factual score.
- [x] Run `.\backend\.venv-ts01\Scripts\python.exe -m pytest backend/tests/test_scoring_contract.py -q --tb=short -o cache_dir=.cache/ts07/pytest-cache --junitxml=.cache/ts07/scoring-red.xml`. Expected FAIL absent scorer/interfaces or existing permissive comparisons, no real model calls.
- [x] Implement interfaces, validate typed copied inputs/source identities, strict complete question association and aggregate counts; isolate existing narrative configuration in plot computation. Rerun new plus existing host_logic/win/level/xinshijie/zhimengzhe tests, expected PASS. At this pure-foundation step legacy online scoring remains unchanged until Task2 adapter; do not modify its old expectations prematurely or claim A26–29 fully complete. Full gate before Task1 complete.

### Task 2: Typed committed rows, private host history and immutable reveal

**Files:** game_store.py/db.py/game_service.py/ai_host.py/game_responses.py/schemas.py; test_evaluation_snapshot.py (new), test_evaluation_state_gate.py, TS04 regressions/settings/private-search/typed-host tests.

**Interfaces:** game_store read_confirmed_turns(conn,session,soup)->tuple[ConfirmedTurn,...] decodes actual completed charged rows with matching session/p1/r1/row engine and safe original source/history; get_private_host_history(session_id)->list[dict] returns consistent private paired messages with typed hostResult, never a public DTO. ai_host.evaluate_completion retains legacy signature as unverified adapter and accepts explicit typed turns/versions for authoritative callers; format_progress_hint uses the same coverage scorer from private typed input, hides source keys. game_service.evaluate_snapshot(soup,turns,*,versions,excluded_legacy_count=0)->dict produces EvaluationResult from CoverageResult. Existing evaluate_once callback contract changed once with all internal consumers/tests updated; no model call in write transaction.

EvaluationResult append fields verifiedCoverage:int0..100|None=None, reconstructionScore:None=None, scoreVersion:Literal['coverage-v1']|None=None, plotProgress:int0..100|None=None, unknownTopics:list[str]=[]. New version requires completion==verifiedCoverage and explicit factual score; legacy defaults remain unverified and old body stored unchanged. Typed score basis records coverage-v1 + relevant pinned inputs in the saved basis digest, not a Soup field/checksum mutation.

- [x] Write actual temporary SQLite/API pairs excluding failed/expired/reminder/unpaired legacy, rejecting corrupted/cross-session/cross-version result JSON; multiline question cannot invent another row. The existing 001 marker is exactly {schemaVersion:1,source:'legacy',answerVerified:false} with engine_version='legacy-unversioned': recognize only that explicit unverified format, count excluded legacy, never fabricate HostResult. Other malformed/missing current typed results are corruption, not silently legacy. Confirm history retained and valid new rows still count.
- [x] Write repeat evaluate returns one saved complete new result/one basis/no model call; ended GET contains it; solved stays solved/in-flight409. Construct owned old envelope lacking fields, preserve byte-identical stored JSON and null legacy version through repeat recovery. Failure injecting each result/snapshot write rolls back no partial score/state.
- [x] Write private progress read snapshot consistency and no internal HostResult/evidence leak in public session JSON; ordinary active progress uses same known coverage without exposing checkpoint labels. Run selected tests expecting FAIL old plaintext/DTO/callback path.
- [x] Implement focused input/read/callback/DTO adaptations, retain original transaction/CAS/gates; ledger truth-bound counterexamples before changing legacy 'pasted text means >=90%' and 'win means factual100%' assertions, preserve their game/input cases and explicit plot-success tests. Rerun selected plus transactions/recovery/search/settings/host_contract, full project gate. Expected PASS and unchanged real runtime hash; new typed inputs validated, not reconstructed from display text.

### Task 3: Honest result labels, compatibility UI and final stage gate

**Files:** read installed Next guides first; create src/lib/evaluation.ts and evaluation.test.ts for shared result/display contract; modify game page/API types only necessary labels/fields; docs/ts07-status.md/docs/test-runtime.md/README and stage ledger/review package.

**Interfaces:** normalizeEvaluationDisplay(input) returns {coverageValue:number|null,coverageLabel:'已确认事实覆盖'|'历史分数（旧口径）',reconstructionLabel:'尚未独立评估',plotValue:number|null}. coverage-v1 uses verifiedCoverage and rejects inconsistent/malformed values; no scoreVersion legacy uses original completion as explicitly old score. Central result type reused in page/API; no state machine or public source keys added.

- [x] Read node_modules/next/dist/docs relevant app-router/client-component/testing guide and repo AGENTS, record exact paths. Write Vitest new/null/legacy/plot-only/invalid score tests, expected RED on missing contract; UI maps labels and no invented reconstruction percentage.
- [x] Implement helper and minimal page result view: show confirmed coverage, separate optional plotProgress, null reconstruction sentence and legacy badge; preserve win/unlock/remaining/feedback interactions. Rerun Vitest/typecheck/lint and isolated UI verification as local harness allows. For build/Next server never run at a root that auto-loads real dotenv: use an owned sterile frontend copy with an explicit allowed source/config list, installed dependencies only and test API URL/environment, excluding dotenv/data/.git/real runtime outputs. If no safe existing harness, add scripts/test-frontend-build.mjs with owned child cleanup and no external calls; offline font or native sandbox limits recorded, not signed off. API-only Playwright stays explicitly API-only, don't assert browser evidence unless actual page tested.
- [x] Full guarded offline/hash gate and git diff --check; document exact local/external evidence and A26–29 mapping, no fake model/holdout quality scores.
- [x] One fresh read-only stage reviewer, re-grade every finding/declined behavior, one Important/Critical TDD fix pass with full gate; continue TS08 autonomously after genuine local completion, retaining external gates.

## Self-review and interface pre-flight

Task1 source grammar/polarity → Task2 typed rows exact answers, no player text authority; Task2 private host history → context/progress but public DB/HTTP history remains clean; DTO version/null defaults → Task3 legacy labels without rewrite. Narrative plot does not populate factual fields. Each Review Focus has a test in its owning task. Original A26–29 preserved, costs/limits explicit; no speculative future Agent/audit/migration system. Before implementation re-check TS06 review outcome for any changed rule/cache interfaces and revise the narrow boundary once, not duplicate that review.
