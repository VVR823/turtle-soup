# TS-06 grounded decisions, evidence and exact deterministic cache

Architectural implementation of approved TS-06/A22–A25, D9/D14/D21/D22. Human intent: zero-new-payment, real-user playable recruiting project; ordinary questions remain smooth, semantic uncertainty is not malformed output. The user explicitly delegates local decisions and continuous execution; spec/plan self-review replaces repeated approval menus, not production/paid/public/private-data authority. TS-05 source remains frozen while its independent review runs; this file is planning only.

## Choice and scope

Selected: focused pure normalization/evidence/rule/cache modules plus existing host/game service, with strict whole-question or completely covered clause decisions. Keep full pinned truth and recent history in the existing free-model fallback. A new embedding/vector service would add unverified operations and does not prove truth. Keeping low-similarity checkpoint answers would retain known negation/subject errors. Do not create a second game engine, arbitrary regex generator, general-purpose semantic parser or model judge.

Fix deterministic false equivalences, not promise universal understanding. A known authored rule can decide only within its explicit scope. An unsupported question proceeds to context-aware model judgment; this is a normal path, not a 422/system_error. Existing malformed provider output handling is unchanged. Real semantic quality remains TS-11/12 external evidence, not FakeModel accuracy.

## Exact identity

normalize_exact_question(text)->str, normalizationVersion exact-v1: Unicode NFC, trim ends, fold runs of whitespace to one space, remove only a terminal run of ASCII/fullwidth question marks (and then trim). Preserve casing, negation, subject, digits, times, conditions and all other punctuation. Empty/non-string input is invalid. Thus composed/decomposed Unicode and terminal question marks may share a key; '小明是凶手'/'小明不是凶手', '3'/'4', commas/periods are distinct. Retrieval's separate normalization may rank candidates but never supplies exact keys for cache/conflicts/publication.

## Grounding and rule decision boundary

Derive immutable evidence views from the already-validated session Soup/puzzle version: full truth, truthItems, checkpoints, authored confusion records and metadata. Each evidence ID is content-addressed from soupId/puzzleVersion/source category/source index/canonical record; every retrieval result carries the same identity/version and source path. EvidenceRecord.payload is the complete canonical JSON string, immutable rather than a mutable dictionary hidden in a frozen wrapper. The compiler verifies the supplied p1 version against the canonical actual Soup snapshot; a plausible hash string alone is not evidence binding. Only existing records produce IDs, no question-generated facts or inferred missing truth. Unversioned standalone calls can retain full truth context but cannot claim verified cross-session evidence/cache.

Replace rag.match_user_query direct-answer usage with bounded candidate evidence ranking, retaining complete records (not deleted negation/subjects). A weak score, shared keyword, edit distance or candidate existence never selects the answer. build_puzzle_context may incorporate selected whole evidence but still keeps full truth and bounded history (12 complete valid turns / 8000 chars). Private evidence is internal, never public search or playing DTO.

Deterministic decisions use exact authored full questions/explicit safe aliases, precise metadata questions and guarded legacy authored rules. The rule decision records scope, source IDs, versions and explicit context independence. Guard changed subjects/polarity/quantity/time/conditions; an unanchored legacy regex is not sufficient to lock an answer. Context/identity references and relationship questions cannot be short-circuited by a generic exact/checkpoint match. Explicit whole-question authored compound rules may decide their own complete scope; otherwise every independent clause must be supported to aggregate. One supported clause does not prove remaining clauses. Ambiguous/unsupported scopes go to the model with original text and history, not a guessed partial answer.

Genre is only a genre fact. '变格' cannot imply every magic/time-travel/ghost element. A supernatural element decision requires actual specific pinned evidence or an exact authored rule; missing/unknown evidence does not become '是'. Precise genre question forms handle negative wording; mixed/unsupported forms defer. Preserve authored cast-count semantics but do not mistake subset/conditional/different-subject counts for total castCount.

Snapshot safety: do NOT add Soup fields and thereby invalidate existing immutable p1/r1 payload field sets, mutate stored baselines or silently migrate them. Compile evidence/guarded rules in memory from the pinned snapshot. Future published exact rules and their compatible versioned release decoding remain TS-10/13 work; only the reusable exact normalization/conflict-safe types are prepared here. No synthetic fact ID is treated as independent human proof.

## Cache

Runtime-owned locked LRU, default capacity 1024, TTL 600 monotonic seconds from insertion. Key includes soupId, puzzleVersion, ruleVersion, engineVersion, normalizationVersion and normalized whole question. Repeated access updates LRU order but not TTL; eviction removes individual entries, never wholesale reset. Expire at now>=expiresAt. Copy and revalidate stored/retrieved HostResult; never cache HTTP bodies, remaining count, IDs or player state.

Cache only pure context-independent deterministic answer results whose source/evidence/versions satisfy the program-owned decision boundary. LLM, context-dependent/partial legacy match, win/random special narration, progress/reveal reminders and failures bypass. A matchedCheckpoint string alone does not prove purity. Hit/miss/eviction/expiry counts are aggregate, no private input. Request result adds internal cacheHit/contextIndependent metadata for later typed Trace consumption; provider HostJudgment cannot choose them. No model output cached across sessions. Original TS-03 cache-safety tests are refined from broad marker eligibility, not discarded.

Pass pinned versions into the host before lookup/decision, not attach them only after. New behavior uses a new engine identifier; old saved turn responses keep their stored versions and replay unaffected. A cache hit still goes through TS-04 finish_turn for current per-session remaining/atomic charge. Standalone legacy host calls without verified versions never use cross-session cache.

## Public boundary and tests

Public list/search matches title/surface/tags only, not bottom/bottomSummary/truth existence. Pair tests: playing/search does not leak; authorized reveal/ended recovery still returns that game's truth. Preserve difficulty, hidden/unlimited/always_yes/win/unlock behavior, ordinary yes/no forms and existing confirmed rule fixtures; wrong legacy expectations are changed only with a named counterexample/ruling, not to make red disappear. Scoring deficiencies stay required TS-07, not silently fixed from this design.

Validation: exact key minimal pairs; same/different soup/version evidence IDs; negative/subject/quantity/time/conditions; weak-match no lock; magic absent/time travel only; genre negative; partially covered compound; two histories with opposite '他死了吗' requiring context fallback; model cache bypass; 1024+1/600s boundaries, concurrent LRU, copy isolation and version misses; atomic remaining not cached; public search and legal reveal pair; full offline/hash gate and one independent stage review. No new dependency/service/model calls, no production deployment or migration.

## Self-review

A22 rule/evidence task, A23 precise metadata task, A24 context/version/public-boundary task, A25 normalization/cache task all covered. Normal-language deferral and protocol invalidity separate. Immutable baseline compatibility is explicit. Future approval/release schema and audit integrations not pretended complete. Human independent labels/real model quality require their later gates.
