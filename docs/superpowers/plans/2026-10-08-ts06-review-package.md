# TS-06 independent read-only stage review

Repo D:/CODE/turtle-soup, branch codex/ts02-storage-foundation, HEAD/base c5765b68cb251a7c566e76e2887d335d6ed6b285. Intentional uncommitted TS01–06 and user changes; HEAD..HEAD is not the implementation diff. Use git diff HEAD plus full untracked listed modules. Preserve tree/index/HEAD, no commits/push/deploy/real models/private runtime data reads.

## Requirements

- Spec docs/superpowers/specs/2026-10-08-ts06-grounded-host-design.md.
- Plan docs/superpowers/plans/2026-10-08-ts06-grounded-host.md.
- Rulings docs/superpowers/plans/2026-10-08-ts06-progress.md.
- Original plan and acceptance/test plans in D:/CODE/turtle-soup-audit; TS-06 A22–A25, D9/D14/D21/D22. All original 18 stages remain required, no scope reduction.

## Source and integration

Read full backend/app/question_normalization.py, host_evidence.py, host_rules.py, host_cache.py, host_context.py, rag.py, ai_host.py; TS06 additions in schemas.py/runtime.py/game_service.py/game_store.py/db.py/main.py. game_responses/baselines/model_gateway/trace_logger are dependencies. Earlier TS01–05 wholesale work is already independently reviewed, but concrete integration regressions must not be silently declined. No real dotenv/backend/data/root data content reads.

Source-aware exact normalization (no negation/subject/number collapse), small explicit-polarity grammar, exact authored whole questions and complete covered conjunctions, precise genre/specific presence/total-count metadata. Generic references defer even with an authored exact question. Empty-history first-person story narrator compatibility is explicitly context-dependent/noncacheable. Old regex/RAG helpers stay only legacy diagnostics/scoring, no online answer authority; full truth/history normal model fallback remains. Strict scoring still TS07.

Actual p1 source verified even before cache hits; program-owned flags default False; complete versioned key, locked LRU 1024/insertion TTL600, independent copies/revalidation/aggregate counts, no player/HTTP state. new turns host-v3, stored host-v2 unaffected. Old dictionaries inert. API search only public title/surface/tags, legal reveal unchanged. Future published rule schema/003/Agent/audit/provider/holdout/OS/production gates not signed off.

## Verification evidence

New module tests: exact23/evidence13/semantic25/genre19/cache40/public-search13 = 133. Refined legacy cache policy and unlock test's explicit local transport, adding irrelevant-answer/no-unlock scenario. Two old monkeypatch host signatures now take versions, blocking/isolation assertions retained.

RED artifacts exact-key-red/evidence-red/semantic-red/cache-red/cache-integration-red/search-red/cache-observability-red.xml in .cache/ts06. Appropriate GREEN/failure copies listed in ledger, no skipped failed cases.

Final parent gate: 621 pytest + 7 Vitest + 6 harness + 3 API-only Playwright = 637 passed / 9 skipped, exit0 (.cache/ts06/pre-review-full-gate.xml). Original239 SHA256 d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a unchanged, owned server PID104196 normal exit. Typecheck/diff check0; cache ACL/CRLF warnings retained. This is not real model accuracy/UI/production evidence.

## Review Focus (verbatim)

1. An exact authored sentence with pronouns can be true in one history and false in another; cache bypass alone cannot legitimize a context-dependent generic rule.
2. A regex that covers one clause must not prove an added false clause, changed subject, quantity, time or condition; successful local fixtures do not authorize unseen variants.
3. An evidence ID must bind the existing source record and pinned version, not merely be a well-formed hash; duplicate texts across soups must remain scoped.
4. A cache key or returned result mutation must not turn an old/stale pure result into a new rule/player response or survive version/TTL boundaries.
5. Disabling private search must preserve legal reveal and ordinary unanswered questions; uncertainty goes through the normal model path, not a malformed-output error.

## Review protocol

One fresh reviewer, one subsequent effect-graded Important/Critical TDD fix pass, no reviewer fanout/re-review. Apply gstack review checklist and Superpowers reviewer template, native dirty/local/no-remote adaptation. Do not run Unix/global telemetry/installation/upload/extra CLI reviewers, change HEAD/index or start another agent. User local autonomy replaces stage-confirmation menus, not external gates. Grade effect on ordinary players, not spec silence.

Read-only scoped review; optional scratch probes/report only .cache/ts06/reviewer-probes (apply_patch), never edit source/tests/docs. Retain repository conftest/network/private-data guards, explicit pytest root/conftest, use a reviewer-specific cache/JUnit path and don't overwrite parent's XML. Default Windows async sandbox is known to hang, use normal approval for guarded offline execution, do not bypass a denial. Record every declined-to-judge behavior individually with reason before verdict; parent will rule each one. State exact tests/commands/results and skips, don't infer full gate from targeted probes. Snapshot source hashes before/after if running probes. Return strengths, Critical/Important/Minor with concrete lines/conditions/user effect/tests, recommendations, assessment and declined list. If quota fails, preserve progress/report once, no repeated probes/payment/model upgrades.
