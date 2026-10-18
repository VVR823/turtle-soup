# Task4 benchmark source-backed execution notes (design only)

Task3 full44194 owns product/tests freeze. These notes do not imply implementation
or any measured P50/P95. Original Task4/spec/200sessions1000turns5000audits/3warmups/
20samples remain binding; do not replace with UI105sessions or prior query-plan
fixture200sessions5000audits lacking1000turns.

Actual turns schema requires id/session/request/payload_hash/question/state,
puzzle_version/rule_version/engine_version/created_at; optional completed_at,
charged0/1 and kinds answer/reminder/system_error/win. One reserved active turn
per session is enforced. Statistical volume must use declared synthetic completed
or failed rows, not1000 active reservations, fake approval receipts or a claim of
1000 genuine user interactions. Source versions come from actual registered
baselines, not guessed current-version hashes. Typed fullAuditEvent/AttemptDetails
envelopes and matching SQL id/type/time/source columns remain necessary.

Measurement design: only new owned TemporaryDirectory/Settings.for_test/isolated
Runtime with explicit safe fixture sources/phase4. No path CLI/output overwrite,
model/API/real dotenv/private catalog or user DB read. Actual sizes verified by
independent SQL counts/expected traffic classes/successful charged predicate and
every actual query result. Use known test/synthetic/legacy exclusions, failures
or reminders cannot become successes. No injected latencies or guessed numbers.

Capture actual production summary/group statements/parameter dictionaries from
actual reader observation. Same fixed SQLite statement batch before/after five
004 indexes is a separate comparison, NOT fullreader performance: phase4 verifier
correctly refuses missing indexes, so never bypass it to claim old-schema reader
speed. For comparison use only owned benchmark schema/transient indexes, clearly
label batch, reestablish exact4/verifier before measuring real query_metrics.
Prefer fresh/cached_statements=0 connections for actual EXPLAIN after schema
change; don't mistake a previously prepared plan for a current index plan.

Three warmups and twenty measured runs; nearest-rank P50/P95 from all actual
sorted samples (for1..20,95th=19). End-to-end reader reported separately, including
schema verification/connection/closed projection. CPU process time and Python
tracemalloc peak labelled accurately, not RSS, physical core count or server
capacity. Record actual Python/SQLite/platform/os.cpu_count (logical)/ownedDB+WAL
file bytes/actual query plans. Error phases/codes recorded without raw values;
no success quantiles for failed runs. Current backend3-second deadline still
applies to real reader. Resource fields are local synthetic measurements, not
production throughput/SLA or actual model correctness.

Task2 source proof is already119 controls+reader full; native211 fixture/backend,
334frontend/type/lint0 and32realEdge are current broader partial evidence, not
Task4 measurement. Task3 current whole-gate still pending; complete after actual
terminal/JUnit/normalAPIcleanup/original239 hashes, then native benchmark RED and
minimal implementation. One final wholeTS16 fresh reviewer only after measured
evidence/docs/current gates; no per-unit/second reviewer or public/prod mutation.
