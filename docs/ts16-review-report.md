Review completed: **0 Critical, 5 Important, 3 Minor. Assessment: With fixes.** TS16 should not yet be marked LOCAL ENGINEERING COMPLETE.

This is one independent whole-stage, read-only review. Findings below are verified by source inspection; their reproducers are proposed native tests, **not tests I executed**.

## Scope, identity, and evidence

I first read the complete review package, then the complete TS16 design and implementation plan. I read all 35 scoped registry entries: the 9 changed entries and 26 registry additions, including implementations, native tests, frontend contracts/panel/integration, owned fixtures, benchmark, browser test, and stage documentation. The 26 additions are additions to the registry, not a claim of 26 newly created files.

I also traced relevant schema, baseline validation, runtime lifecycle, authentication, body handling, rate accounting, audit envelope/storage/collector, feedback provenance, and Agent context/manifest consumers. I applied the complete gstack two-pass checklist and requesting-code-review template expectations, followed by a self-check of each reported finding.

Snapshot verification:

| Item | Result |
|---|---|
| Source registry | 350 entries; every hash matched |
| Evidence registry | 189 entries; every hash matched |
| Source manifest SHA256 | `2CECFAD0C2E75274A1B0F6EEEF10EE40CF4EF3FADD6B799FC6219D7E7B8C18B5` |
| Evidence manifest SHA256 | `EB30AF62D98F1798A8C51E591F937A2C9AC512088F14707A0D9EE0301AB63D0B` |
| HEAD | `c5765b68cb251a7c566e76e2887d335d6ed6b285` |
| Branch | `codex/ts02-storage-foundation` |
| Index SHA256 | `45C635EFDD2844F5A8DAC3CF3B6B7FBB4CAA6A54A2F247F3F8CC902C4CA275F5` |
| Final source recheck | 350 matches; index unchanged |

There is no invented origin, base branch, PR, or commit range in this review.

I inspected current gate logs/JUnit, the measured benchmark report and its plans/samples, QA reports, the corrected documentation-link evidence, the actual 27-group downloaded aggregate, console/layout artifacts, and stored desktop/mobile screenshots. These support the main agent’s recorded results: 2582 Python passes plus 10 skips, 334 frontend passes, 25 Node passes, 3 API passes, 274 selected passes, and 32 stored Edge passes. Eval’s 412 records are included in Python’s total. I did not execute those gates.

The original 239 runtime-file preservation result is supported by the supplied artifacts; I did not independently read or rehash private runtime contents.

No files were edited or written, no tests or servers launched, no networking/browser/provider/install operations performed, and no additional reviewers or agents dispatched.

## Strengths

- **Migration scope is restrained.** [migrations.py:143](D:/CODE/turtle-soup/backend/app/migrations.py:143) adds precisely five indexes. The wrapper preserves default target 1, completes earlier phases normally, and places 004 DDL/report/ledger/verification/commit in its own transaction. Native tests cover rollback injection, drift, reruns, and old consumers.

- **The main accounting distinctions are implemented correctly.** [metrics.py:119](D:/CODE/turtle-soup/backend/app/metrics.py:119) counts charged completed answer/win turns independently from HTTP events; retains unlinked feedback; uses observed source versions; includes all six task states and four candidate states; and avoids double-counting generic rule publication.

- **The reader has a coherent bounded lifecycle.** [metrics.py:235](D:/CODE/turtle-soup/backend/app/metrics.py:235) uses a dedicated existing-file connection, query-only transaction, shared deadline, bounded busy waits, progress interruption, and attempted cleanup of every resource. Summary and groups use one database snapshot. The native WAL barrier test exercises this relationship directly.

- **Export completeness is substantive.** [metrics_contracts.py:303](D:/CODE/turtle-soup/backend/app/metrics_contracts.py:303) rejects lookahead before creating an export, constructs a closed projection, and checks UTF-8 bytes. HTTP tests exercise actual 100/101 boundaries. The stored browser artifact contains 27 groups, matching summary/group totals, and is 13,416 bytes.

- **Private UI fencing is well considered.** [MetricsPanel.tsx:47](D:/CODE/turtle-soup/src/components/MetricsPanel.tsx:47) gives token changes fresh component state; filter changes abort and invalidate state; late query/export responses are fenced; exports fetch a fresh backend snapshot. Tests explicitly cover A→B→A resurrection and late downloads.

