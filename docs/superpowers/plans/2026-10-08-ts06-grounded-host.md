# TS-06 grounded host implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop weak similarity, negation/subject collapse and stateful caching from producing confident wrong answers while preserving normal context-aware gameplay.

**Architecture:** Pure exact normalization, pinned evidence/rule decisions and bounded typed cache, integrated into existing host/service/context; no parallel game engine or new service. Native serial implementation, one independent final stage review.

**Tech Stack:** Existing Python/Pydantic/FastAPI/SQLite/stdlib and guarded pytest FakeModel/event clocks, no paid/new dependencies.

**Spec:** docs/superpowers/specs/2026-10-08-ts06-grounded-host-design.md; original TS-06 A22–A25 and D9/D14/D21/D22.

## Global constraints

- Exact NFC/trim/whitespace-fold/terminal-question-mark-only normalization; preserve negation, casing, subject, numbers, conditions and other punctuation. Version exact-v1.
- Cache LRU 1024 / insertion TTL 600s, locked and copy-isolated, complete versioned keys; only verified pure deterministic answers, never player state/LLM/context/win/error/reminder.
- Existing immutable p1/r1 Soup payloads remain readable; no new Soup fields, in-place snapshot edits, new migrations, future publication/Agent tools or external writes.
- Full truth and at most 12 valid complete turns/8000chars retained through the existing model path; weak match is evidence not a factual answer. No paid model/fallback or real calls.
- TS-05 reviewed source held stable until its one review/fix gate completes. Only disjoint docs and the dependency-free exact-key function/new tests advance during that review; evidence/rag/host/runtime integration waits. Preserve existing user changes/real runtime files.
- Human no-stage-confirmation delegation applies; record consequential rulings, continue unaffected parts, do not guess external evidence. No automatic commit/push/deploy.

## Review Focus

1. An exact authored sentence with pronouns can be true in one history and false in another; cache bypass alone cannot legitimize a context-dependent generic rule.
2. A regex that covers one clause must not prove an added false clause, changed subject, quantity, time or condition; successful local fixtures do not authorize unseen variants.
3. An evidence ID must bind the existing source record and pinned version, not merely be a well-formed hash; duplicate texts across soups must remain scoped.
4. A cache key or returned result mutation must not turn an old/stale pure result into a new rule/player response or survive version/TTL boundaries.
5. Disabling private search must preserve legal reveal and ordinary unanswered questions; uncertainty goes through the normal model path, not a malformed-output error.

### Task 1: Exact keys and pinned evidence-only retrieval

**Files:** create backend/app/question_normalization.py, backend/app/host_evidence.py; modify rag.py/host_context.py only after TS-05 gate; tests test_exact_question_keys.py/test_host_evidence.py.

**Interfaces:** NORMALIZATION_VERSION='exact-v1'; normalize_exact_question(text:str)->str. Frozen EvidenceRecord(id,soupId,puzzleVersion,sourcePath,category,payload:str) (complete canonical JSON payload) and retrieve_evidence(soup,question,*,puzzle_version,limit=8)->tuple[EvidenceRecord,...], strict integer limit 1–8. build_evidence_catalog(soup,puzzle_version) verifies the p1 hash of the actual canonical Soup payload, validates source identities and creates content IDs; malformed/mismatched versions raise SnapshotError, not empty evidence. Retrieval never returns a chosen answer.

- [x] Write minimal pairs: ' 小明是凶手？ '→'小明是凶手', Unicode composed equality/whitespace folding; 否定/主体/3与4/2004与2006/如果/逗号句号/casing not equal; empty/non-string refused. Test same record repeat stable ID, same text different soup/version different ID, absent source not fabricated, bounded whole evidence, wrong plausible p1 hash rejected, invalid 0/9/bool limits rejected, payload immutable/canonical full record.
- [x] Run `.\backend\.venv-ts01\Scripts\python.exe -m pytest backend/tests/test_exact_question_keys.py backend/tests/test_host_evidence.py -q --tb=short -o cache_dir=.cache/ts06/pytest-cache`. Expected: FAIL missing interfaces.
- [x] Implement pure modules and evidence-only rag API; keep private complete truth/context budget. Add a weak positive/negative checkpoint collision test showing no deterministic answer is chosen merely from ranking.
- [x] Rerun targeted plus test_host_context.py/test_legacy_compatibility.py/test_migrations.py. Expected: PASS, no baseline schema mutation; run project gate before task completion, record precise evidence.

### Task 2: Guarded rule decisions and precise metadata

**Files:** create backend/app/host_rules.py; modify ai_host.py; tests test_semantic_rule_guards.py and test_genre_evidence.py, existing host logic/confirmed fixtures preserved.

