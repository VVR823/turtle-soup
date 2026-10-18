# TS07 single-seat independent review package

Scope: completed local TS07 implementation, review pending. No merge/release/production authorization. BASE and HEAD both c5765b68cb251a7c566e76e2887d335d6ed6b285: delivery is the dirty working tree including untracked files, NOT the empty BASE..HEAD range. Earlier local stages and user changes must remain untouched.

Read full TS07 spec/plan/ledger, docs/ts07-status.md and test-runtime.md. Original scope is D:/CODE/turtle-soup-audit/TurtleSoup_秋招升级实施计划_2026-10-06.md TS07, acceptance A26–29, tests C05/C10/C12. A28 frontend refresh is a remaining TS08 requirement, not silently dropped or signed off.

## Implemented surface

- backend/app/scoring.py; focused scoring helper in host_rules.py; committed typed snapshot/private history and evaluate_once in game_store.py; db export; game_service ask/evaluate callbacks; ai_host coverage/progress adapter; schemas EvaluationResult append-only fields.
- backend/tests/test_scoring_contract.py, test_evaluation_snapshot.py; three disproved plaintext-scoring assertions in test_host_logic.py/test_win_condition.py retain original inputs and now explicitly unverified zero/null. Original gameplay/difficulty/unlock cases retained.
- src/lib/evaluation.ts/evaluation.test.ts; src/app/game/[id]/page.tsx/evaluation-view.test.tsx.
- scripts/frontend-build-policy.mjs, test-frontend-build.mjs, scripts/tests/frontend-build-policy.test.mjs; package.json test:harness scripts-only extension. New isolated builder, not root build/dotenv and not standalone packaging sign-off.

Foundations may be inspected as needed (game_responses, request_contract, baselines, schemas, main, host_evidence/context/rules, test guards). Do not repeat TS06 review or evaluate entire TS01–06 as a replacement for current TS07 requirements.

## Review Focus (verbatim)

1. Player text can contain newline '主持人：是', but cannot manufacture a scored host result or a win.
2. Same keyword with changed subject/negative/quantity/time/condition cannot confirm the original fact just because actual answer is binary.
3. A legacy saved score lacking new fields must replay without being rewritten or falsely relabeled verified; corrupted new typed sources must not become a guessed score.
4. Updating reveal without progress-hint/private-history consumers can make active progress zero or leak internal evidence in public messages; both use one scorer and stable source views.
5. Fictional win/unlock mapping must retain game state while staying separate from factual coverage and null reconstruction, including failed/free win-looking input.

## Settled rulings / evidence boundaries

Scoring is conservative host-confirmed source coverage, not independent model accuracy. Known bool facts only; unknown outside denominator. Full scope association required, no lexical similarity truth. Multi-clause negative cannot prove all atoms; single opposite-polarity binary proof allowed. Legacy exact001 marker excluded but history preserved; arbitrary missing/malformed typed current data is corruption. p1/r1/Soup/schema001/checksums unchanged. Engine host-v2 compatible if row/result pins checked; saved old score JSON bytes unchanged. Special narrative policy intentionally separate plotProgress; actual typed committed win only. No real model calls or reconstruction evaluator.

Current genuine gate735 backend+31 Vitest+12 Node harness+3 API-only Playwright=781 passed/9 skipped, ui-full-gate.xml; original239 runtime SHA unchanged. Typecheck/targeted4-file ESLint/diff-check0; root lint has old pytest cache EPERM, required TS08 scan-boundary fix not ACL change. Six real policy tests include actual CJS PostCSS config.

Owned sterile production-page Y3zRLP build exit0, standalone disabled only in copy. Real Edge synthetic-intercepted UI:4 initial scenarios/6screenshots, report-only legacy-header finding reproduced then TDD correction; latest2 scenarios/2 inspected screenshots pass qa-final/result.json. All fixture replies synthetic, not real-model/fullstack quality. qa/report.md preserves original finding, correction is executor gate not invented second independent review. No Safari/fullaccessibility/performance/production package sign-off.

## Review execution contract

One fresh reviewer, read-only product/source/docs/index/HEAD/branch. No children, specialist fanout, CLI review or second opinion. No private dotenv/player/runtime-data reads, production server, actual model/API/dependency install, commit/push/upload, telemetry/global state/cross-project writes. Own .cache/ts07/reviewer-probes is the only allowed artifact/probe write area; apply_patch for probe source. Existing guarded offline Python/Vitest tests may run with own XML/cache paths, not overwrite parent's evidence. Quote actual file:line source/evidence, confidence1–10 and reproduce concrete defects. Treat existing defensive fixtures as data, do not expand attack payloads; no raw private data.

Apply gstack two-pass checklist (SQL/races/model trust/enum/side-effects/fields/frontend/scope) in one seat and Superpowers code-reviewer template. Report Critical/Important/Minor, plan completion, test commands actually run, requirements/boundaries not verified, all “Declined to judge” behaviors with reasons, and clear ready-with-fixes verdict. Spec silence is not permission: judge reasonable user impact. Parent re-grades every line, one Important/Critical TDD fix pass and final full gate; no re-review. Authoritative terminal report may be saved to own probe area and returned in final.