- **Evidence limitations are mostly stated accurately.** Benchmark data is declared synthetic, all 20 samples are retained, nearest-rank quantiles match the report, and actual plans name all five indexes. Documentation distinguishes Python allocation from RSS, SQL-batch comparison from an old-reader comparison, and publication progress from semantic correctness.

## Critical

None identified within the authorized local scope. This does not constitute production or whole-system security approval.

## Important

### I1 — Feedback provenance can accept incomplete or contradictory evidence

**Confidence: 9/10.**

Location: [metrics.py:86](D:/CODE/turtle-soup/backend/app/metrics.py:86), with classification at line 128.

Motivating code:

```python
CASE WHEN min(json_extract(j,'$.details.soupId'))=max(json_extract(j,'$.details.soupId'))
    THEN min(json_extract(j,'$.details.soupId')) END AS soup,
CASE WHEN min(json_extract(j,'$.details.sourceState'))=max(json_extract(j,'$.details.sourceState'))
    THEN min(json_extract(j,'$.details.sourceState')) END AS source_state
```

```python
CASE WHEN p.traffic IS NOT NULL AND p.soup=f.soup_id AND p.source_state=json_extract(f.j,'$.state') THEN p.traffic
```

`min`/`max` ignore SQL NULL. A valid real submission event plus another matching event whose `soupId` or `sourceState` is missing/null can therefore still produce the valid value and classify the feedback as real. The aggregation also discards submission-event `turn_id`; contradictory linked-turn provenance is not compared with `feedback_items.turn_id`.

**Reproducer:** In the existing synthetic feedback fixture, retain a valid submission audit and add another event with the same feedback ID and creation time, matching envelope and real traffic. Remove its `details.soupId` or `details.sourceState`. Alternatively, for linked feedback, give the duplicate a different mirrored outer/SQL `turn_id`. Query the feedback window.

**Predicted failure:** `counts.feedbackSubmitted` remains 1 rather than moving that feedback to `excluded.unknown`. This contradicts the requirement that missing or conflicting necessary provenance remain unknown.

**Native test:** Extend `test_feedback_provenance_is_batch_bound_and_unknown_explicit` with missing/null provenance and linked-turn disagreement. Preserve its valid identical-duplicate control.

**Fix:** Validate every contributing provenance record before aggregation, make missing values conflict explicitly, and verify linked submission identity against the authoritative feedback/turn relationship. Keep classification batch-based and feedback counting by primary key.

### I2 — Table membership is treated as a verified public-source whitelist

**Confidence: 9/10.**

Locations: [metrics.py:44](D:/CODE/turtle-soup/backend/app/metrics.py:44), [metrics.py:253](D:/CODE/turtle-soup/backend/app/metrics.py:253), and [baselines.py:128](D:/CODE/turtle-soup/backend/app/baselines.py:128).

Motivating code:

```python
soup_value = f"CASE WHEN {soup} IN (SELECT soup_id FROM puzzle_versions) THEN {soup} END"
```

```python
if query.soupId is not None and conn.execute("SELECT 1 FROM puzzle_versions WHERE soup_id=? LIMIT 1", (query.soupId,)).fetchone() is None:
```

The verifier validates snapshots referenced by the **active** manifest:

```python
for soup_id, version in manifest["puzzleVersions"].items():
    soup = session_soup(conn, version)
```

It does not validate every other `puzzle_versions` row. The table permits inserts and does not enforce payload/digest/identity coherence at insertion.

**Reproducer:** In a synthetic phase-4 database, keep the active baseline intact. Insert an unused, syntactically valid `p1:` row with `payload_json='{}'` and a synthetic private-ID canary as `soup_id`. Insert an in-window real-tagged session using that soup/version. Query or export it; also try the canary as a soup filter.

**Predicted failure:** The unverified canary becomes a public `soupId`, can enter groups/cursors/export, and passes the soup-filter existence check. Active-baseline verification does not reject the unused invalid snapshot.

**Impact:** The promised privacy whitelist is weaker than “verified puzzle snapshot.” A malformed database row can expose arbitrary text or a bearer-ID canary in an otherwise closed aggregate export.

This requires malformed stored data; it is not a claim that ordinary HTTP clients can insert these rows.