**Interfaces:** frozen RuleDecision(answer, evidenceIds, contextIndependent, scope, ruleId); decide_deterministic(soup,question,history,*,versions)->RuleDecision|None. Program-owned scope='whole_question'|'all_clauses'|'metadata'. Reference-dependent/unsupported/weak variants return None. Existing workflow/win/special modes remain separate.

- [x] Write same-subject opposite-polarity, changed subject, quantity, time and conditions; one matched true clause plus unsupported/false clause cannot return a partial whole answer; weak checkpoint ranked but fallback invoked with original question/history. Test two histories resolving '他' to alive/dead despite same authored generic question, neither gets a fixed universal answer.
- [x] Write time-travel-only/no-magic synthetic Soup and unknown fact cases; 变格 alone never answers 有魔法 as affirmative. Precise positive/negative genre forms, mixed types and conditional/subset cast count. Add existing eight zhimengzhe and two hotel complete-question fixtures to preservation assertions.
- [x] Run targeted command selecting these files. Expected: FAIL known semantic shortcuts, not real model calls. Implement guarded existing rule compilation/full-scope aggregation and metadata decisions; unknown scope uses call_llm. No arbitrary generated regex or new fact text.
- [x] Rerun new + existing host logic, typed-host, win-condition and xinshijie tests; project gate. Expected: PASS. If an old semantic expectation is wrong, reproduce a truth-bound counterexample and ledger the ruling before changing it; scoring tests remain TS-07 work.

### Task 3: Versioned deterministic LRU cache and service integration

**Files:** create backend/app/host_cache.py; modify runtime.py/game_service.py/ai_host.py/main.py/schemas.py/game_store.py only after TS-05 review; tests test_versioned_host_cache.py, test_cache_policy.py and transaction/API regressions.

**Interfaces:** frozen HostCacheKey(soupId,puzzleVersion,ruleVersion,engineVersion,normalizationVersion,questionKey). DeterministicHostCache(capacity=1024,ttl_seconds=600,clock=time.monotonic).get(key)->HostResult|None, put(key,result)->bool, clear(), snapshot()->aggregate counts. HostResult cacheHit/contextIndependent program-owned defaults False. handle_host_response(...,*,versions:HostVersions|None=None); verified pinned versions supplied by game_service, new engine identity host-v3; old saved versions unchanged.

- [x] Write 1024+1 evicts exactly LRU, TTL 599.999 hit/600 miss without access renewal, version dimensions isolated, 40 concurrent operations bounded, independent copies/invalid result refusal. LLM/errors/reminders/win/context-dependent or unversioned marker-only results not cached; no response remaining/session/request fields stored.
- [x] Write two same-question sessions with different histories and opposite scripted model output; no cross-session cache. Pure same-version hit returns new HostResult/cacheHit but TS-04 charges each session exactly once with its own remaining; changed rule/engine/normalization misses. Active saved responses retain old version/replay identity.
- [x] Run targeted new cache/service tests. Expected: FAIL missing cache/metadata/pinned-before-host interfaces. Implement locked per-Runtime cache, pass versions before lookup, retain narrow compatibility of old internal helpers without accepting marker strings as proof; keep legacy dict fields inert if required by existing isolation APIs until explicit removal.
- [x] Rerun cache/host/gateway/transactions/recovery/settings tests and project gate. Expected: PASS. Record aggregate cache evidence, not invented latency/real model gains.

### Task 4: Public search boundary and full stage review

**Files:** db.py/main.py; tests test_public_search_boundary.py; docs/ts06-status.md/docs/test-runtime.md/this ledger.

- [x] Write private-only bottom/bottomSummary/fact query cannot select a Soup; title/surface/tag still search; list/playing/error do not expose private fields. Pair authorized evaluate/ended recovery with intact truth and hidden/unlocked behavior. Expected targeted FAIL current private search match.
- [x] Limit search to public metadata, update inaccurate docs/comments, no broader authentication rewrite. Rerun paired API/privacy/legacy tests. Expected PASS.
- [x] Run scripts/verify-test-isolation.ps1, npm run typecheck, git diff --check. Expected exit 0/real data hash unchanged; preserve all explicit skips and warnings.
- [x] One independent read-only stage review, re-grade effects and make one Important/Critical RED→GREEN fix pass/full gate. Map A22–A25 with actual proofs and preserved TS-10/11/12/13/real-provider/topology limits. Continue TS-07 without a user stage prompt.

## Self-review and interface pre-flight

1→2 evidence IDs belong to actual pinned source records, not match confidence; rule decisions cannot change versions. 2→3 only program-owned contextIndependent whole-scope results eligible, keys built from shared exact normalization not retrieval transforms. 3→TS-04 charge response assembled per-session after cache; engine host-v3 marks new behavior without changing old saved results. 4 keeps public metadata and legal reveal distinct. Tests added for all five Review Focus conditions; no future persisted release schema or quality sign-off inferred.