**Native test:** Extend `test_unknown_scope_never_exports_untrusted_identifiers` with an invalid, non-active registered snapshot. Assert unavailable/null projection according to the chosen corruption policy, no canary in page/cursor/export, and rejection as a public filter.

**Fix:** Use a genuinely verified public-source set for both projection and filters. Preserve legitimate historical sources through explicit verification; do not equate arbitrary table existence with verification.

### I3 — A stalled request can leave the metrics panel busy indefinitely

**Confidence: 10/10.**

Location: [MetricsPanel.tsx:69](D:/CODE/turtle-soup/src/components/MetricsPanel.tsx:69).

Motivating code:

```typescript
if (!adminToken || active.current || mode !== 'query' && !page) return;
```

```typescript
const response = await fetch(...);
```

```typescript
const raw: unknown = await response.json();
```

There is no request timer or timeout signal. The three operation buttons remain disabled while `operation` is active. Backend SQL deadlines do not bound a connection that stalls before reaching the backend, or a response body that never finishes.

**Reproducer:** Make `fetch` remain pending, or return a response whose `json()` remains pending. Click query, next, or export and leave token/filters unchanged.

**Failure:** The panel keeps “正在处理统计” indefinitely and provides no timeout recovery. Changing a filter or leaving the page can abort it, but the requested timeout-and-retry lifecycle is absent.

**Native test:** Add Vitest fake-timer cases for stalled fetch and stalled body parsing, including mocks that honor and ignore abort. Assert timeout notice, re-enabled operations, and rejection of late results/downloads.

**Fix:** Add an owned bounded operation timer covering fetch and decoding. Timeout must explicitly release busy state and show recovery guidance while preserving epoch fencing. Merely calling `abort()` is insufficient because `current()` then becomes false and existing cleanup skips state release.

### I4 — Coverage decoder coercion can display unknown coverage as complete

**Confidence: 10/10.**

Locations: [metrics-contract.ts:93](D:/CODE/turtle-soup/src/lib/metrics-contract.ts:93), line 105, and [MetricsPanel.tsx:143](D:/CODE/turtle-soup/src/components/MetricsPanel.tsx:143).

Motivating code:

```typescript
|| !['complete', 'partial', 'unknown'].includes(String(data.state))) return invalid();
```

```typescript
processAudit, state: data.state as MetricsCoverage['state'] };
```

The display subsequently compares the retained value with string literals and uses the final branch for complete coverage.

**Reproducer:** Take the existing otherwise-valid `metricsPage()` fixture, retain null coverage epochs/process status, and replace `coverage.state` with `["unknown"]`.

**Failure:** `String(["unknown"])` passes the allowlist. The array is retained, bypasses the string `"complete"` proof check, and matches neither `"unknown"` nor `"partial"` in the panel. The panel displays “此刻已知审计覆盖完整”.

**Impact:** A malformed response becomes an affirmative coverage claim, directly violating strict frontend decoding and unknown-coverage semantics.

**Native test:** Add contract rejection cases for single-element arrays containing each state. Add a panel case asserting a contract error and absence of the complete-coverage message.

**Fix:** Require `typeof data.state === 'string'` before enum membership and retain only that validated string.

### I5 — Ambiguous duplicate JSON metadata can select real over test

**Confidence: 9/10.**

Locations: [metrics.py:37](D:/CODE/turtle-soup/backend/app/metrics.py:37), lines 82–83 and 115–116. Surrounding strict parsing: [baselines.py:29](D:/CODE/turtle-soup/backend/app/baselines.py:29).

Motivating code:

```python
return f"CASE WHEN json_valid({expression}) THEN {expression} ELSE '{{}}' END"
```

```python
AND json_extract(a.j,'$.details.trafficClass') IN ('real','test','synthetic','legacy')
THEN json_extract(a.j,'$.details.trafficClass') ELSE 'unknown' END AS traffic
```

JSON syntax validity does not require unique object keys. SQLite extraction selects a matching duplicate member rather than establishing an unambiguous classification. Consequently, metadata containing both real and test under the same `trafficClass` key can be classified by whichever member extraction selects.

The normal writers reject ambiguous JSON through strict parsing; that does not protect this reader’s explicitly required malformed-storage boundary.

**Reproducer:** In a synthetic database, store an otherwise coherent HTTP event whose `details` contains duplicate `trafficClass` members, one real and one test. Keep envelope columns aligned. Repeat in both orders. A corresponding manifest mutation exercises `run_source`.

**Predicted failure:** One ordering enters real counts instead of `excluded.unknown`. Existing cursor duplicate-key tests do not cover stored audit/manifest metadata.

**Native test:** Add duplicate-key classification cases for audit and run metadata, asserting unknown for both orders and unchanged valid controls. Construct the ambiguity in raw JSON rather than a Python dict.

**Fix:** Reject ambiguous relevant source objects before extracting classification or dimensions. This can remain within SQL, for example by detecting duplicate keys per object using JSON traversal. Retain the deadline and aggregate-only Python projection.

## Minor

### M1 — SQLite busy/interruption during baseline verification can become “unavailable”

**Confidence: 9/10.**

Locations: [baselines.py:114](D:/CODE/turtle-soup/backend/app/baselines.py:114), line 143, and [metrics.py:264](D:/CODE/turtle-soup/backend/app/metrics.py:264).

Motivating code:

```python
except (ValueError, TypeError, KeyError, AttributeError, sqlite3.Error) as error:
    raise SnapshotError("Invalid rule release") from error
```

```python
except Exception:
    raise MetricsError("metrics_unavailable", 503) from None
```

**Reproducer:** Cause a native SQLite interruption during a baseline query inside `verify_schema`, rather than during the initial table lookup or aggregate statement.

**Failure/impact:** The baseline helper wraps the SQLite error. The reader’s SQLite-code handler no longer sees it, and emits `metrics_unavailable` instead of the specified `metrics_busy`. The request still fails safely with 503, so this is a diagnostic-contract issue.

**Native test:** Target an actual baseline SELECT with native progress interruption; assert `metrics_busy`, closed connection, and no raw diagnostics.

**Fix:** Preserve controlled busy/interruption classification across verifier wrapping, using the exception chain or a narrowly scoped translation. Keep genuine snapshot corruption unavailable.

### M2 — Benchmark fixture omits the specified unknown class and coverage-clock setup

**Confidence: 10/10.**

Location: [benchmark_metrics.py:45](D:/CODE/turtle-soup/backend/app/scripts/benchmark_metrics.py:45).

Motivating code:

```python
traffic = ("real", "test", "synthetic", "legacy")
```

The migration uses the current wall clock, while seeded timestamps begin at 100/1000 seconds and the query begins at epoch zero. No independent migration clock is fixed. The measured report confirms all unknown counts are zero.

**Impact:** The benchmark does not implement the design’s five-class fixture or its fixed-clock/post-coverage setup. Separate query tests cover unknown behavior, so this does not invalidate the measured valid-class results. It does limit fixture compliance and what the benchmark demonstrates.

**Native test:** Verify a nonzero independently derived unknown count while retaining exactly 200/1000/5000 rows; verify the declared fixture clock/window relationship.

**Fix:** Include declared unknown audit metadata and use an explicit fixture clock or post-coverage timestamps. Preserve old measured artifacts as historical evidence and generate a separately identified measurement.

### M3 — The measured reader profile excludes complete JSON serialization

**Confidence: 10/10.**

Location: [benchmark_metrics.py:161](D:/CODE/turtle-soup/backend/app/scripts/benchmark_metrics.py:161). HTTP serialization is at [routers/metrics.py:32](D:/CODE/turtle-soup/backend/app/routers/metrics.py:32).

Motivating code:

```python
page = metrics.query_metrics(runtime, query)
if page.summary.model_dump(mode="json") != expected:
    raise ValueError("Measured reader changed its counts")
```

The timed call does not serialize the complete page with `model_dump_json`, whereas the design expressly includes serialization in the complete-reader measurement.

**Impact:** The 90.63/92.49 ms numbers support query/model projection plus summary checking, not complete response serialization. This is a measurement-scope discrepancy, not evidence that the numbers are fabricated.

**Native test:** Exercise complete page serialization and parse/validate the resulting JSON within the measured call; retain sample count and independently checked totals.

**Fix:** Either include complete serialization in that profile or explicitly rename its scope and add the promised serialization-inclusive profile.

## Recommendations

Resolve I1–I5 in the authorized single scoped fix pass, using native failing tests before fixes. Keep valid provenance, valid historical-source, token/filter fencing, and export-boundary controls alongside the new negative cases.

Treat M1–M3 individually rather than silently folding them into larger work. M1 is a narrow error-translation change; M2 requires fixture expectations and fresh measured evidence; M3 requires a precisely labeled measurement update. Historical artifacts should remain intact.

The same-database sequential index removal/restoration differs from the design’s two-database wording, but fresh connections prepare the same captured SQL against unchanged synthetic content. I accept that implementation choice for the stated local SQL-batch comparison; it does not establish cold-cache or causal production speedup.

## Declined to judge

Each item below remains explicit for the main task’s individual ruling.

- **D1 — Real model answer accuracy or repair correctness:** no provider execution or independent semantic-quality evidence was reviewed; mechanical counts and regression passes cannot establish it.
- **D2 — Genuine human annotation/review quality:** synthetic `humanConfirmed` fixtures exercise contracts, not actual independent human judgment.
- **D3 — Provider availability, account eligibility, pricing, or free quota:** networking/provider inspection was prohibited; no current external verification was performed.
- **D4 — Actual production usage, satisfaction, or operational traffic totals:** only declared synthetic fixtures and authorized aggregate artifacts were inspected.
- **D5 — Stable unique-user counts:** the system has no qualifying identity basis; session counts do not answer that question.
- **D6 — Production 004 migration and real-database integrity:** production/private rows were outside permission; local migration tests do not authorize or prove production migration.
- **D7 — Production backup, latest-data recovery, rollback, and old-writer inventory:** these require operational evidence, including external writers; they remain TS17/production boundaries.
- **D8 — Deployment, TLS, SSH, reverse-proxy configuration, and remote CI:** no external environment or remote execution was inspected.
- **D9 — Production concurrency, QPS, SLA, large-catalog/history scalability, RSS, or provider latency:** the stored benchmark is a small local instrumented synthetic measurement, with no such workload.
- **D10 — Unsupported-platform behavior:** Windows evidence does not prove Unix-socket or unavailable symlink-privilege paths. The 10 recorded skips remain skips.
- **D11 — Exhaustive security/secret audit:** the corrected documentation checker establishes link existence and limited pattern results, not absence of all secrets or vulnerabilities.
- **D12 — Exhaustive accessibility or human usability quality:** stored screenshots and the 375/375 DOM result support the tested layout boundary; no complete accessibility or human study occurred.
- **D13 — TS15 deferred malformed-private-detail frontend combination checks:** explicitly retained for TS17; this review does not close or re-review that existing Minor.
- **D14 — TS15 deferred task observation after returning from a hidden tab:** explicitly retained for TS17; manual observation does not prove automatic resumption.
- **D15 — Missing-corpus browser branch:** the prior limitation remains. Native/HTTP/React evidence is not substituted for its absent browser coverage.
- **D16 — Cross-request frozen snapshots and arbitrary-size exports:** explicitly excluded by TS16. Fixed-window live snapshots and whole-export refusal were judged against their actual contract.
- **D17 — Public export/publication or credential transport outside the local instance:** no upload/publication was authorized or performed; private local export is not public-release approval.
- **D18 — Original plan’s “subsequent regression failures” statistic:** the original plan mentions it, while the frozen TS16 specification enumerates nine different fields and no authoritative post-publication failure stream. I did not invent a tenth metric or count candidate pre-publication failures as that statistic. The scope difference needs an explicit main-task ruling.
- **D19 — Replaying live Agent authorization/corpus checks merely to count historical records:** metrics is statistical observation, not an authority grant. This review does not certify every historical business artifact or require stale historical tasks to regain current authorization.
- **D20 — Independent preservation of private runtime bytes:** I checked the supplied preservation evidence, not the private files themselves.
- **D21 — Completion of all 18 stages:** this report assesses TS16 only and does not close TS17, TS18, or the overall goal.

## Assessment

**With fixes.** The stage has substantial local engineering evidence and a sound core accounting/export design. I1–I5 leave actionable gaps in provenance, privacy projection, timeout recovery, and strict boundary validation; they should be resolved before TS16 is declared locally complete. No Critical issue was established, and no production, human-quality, or all-stage approval is implied.

**Status: DONE_WITH_CONCERNS.** This is the full initial independent report; no unsolicited second review was performed.
